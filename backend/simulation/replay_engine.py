"""
Historical Replay Engine — Phase 5.2

Sequential, point-in-time time-series simulation engine executing the full Trading Desk pipeline:
PIT MarketContext -> Specialists -> Evidence Aggregation -> Debate -> Investment Committee -> Safety -> Paper Broker -> Portfolio.
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Union
import uuid

from backend.application.evidence_aggregator import EvidenceAggregator
from backend.application.specialist_orchestrator import SpecialistOrchestrator
from backend.debate.debate_orchestrator import DebateOrchestrator
from backend.domain.agents import BaseAgent
from backend.domain.execution_schemas import (
    ExecutionDecision,
    OrderSide,
    OrderStatus,
    RejectionReason,
)
from backend.domain.investment_committee_schemas import (
    DecisionAudit,
    ExecutionPlan,
    InvestmentAction,
    InvestmentDecision,
    InvestmentDecisionState,
    InvestmentHorizon,
    InvestmentThesis,
    PositionSizing,
)
from backend.domain.schemas import (
    AgentInput,
    HistoricalWindow,
    MarketContext,
    UnifiedEvidencePackage,
)
from backend.execution.audit import ExecutionAuditManager
from backend.execution.paper_broker import PaperBroker
from backend.execution.portfolio import PaperPortfolio
from backend.execution.safety_engine import ExecutionSafetyEngine
from backend.investment_committee.committee_agent import InvestmentCommitteeAgent
from backend.simulation.performance import PerformanceEngine
from backend.simulation.pit_filter import PointInTimeFilter, _parse_timestamp
from backend.simulation.report import SimulationReportBuilder
from backend.simulation.simulation_config import SimulationConfig
from backend.simulation.simulation_state import (
    DataQualityStatistics,
    DecisionJournalEntry,
    EquityCurvePoint,
    SimulationReport,
    TradeJournalEntry,
)


class HistoricalReplayEngine:
    """
    Executes a strict point-in-time paper trading simulation over historical market data.
    """

    def __init__(
        self,
        config: Optional[SimulationConfig] = None,
        specialists: Optional[List[BaseAgent]] = None,
        specialist_orchestrator: Optional[SpecialistOrchestrator] = None,
        evidence_aggregator: Optional[EvidenceAggregator] = None,
        debate_orchestrator: Optional[DebateOrchestrator] = None,
        committee_agent: Optional[InvestmentCommitteeAgent] = None,
        safety_engine: Optional[ExecutionSafetyEngine] = None,
        broker: Optional[PaperBroker] = None,
        performance_engine: Optional[PerformanceEngine] = None,
    ) -> None:
        self.config = config or SimulationConfig()
        self.specialists = specialists or []
        self.specialist_orchestrator = specialist_orchestrator or SpecialistOrchestrator()
        self.evidence_aggregator = evidence_aggregator or EvidenceAggregator()
        self.debate_orchestrator = debate_orchestrator
        self.committee_agent = committee_agent
        self.safety_engine = safety_engine or ExecutionSafetyEngine()
        self.broker = broker or PaperBroker(
            initial_cash=self.config.initial_cash,
            commission_rate=self.config.commission_rate,
            slippage_rate=self.config.slippage_rate,
            transaction_fee_flat=self.config.transaction_fee_flat,
            safety_engine=self.safety_engine,
        )
        self.performance_engine = performance_engine or PerformanceEngine()

    def _extract_timeline(
        self, historical_datasets: Dict[str, Union[MarketContext, Dict[str, Any]]]
    ) -> List[datetime]:
        """Extract sorted list of unique simulation timestamps from historical data."""
        timestamps: Set[datetime] = set()
        for symbol, data in historical_datasets.items():
            ohlcv = []
            if isinstance(data, MarketContext):
                ohlcv = data.ohlcv_historical
            elif isinstance(data, dict):
                ohlcv = data.get("ohlcv_historical") or data.get("bars", [])

            for bar in ohlcv:
                ts = _parse_timestamp(bar.get("timestamp") or bar.get("date"))
                if ts:
                    if self.config.start_date <= ts <= self.config.end_date:
                        timestamps.add(ts)

        return sorted(list(timestamps))

    async def run(
        self,
        historical_datasets: Dict[str, Union[MarketContext, Dict[str, Any]]],
        benchmark_bars: Optional[List[Dict[str, Any]]] = None,
    ) -> SimulationReport:
        """
        Execute full chronological replay simulation.
        """
        timeline = self._extract_timeline(historical_datasets)
        if not timeline:
            # Fallback if start_date/end_date filter has no match: use all available dates
            all_ts: Set[datetime] = set()
            for symbol, data in historical_datasets.items():
                ohlcv = data.ohlcv_historical if isinstance(data, MarketContext) else data.get("ohlcv_historical", [])
                for bar in ohlcv:
                    ts = _parse_timestamp(bar.get("timestamp") or bar.get("date"))
                    if ts:
                        all_ts.add(ts)
            timeline = sorted(list(all_ts))

        start_date = timeline[0] if timeline else self.config.start_date
        end_date = timeline[-1] if timeline else self.config.end_date

        self.broker.reset(initial_cash=self.config.initial_cash)
        data_quality = DataQualityStatistics()
        equity_curve: List[EquityCurvePoint] = []
        trade_journal: List[TradeJournalEntry] = []
        decision_journal: List[DecisionJournalEntry] = []

        running_peak_equity = self.config.initial_cash
        prev_equity = self.config.initial_cash

        # Benchmark mapping
        benchmark_map: Dict[datetime, float] = {}
        if benchmark_bars:
            for bar in benchmark_bars:
                bts = _parse_timestamp(bar.get("timestamp") or bar.get("date"))
                if bts:
                    benchmark_map[bts] = float(bar.get("close", 0.0))

        benchmark_initial: Optional[float] = None
        benchmark_final: Optional[float] = None
        if timeline and benchmark_map:
            benchmark_initial = benchmark_map.get(timeline[0])
            benchmark_final = benchmark_map.get(timeline[-1])

        # Chronological loop
        for current_time in timeline:
            # 1. Update prices of existing open positions in portfolio
            for symbol, data in historical_datasets.items():
                raw_ctx = (
                    data
                    if isinstance(data, MarketContext)
                    else MarketContext(
                        context_id=f"ctx-{symbol}",
                        symbol=symbol,
                        data_timestamp=current_time,
                        current_price=data.get("current_price", 100.0),
                        provider="REPLAY",
                        ohlcv_historical=data.get("ohlcv_historical", []),
                        fundamental_data=data.get("fundamental_data", {}),
                        news_data=data.get("news_data", {}),
                        institutional_data=data.get("institutional_data", []),
                    )
                )
                pit_ctx = PointInTimeFilter.filter_market_context(raw_ctx, as_of=current_time)
                if pit_ctx.current_price > 0:
                    self.broker.portfolio.update_price(symbol, pit_ctx.current_price)

            # 2. Evaluate symbols scheduled for this simulation step
            for symbol in self.config.symbols:
                if symbol not in historical_datasets:
                    continue

                raw_data = historical_datasets[symbol]
                if isinstance(raw_data, MarketContext):
                    raw_ctx = raw_data
                else:
                    raw_ctx = MarketContext(
                        context_id=f"ctx-{symbol}",
                        symbol=symbol,
                        data_timestamp=current_time,
                        current_price=raw_data.get("current_price", 100.0),
                        provider="REPLAY",
                        ohlcv_historical=raw_data.get("ohlcv_historical", []),
                        fundamental_data=raw_data.get("fundamental_data", {}),
                        news_data=raw_data.get("news_data", {}),
                        institutional_data=raw_data.get("institutional_data", []),
                    )

                pit_ctx = PointInTimeFilter.filter_market_context(raw_ctx, as_of=current_time)
                data_quality.contexts_processed += 1

                # Track Data Quality Statistics
                if not pit_ctx.fundamental_data:
                    data_quality.missing_fundamentals_count += 1
                if not pit_ctx.news_data or (isinstance(pit_ctx.news_data, dict) and not pit_ctx.news_data.get("articles") and len(pit_ctx.news_data) <= 1):
                    data_quality.missing_news_count += 1
                if not pit_ctx.institutional_data:
                    data_quality.missing_institutional_count += 1

                # Run Full Pipeline if agents/orchestrator provided
                decision: Optional[InvestmentDecision] = None
                spec_successful = 0
                spec_degraded = 0
                spec_failed = 0
                bull_str = 0.0
                bear_str = 0.0
                risk_sc = 0.0

                if self.committee_agent and self.debate_orchestrator:
                    if self.specialists:
                        spec_run_result = await self.specialist_orchestrator.run(self.specialists, pit_ctx)
                        spec_successful = spec_run_result.successful_agents
                        spec_degraded = spec_run_result.degraded_agents
                        spec_failed = spec_run_result.failed_agents

                        if spec_degraded > 0:
                            data_quality.degraded_specialist_runs += 1

                        unified_evidence = self.evidence_aggregator.aggregate(spec_run_result)
                    else:
                        from backend.domain.schemas import NormalizedEvidence, EvidenceCategory, SignalDirection
                        unified_evidence = UnifiedEvidencePackage(
                            run_id="run-pit",
                            context_id=pit_ctx.context_id,
                            symbol=symbol,
                            data_timestamp=pit_ctx.data_timestamp,
                            total_evidence_extracted=5,
                            evidence_items=[
                                NormalizedEvidence(
                                    evidence_id=f"ev-{i}",
                                    specialist_name="Technical",
                                    metric_name="trend",
                                    category=EvidenceCategory.TECHNICAL,
                                    direction=SignalDirection.BULLISH,
                                    context_id=pit_ctx.context_id,
                                    data_timestamp=pit_ctx.data_timestamp,
                                ) for i in range(5)
                            ],
                        )

                    debate_result = await self.debate_orchestrator.run_debate(pit_ctx, unified_evidence)
                    bull_str = debate_result.bull_strength
                    bear_str = debate_result.bear_strength
                    risk_sc = debate_result.risk_score

                    agent_input = AgentInput(
                        symbol=symbol,
                        market_context=pit_ctx,
                        additional_data={
                            "unified_evidence": unified_evidence.model_dump(),
                            "debate_result": debate_result.model_dump(),
                        },
                    )
                    comm_out = await self.committee_agent.execute(agent_input)
                    if comm_out.raw_data and "state" in comm_out.raw_data:
                        decision = InvestmentDecision.model_validate(comm_out.raw_data)
                elif isinstance(raw_data, dict) and "mock_decision" in raw_data:
                    decision = raw_data["mock_decision"]
                else:
                    # Default neutral decision
                    decision = InvestmentDecision(
                        decision_id=f"dec-{uuid.uuid4().hex[:8]}",
                        context_id=pit_ctx.context_id,
                        symbol=symbol,
                        state=InvestmentDecisionState.HOLD,
                        thesis=InvestmentThesis(synthesis="Hold posture"),
                        execution_plan=ExecutionPlan(
                            action=InvestmentAction.HOLD,
                            horizon=InvestmentHorizon.SWING,
                            position_sizing=PositionSizing(is_available=False, recommended_size_pct=0.0),
                        ),
                        audit_trail=DecisionAudit(deterministic_state=InvestmentDecisionState.HOLD),
                        confidence=0.5,
                    )

                # Process Committee Decision through Execution Safety
                order_created = False
                order_filled = False
                exec_decision = ExecutionDecision.BLOCKED

                if decision is not None:
                    # Update committee statistics
                    if decision.state == InvestmentDecisionState.RISK_VETO:
                        data_quality.risk_veto_count += 1
                    elif decision.state == InvestmentDecisionState.DATA_QUALITY_VETO:
                        data_quality.data_quality_veto_count += 1
                    elif decision.state == InvestmentDecisionState.INSUFFICIENT_EVIDENCE:
                        data_quality.committee_insufficient_evidence_count += 1

                    order_req = self.safety_engine.create_order_from_decision(
                        decision=decision,
                        market_context=pit_ctx,
                        portfolio_state=self.broker.portfolio.get_state(),
                        current_price=pit_ctx.current_price,
                    )

                    if order_req is not None:
                        order_created = True
                        exec_res = self.broker.submit_order(
                            order=order_req,
                            market_context=pit_ctx,
                            decision=decision,
                        )
                        if exec_res.status == OrderStatus.FILLED:
                            order_filled = True
                            exec_decision = ExecutionDecision.ALLOWED
                            slippage_cost = abs(exec_res.fill_price - order_req.price) * exec_res.quantity_filled
                            trade_journal.append(
                                TradeJournalEntry(
                                    trade_id=f"trd-{uuid.uuid4().hex[:8]}",
                                    order_id=order_req.order_id,
                                    timestamp=current_time,
                                    symbol=symbol,
                                    side=order_req.side,
                                    quantity=exec_res.quantity_filled,
                                    requested_price=order_req.price,
                                    executed_price=exec_res.fill_price,
                                    slippage=slippage_cost,
                                    commission=exec_res.commission,
                                    total_cost=exec_res.total_cost,
                                    realized_pnl=self.broker.portfolio.realized_pnl,
                                    context_id=pit_ctx.context_id,
                                    run_id=order_req.run_id,
                                    decision_id=decision.decision_id,
                                    committee_decision_state=decision.state,
                                    confidence=decision.confidence,
                                    execution_decision=ExecutionDecision.ALLOWED,
                                    order_status=OrderStatus.FILLED,
                                )
                            )
                        else:
                            data_quality.execution_rejections_count += 1
                            exec_decision = ExecutionDecision.BLOCKED
                            trade_journal.append(
                                TradeJournalEntry(
                                    trade_id=f"trd-{uuid.uuid4().hex[:8]}",
                                    order_id=order_req.order_id,
                                    timestamp=current_time,
                                    symbol=symbol,
                                    side=order_req.side,
                                    quantity=order_req.quantity,
                                    requested_price=order_req.price,
                                    executed_price=0.0,
                                    slippage=0.0,
                                    commission=0.0,
                                    total_cost=0.0,
                                    realized_pnl=0.0,
                                    context_id=pit_ctx.context_id,
                                    run_id=order_req.run_id,
                                    decision_id=decision.decision_id,
                                    committee_decision_state=decision.state,
                                    confidence=decision.confidence,
                                    execution_decision=ExecutionDecision.BLOCKED,
                                    order_status=exec_res.status,
                                    rejection_reasons=[RejectionReason.UNKNOWN],
                                )
                            )

                    # Record Decision Journal
                    current_portfolio_state = self.broker.portfolio.get_state()
                    decision_journal.append(
                        DecisionJournalEntry(
                            timestamp=current_time,
                            symbol=symbol,
                            context_id=pit_ctx.context_id,
                            current_price=pit_ctx.current_price,
                            specialist_count=len(self.specialists),
                            specialists_successful=spec_successful,
                            specialists_degraded=spec_degraded,
                            specialists_failed=spec_failed,
                            bull_strength=bull_str,
                            bear_strength=bear_str,
                            risk_score=risk_sc,
                            debate_status="COMPLETE" if self.debate_orchestrator else "N/A",
                            committee_state=decision.state,
                            committee_action=decision.execution_plan.action,
                            recommended_size_pct=decision.execution_plan.position_sizing.recommended_size_pct,
                            risk_veto_active=(decision.state == InvestmentDecisionState.RISK_VETO),
                            execution_decision=exec_decision,
                            order_created=order_created,
                            order_filled=order_filled,
                            portfolio_equity_after=current_portfolio_state.total_equity,
                        )
                    )

            # 3. Snapshot Portfolio State at timestamp T for Equity Curve
            port_state = self.broker.portfolio.get_state()
            equity = port_state.total_equity
            running_peak_equity = max(running_peak_equity, equity)
            drawdown = running_peak_equity - equity
            drawdown_pct = (drawdown / running_peak_equity) * 100.0 if running_peak_equity > 0 else 0.0
            daily_return = (equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
            cum_return = ((equity - self.config.initial_cash) / self.config.initial_cash) * 100.0

            b_val = benchmark_map.get(current_time)
            b_return = (
                ((b_val - benchmark_initial) / benchmark_initial) * 100.0
                if benchmark_initial and b_val
                else None
            )

            equity_curve.append(
                EquityCurvePoint(
                    timestamp=current_time,
                    portfolio_value=equity,
                    cash=port_state.cash,
                    invested_capital=port_state.total_market_value,
                    gross_exposure=port_state.total_exposure,
                    net_exposure=port_state.total_exposure,
                    drawdown=drawdown,
                    drawdown_pct=drawdown_pct,
                    peak_equity=running_peak_equity,
                    realized_pnl=port_state.realized_pnl,
                    unrealized_pnl=port_state.unrealized_pnl,
                    daily_return=daily_return,
                    cumulative_return=cum_return,
                    benchmark_value=b_val,
                    benchmark_return=b_return,
                    number_of_positions=len(port_state.positions),
                )
            )
            prev_equity = equity

        # 4. Final Performance Calculation & Report Assembly
        metrics = self.performance_engine.calculate_metrics(
            initial_capital=self.config.initial_cash,
            equity_curve=equity_curve,
            trade_journal=trade_journal,
            benchmark_initial=benchmark_initial,
            benchmark_final=benchmark_final,
        )

        return SimulationReportBuilder.build_report(
            simulation_id=self.config.simulation_id,
            config=self.config,
            metrics=metrics,
            data_quality=data_quality,
            equity_curve=equity_curve,
            trade_journal=trade_journal,
            decision_journal=decision_journal,
            start_date=start_date,
            end_date=end_date,
        )
