"""
Phase 9 — End-to-End Trading OS Unified Orchestrator

Coordinates the complete 17-stage analysis-to-execution pipeline:
Market Context -> Specialists -> Evidence -> Debate -> Investment Committee ->
Conviction -> Regime -> Portfolio -> Scenario -> Risk -> Sizing -> Validation ->
Pre-Flight -> Paper Broker -> Simulated Fills -> Portfolio Ledger -> Telemetry -> Run Summary.

FAIL-CLOSED ARCHITECTURE:
If any safety gate (Committee Reject, Risk Veto, Sizing Invalidation, Pre-Flight Breach,
Kill Switch) triggers, downstream execution is immediately halted.
PAPER_ONLY MODE: Strictly offline, deterministic simulation.
Zero real broker credentials, zero real money. Zero LLM math.
"""

from datetime import datetime, timezone
import math
import logging
import time
from typing import Any, Dict, List, Optional
import uuid

from backend.domain.schemas import (
    MarketContext,
    EvidenceSummary,
    SignalDirection,
)
from backend.domain.debate_schemas import DebateResult
from backend.domain.investment_committee_schemas import (
    CommitteeDecision,
    CommitteeRecommendation,
    InvestmentDecisionState,
)
from backend.domain.risk_schemas import (
    RiskAssessmentResult,
    PositionSizingPlan,
    PositionDirection,
)
from backend.domain.preflight_schemas import (
    PreflightOrderRequest,
    PreflightOrderType,
    PreflightSide,
    PreflightStatus,
    ExecutionAuthorizationSnapshot,
    ExecutionPreflightResult,
)
from backend.domain.paper_broker_schemas import (
    PaperOrderStatus,
    PaperOrder,
    PaperExecutionResult,
)
from backend.domain.telemetry_schemas import (
    ExecutionEventType,
    EventSeverity,
    KillSwitchState,
)
from backend.domain.trading_os_schemas import (
    TRADING_OS_VERSION,
    StageStatus,
    PipelineStageResult,
    TradingOSRun,
    TradingOSRunSummary,
)

from backend.application.evidence_aggregator import EvidenceAggregator
from backend.application.debate_engine import DebateEngine
from backend.application.investment_committee import InvestmentCommittee
from backend.application.conviction_calibrator import ConvictionCalibrator
from backend.application.market_regime_engine import MarketRegimeEngine
from backend.application.portfolio_intelligence_engine import PortfolioIntelligenceEngine
from backend.application.scenario_engine import ScenarioEngine
from backend.application.risk_engine import RiskEngine
from backend.application.execution_preflight_engine import ExecutionPreflightEngine
from backend.application.paper_broker_adapter import PaperBrokerAdapter
from backend.application.execution_telemetry_engine import ExecutionTelemetryEngine, global_telemetry_engine
from backend.application.bull_bear_engine import BullBearRiskEngine

logger = logging.getLogger(__name__)


class TradingOSOrchestrator:
    """
    Authoritative application orchestrator uniting Phases 2 through 8.
    Coordinates existing engines without duplicating domain or accounting logic.
    """

    def __init__(
        self,
        evidence_aggregator: Optional[EvidenceAggregator] = None,
        debate_engine: Optional[DebateEngine] = None,
        committee: Optional[InvestmentCommittee] = None,
        conviction_calibrator: Optional[ConvictionCalibrator] = None,
        regime_engine: Optional[MarketRegimeEngine] = None,
        portfolio_engine: Optional[PortfolioIntelligenceEngine] = None,
        scenario_engine: Optional[ScenarioEngine] = None,
        risk_engine: Optional[RiskEngine] = None,
        preflight_engine: Optional[ExecutionPreflightEngine] = None,
        paper_broker: Optional[PaperBrokerAdapter] = None,
        telemetry_engine: Optional[ExecutionTelemetryEngine] = None,
        bull_bear_engine: Optional[BullBearRiskEngine] = None,
    ):
        self.evidence_aggregator = evidence_aggregator if evidence_aggregator is not None else EvidenceAggregator()
        self.debate_engine = debate_engine if debate_engine is not None else DebateEngine()
        self.committee = committee if committee is not None else InvestmentCommittee()
        self.conviction_calibrator = conviction_calibrator if conviction_calibrator is not None else ConvictionCalibrator()
        self.regime_engine = regime_engine if regime_engine is not None else MarketRegimeEngine()
        self.portfolio_engine = portfolio_engine if portfolio_engine is not None else PortfolioIntelligenceEngine()
        self.scenario_engine = scenario_engine if scenario_engine is not None else ScenarioEngine()
        self.risk_engine = risk_engine if risk_engine is not None else RiskEngine()
        self.preflight_engine = preflight_engine if preflight_engine is not None else ExecutionPreflightEngine()
        self.telemetry_engine = telemetry_engine if telemetry_engine is not None else global_telemetry_engine
        self.paper_broker = paper_broker if paper_broker is not None else PaperBrokerAdapter(telemetry_engine=self.telemetry_engine)
        self.bull_bear_engine = bull_bear_engine if bull_bear_engine is not None else BullBearRiskEngine()

    # ── Full Pipeline Execution ───────────────────────────────────────────────

    def run_pipeline(
        self,
        market_context: MarketContext,
        specialist_reports: Optional[List[Any]] = None,
        evidence_summary: Optional[EvidenceSummary] = None,
        debate_result: Optional[DebateResult] = None,
        committee_decision: Optional[CommitteeDecision] = None,
        portfolio_state: Optional[Any] = None,
        fill_ratio: float = 1.0,
        evaluation_timestamp: Optional[datetime] = None,
        allow_execution: bool = True,
    ) -> TradingOSRun:
        """
        Execute one complete analysis-to-execution cycle across the Trading OS.
        Deterministic, synchronous, pure-Python orchestration.
        """
        now = evaluation_timestamp or datetime.now(timezone.utc)
        start_mono = time.monotonic()

        symbol = getattr(market_context, "symbol", "UNKNOWN")
        run_id = f"run-{uuid.uuid4().hex[:8]}"

        run = TradingOSRun(
            run_id=run_id,
            symbol=symbol,
            started_at=now,
            mode="PAPER_ONLY",
        )

        # Telemetry: Record run start
        self.telemetry_engine.record_event(
            event_type=ExecutionEventType.ORDER_CREATED,
            execution_id=run_id,
            symbol=symbol,
            reason=f"Trading OS End-to-End Pipeline started for {symbol}",
            timestamp=now,
        )

        try:
            # ── 1. Market Context Stage ───────────────────────────────────────
            s_t0 = time.monotonic()
            run.stages["MARKET_CONTEXT"] = PipelineStageResult(
                stage_name="MARKET_CONTEXT",
                status=StageStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                details={"symbol": symbol, "current_price": getattr(market_context, "current_price", 0.0)},
            )
            
            dt = getattr(market_context, "data_timestamp", None)
            run.market_context = {
                "symbol": symbol, 
                "current_price": getattr(market_context, "current_price", 0.0),
                "snapshot_id": getattr(market_context, "snapshot_id", ""),
                "freshness_status": getattr(market_context, "freshness_status", ""),
                "cache_hit": getattr(market_context, "cache_hit", False),
                "completeness_status": getattr(market_context, "completeness_status", "UNKNOWN"),
                "data_timestamp": dt.isoformat() if dt else None
            }


            # ── 2. Specialist Reports Stage ───────────────────────────────────
            s_t0 = time.monotonic()
            reports = specialist_reports or []
            run.stages["SPECIALISTS"] = PipelineStageResult(
                stage_name="SPECIALISTS",
                status=StageStatus.COMPLETED if reports else StageStatus.DEGRADED,
                started_at=now,
                completed_at=now,
                duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                details={"count": len(reports)},
            )

            # ── 3. Evidence Aggregation Stage ─────────────────────────────────
            s_t0 = time.monotonic()
            if evidence_summary is None:
                if reports:
                    evidence_summary = self.evidence_aggregator.aggregate(reports)
                else:
                    evidence_summary = EvidenceSummary(
                        run_id=run_id,
                        symbol=symbol,
                        context_id=getattr(market_context, "context_id", f"ctx-{symbol}"),
                        evidence_records=[],
                        contradictions=[],
                    )

            # --- Phase 13 Integration ---
            bull_bear_result = self.bull_bear_engine.evaluate(market_context, evidence_summary)
            if hasattr(evidence_summary, "evidence_records"):
                evidence_summary.evidence_records.extend(bull_bear_result.active_evidence)
            elif hasattr(evidence_summary, "records"):
                evidence_summary.records.extend(bull_bear_result.active_evidence)
            run.stages["BULL_BEAR"] = PipelineStageResult(
                stage_name="BULL_BEAR",
                status=StageStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                details={"directional_state": bull_bear_result.directional_state.value, "risk_state": bull_bear_result.risk_state.value},
            )
            # ---------------------------

            ev_records = getattr(evidence_summary, "evidence_records", getattr(evidence_summary, "records", []))
            ev_contradictions = getattr(evidence_summary, "contradictions", [])
            run.evidence = evidence_summary.model_dump() if hasattr(evidence_summary, "model_dump") else {}
            run.stages["EVIDENCE"] = PipelineStageResult(
                stage_name="EVIDENCE",
                status=StageStatus.COMPLETED if ev_records else StageStatus.DEGRADED,
                started_at=now,
                completed_at=now,
                duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                details={"record_count": len(ev_records), "contradiction_count": len(ev_contradictions)},
            )

            # ── 4. Adversarial Debate Stage ───────────────────────────────────
            s_t0 = time.monotonic()
            if debate_result is None:
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            debate_result = pool.submit(
                                lambda: asyncio.run(self.debate_engine.run_debate(
                                    evidence_summary=evidence_summary,
                                    market_context=market_context,
                                ))
                            ).result()
                    else:
                        debate_result = loop.run_until_complete(
                            self.debate_engine.run_debate(
                                evidence_summary=evidence_summary,
                                market_context=market_context,
                            )
                        )
                except Exception:
                    debate_result = asyncio.run(
                        self.debate_engine.run_debate(
                            evidence_summary=evidence_summary,
                            market_context=market_context,
                        )
                    )

            run.debate = debate_result.model_dump() if hasattr(debate_result, "model_dump") else {}
            run.stages["DEBATE"] = PipelineStageResult(
                stage_name="DEBATE",
                status=StageStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                details={"decision_state": str(getattr(debate_result, "final_debate_state", getattr(debate_result, "decision_state", "UNKNOWN")))},
            )

            # ── 5. Investment Committee Synthesis Stage ───────────────────────
            s_t0 = time.monotonic()
            if committee_decision is None:
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Create an independent background task in current event loop if already running
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            committee_decision = pool.submit(
                                lambda: asyncio.run(self.committee.synthesize_decision(
                                    evidence_summary=evidence_summary,
                                    debate_result=debate_result,
                                    market_context=market_context,
                                ))
                            ).result()
                    else:
                        committee_decision = loop.run_until_complete(
                            self.committee.synthesize_decision(
                                evidence_summary=evidence_summary,
                                debate_result=debate_result,
                                market_context=market_context,
                            )
                        )
                except Exception:
                    committee_decision = asyncio.run(
                        self.committee.synthesize_decision(
                            evidence_summary=evidence_summary,
                            debate_result=debate_result,
                            market_context=market_context,
                        )
                    )

            run.committee_decision = committee_decision.model_dump() if hasattr(committee_decision, "model_dump") else {}
            recom = getattr(committee_decision, "recommendation", CommitteeRecommendation.HOLD)
            committee_status = StageStatus.COMPLETED if recom in (CommitteeRecommendation.BUY, CommitteeRecommendation.SELL) else StageStatus.REJECTED

            run.stages["INVESTMENT_COMMITTEE"] = PipelineStageResult(
                stage_name="INVESTMENT_COMMITTEE",
                status=committee_status,
                started_at=now,
                completed_at=now,
                duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                details={"recommendation": recom.value, "conviction_score": committee_decision.conviction_score},
            )

            # Safety Gate: If committee rejects or recommends HOLD, do not execute order
            if recom not in (CommitteeRecommendation.BUY, CommitteeRecommendation.SELL):
                run.final_status = StageStatus.REJECTED
                run.failed_stage = "INVESTMENT_COMMITTEE"
                run.failure_reason = f"Committee recommendation is {recom.value} — execution not warranted."
                self._mark_skipped_stages(run, ["PREFLIGHT", "PAPER_BROKER", "FILLS"])
                return self._finalize_run(run, start_mono)

            # ── 6. Conviction Calibration Stage ───────────────────────────────
            s_t0 = time.monotonic()
            calibration = self.conviction_calibrator.calibrate(
                committee_decision=committee_decision,
                debate_result=debate_result,
                evidence_summary=evidence_summary,
                market_context=market_context,
            )
            run.conviction = calibration.model_dump() if hasattr(calibration, "model_dump") else {}
            run.stages["CONVICTION"] = PipelineStageResult(
                stage_name="CONVICTION",
                status=StageStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                details={"calibrated_conviction": calibration.calibrated_conviction, "band": calibration.conviction_band.value},
            )

            # ── 7. Market Regime Detection Stage ──────────────────────────────
            s_t0 = time.monotonic()
            regime = self.regime_engine.evaluate_regime(market_context=market_context)
            run.regime = regime.model_dump() if hasattr(regime, "model_dump") else {}
            run.stages["MARKET_REGIME"] = PipelineStageResult(
                stage_name="MARKET_REGIME",
                status=StageStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                details={"overall_regime": regime.overall_regime.value},
            )

            # ── 8. Portfolio Intelligence Stage ───────────────────────────────
            s_t0 = time.monotonic()
            portfolio_intel = self.portfolio_engine.analyze_portfolio(
                portfolio_state=portfolio_state or {},
                candidate_context=market_context,
            )
            run.portfolio = portfolio_intel.model_dump() if hasattr(portfolio_intel, "model_dump") else {}
            run.stages["PORTFOLIO_INTELLIGENCE"] = PipelineStageResult(
                stage_name="PORTFOLIO_INTELLIGENCE",
                status=StageStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                details={"total_equity": getattr(portfolio_intel, "total_equity", 0.0)},
            )

            # ── 9. Scenario & Stress Testing Stage ────────────────────────────
            s_t0 = time.monotonic()
            stress_result = self.scenario_engine.run_scenario(
                candidate_context=market_context,
                portfolio_state=portfolio_state,
                market_regime=regime,
            )
            run.scenario = stress_result.model_dump() if hasattr(stress_result, "model_dump") else {}
            run.stages["SCENARIO_STRESS_TEST"] = PipelineStageResult(
                stage_name="SCENARIO_STRESS_TEST",
                status=StageStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                details={"resilience": stress_result.resilience.value},
            )

            # ── 10. Risk Management & Position Sizing Stage ───────────────────
            s_t0 = time.monotonic()
            sizing_plan: PositionSizingPlan = self.risk_engine.evaluate_and_size(
                committee_decision=committee_decision,
                market_context=market_context,
                portfolio_state=portfolio_state,
                calibration=calibration,
                portfolio_intelligence=portfolio_intel,
                market_regime=regime,
            )
            run.risk = {"veto_applied": sizing_plan.veto_applied, "veto_reasons": sizing_plan.veto_reasons}
            run.sizing = sizing_plan.model_dump() if hasattr(sizing_plan, "model_dump") else {}

            # Safety Gate: If Risk Engine applies a veto, halt execution immediately
            approved_qty = getattr(sizing_plan, "position_quantity", getattr(sizing_plan, "approved_quantity", 0))
            if sizing_plan.veto_applied or approved_qty <= 0:
                run.stages["RISK_SIZING"] = PipelineStageResult(
                    stage_name="RISK_SIZING",
                    status=StageStatus.REJECTED,
                    started_at=now,
                    completed_at=now,
                    duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                    details={"veto_reasons": sizing_plan.veto_reasons},
                )
                self.telemetry_engine.record_event(
                    event_type=ExecutionEventType.RISK_VETO,
                    execution_id=run_id,
                    symbol=symbol,
                    reason=f"Risk Veto: {', '.join(sizing_plan.veto_reasons)}",
                    severity=EventSeverity.CRITICAL,
                    timestamp=now,
                )
                run.final_status = StageStatus.REJECTED
                run.failed_stage = "RISK_SIZING"
                run.failure_reason = f"Risk Engine Veto Applied: {'; '.join(sizing_plan.veto_reasons)}"
                self._mark_skipped_stages(run, ["PREFLIGHT", "PAPER_BROKER", "FILLS"])
                return self._finalize_run(run, start_mono)

            run.stages["RISK_SIZING"] = PipelineStageResult(
                stage_name="RISK_SIZING",
                status=StageStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                details={"approved_quantity": approved_qty, "stop_price": sizing_plan.stop_loss_price},
            )

            if not allow_execution:
                run.final_status = StageStatus.COMPLETED
                self._mark_skipped_stages(run, ["PREFLIGHT", "PAPER_BROKER", "FILLS"])
                return self._finalize_run(run, start_mono)

            # ── 11. Execution Pre-Flight Gatekeeper Stage ─────────────────────
            s_t0 = time.monotonic()
            order_side = PreflightSide.BUY if sizing_plan.direction == PositionDirection.LONG else PreflightSide.SELL
            limit_price = sizing_plan.entry_price or getattr(market_context, "current_price", 1000.0)

            preflight_req = PreflightOrderRequest(
                decision_id=committee_decision.decision_id,
                symbol=symbol,
                side=order_side,
                order_type=PreflightOrderType.LIMIT,
                quantity=float(approved_qty),
                limit_price=limit_price,
                stop_price=sizing_plan.stop_loss_price,
                target_price=sizing_plan.take_profit_price,
                portfolio_id="PORT-DEFAULT",
                conviction=getattr(calibration, "calibrated_conviction", 0.8),
                timestamp=now,
            )

            if self.preflight_engine is None:
                failed_msg = "Pre-flight engine is not initialized or unavailable (None)"
                run.stages["PREFLIGHT"] = PipelineStageResult(
                    stage_name="PREFLIGHT",
                    status=StageStatus.FAILED,
                    started_at=now,
                    completed_at=now,
                    duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                    details={"status": "ENGINE_UNAVAILABLE", "reason": failed_msg},
                    error_message=failed_msg,
                )
                self.telemetry_engine.record_event(
                    event_type=ExecutionEventType.PREFLIGHT_REJECTED,
                    execution_id=run_id,
                    symbol=symbol,
                    reason=f"Pre-Flight Failed: {failed_msg}",
                    severity=EventSeverity.CRITICAL,
                    timestamp=now,
                )
                run.final_status = StageStatus.FAILED
                run.failed_stage = "UNHANDLED_EXCEPTION"
                run.failure_reason = failed_msg
                logger.warning(f"[TradingOSOrchestrator] Pre-flight failed: {failed_msg}")
                return self._finalize_run(run, start_mono)

            preflight_res: ExecutionPreflightResult = self.preflight_engine.evaluate_preflight(
                order_request=preflight_req,
                candidate_plan=sizing_plan,
                market_context=market_context,
                portfolio_state=portfolio_state or {"cash": self.paper_broker.account.cash, "total_equity": self.paper_broker.account.total_equity},
                evaluation_timestamp=now,
            )

            run.preflight = preflight_res.model_dump() if hasattr(preflight_res, "model_dump") else {}

            # Safety Gate: Pre-Flight Rejection
            if preflight_res.status != PreflightStatus.APPROVED or not preflight_res.authorization:
                failed_msg = "; ".join(preflight_res.failed_checks) if preflight_res.failed_checks else preflight_res.status.value
                run.stages["PREFLIGHT"] = PipelineStageResult(
                    stage_name="PREFLIGHT",
                    status=StageStatus.REJECTED,
                    started_at=now,
                    completed_at=now,
                    duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                    details={"status": preflight_res.status.value, "reason": failed_msg},
                )
                self.telemetry_engine.record_event(
                    event_type=ExecutionEventType.PREFLIGHT_REJECTED,
                    execution_id=run_id,
                    symbol=symbol,
                    reason=f"Pre-Flight Rejected: {failed_msg}",
                    severity=EventSeverity.ERROR,
                    timestamp=now,
                )
                run.final_status = StageStatus.REJECTED
                run.failed_stage = "PREFLIGHT"
                run.failure_reason = f"Pre-Flight Rejection: {failed_msg}"
                self._mark_skipped_stages(run, ["PAPER_BROKER", "FILLS"])
                return self._finalize_run(run, start_mono)

            run.stages["PREFLIGHT"] = PipelineStageResult(
                stage_name="PREFLIGHT",
                status=StageStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                details={"authorization_id": preflight_res.authorization.authorization_id},
            )

            # ── 12. Paper Broker Intake Stage ─────────────────────────────────
            s_t0 = time.monotonic()
            broker_res: PaperExecutionResult = self.paper_broker.submit_order(
                authorization=preflight_res.authorization,
                market_context=market_context,
                evaluation_timestamp=now,
            )
            run.paper_order = broker_res.order.model_dump() if hasattr(broker_res.order, "model_dump") else {}

            if broker_res.status == PaperOrderStatus.REJECTED:
                run.stages["PAPER_BROKER"] = PipelineStageResult(
                    stage_name="PAPER_BROKER",
                    status=StageStatus.REJECTED,
                    started_at=now,
                    completed_at=now,
                    duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                    details={"reason": broker_res.message},
                )
                run.final_status = StageStatus.REJECTED
                run.failed_stage = "PAPER_BROKER"
                run.failure_reason = f"Paper Broker Submission Rejected: {broker_res.message}"
                self._mark_skipped_stages(run, ["FILLS"])
                return self._finalize_run(run, start_mono)

            run.stages["PAPER_BROKER"] = PipelineStageResult(
                stage_name="PAPER_BROKER",
                status=StageStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                details={"order_id": broker_res.order.order_id, "status": broker_res.status.value},
            )

            # ── 13. Simulated Fill Execution Stage ────────────────────────────
            s_t0 = time.monotonic()
            fill_price = limit_price
            fill_res = self.paper_broker.process_fills(
                order_id=broker_res.order.order_id,
                market_price=fill_price,
                fill_ratio=fill_ratio,
                evaluation_timestamp=now,
            )

            run.fills = [f.model_dump() for f in fill_res.order.fills]
            run.paper_order = fill_res.order.model_dump()
            fill_stage_status = StageStatus.COMPLETED if fill_res.order.status == PaperOrderStatus.FILLED else StageStatus.DEGRADED

            run.stages["FILLS"] = PipelineStageResult(
                stage_name="FILLS",
                status=fill_stage_status,
                started_at=now,
                completed_at=now,
                duration_ms=round((time.monotonic() - s_t0) * 1000.0, 2),
                details={
                    "status": fill_res.order.status.value,
                    "filled_quantity": fill_res.order.filled_quantity,
                    "avg_fill_price": fill_res.order.average_fill_price,
                },
            )

            # ── 14. Telemetry & Run Completion ────────────────────────────────
            run.telemetry_summary = {
                "total_events": len(self.telemetry_engine._events),
                "last_order_status": fill_res.order.status.value,
            }
            run.final_status = StageStatus.COMPLETED

            # Telemetry: Record run completion
            self.telemetry_engine.record_event(
                event_type=ExecutionEventType.ORDER_FILLED if fill_res.order.status == PaperOrderStatus.FILLED else ExecutionEventType.ORDER_PARTIALLY_FILLED,
                execution_id=run_id,
                order_id=broker_res.order.order_id,
                symbol=symbol,
                quantity=fill_res.order.filled_quantity,
                price=fill_res.order.average_fill_price,
                reason="End-to-End Trading OS run executed successfully",
                timestamp=now,
            )

            return self._finalize_run(run, start_mono)

        except Exception as e:
            logger.exception(f"[TradingOSOrchestrator] Unhandled pipeline failure: {e}")
            run.final_status = StageStatus.FAILED
            run.failed_stage = "UNHANDLED_EXCEPTION"
            run.failure_reason = str(e)
            self.telemetry_engine.record_event(
                event_type=ExecutionEventType.EXECUTION_ERROR,
                execution_id=run_id,
                symbol=symbol,
                reason=f"Pipeline exception: {str(e)}",
                severity=EventSeverity.CRITICAL,
                timestamp=now,
            )
            return self._finalize_run(run, start_mono)

    # ── Helper Utilities ──────────────────────────────────────────────────────

    def get_summary(self, run: TradingOSRun) -> TradingOSRunSummary:
        """Derive concise machine-readable operational summary from a completed run."""
        decision = "UNKNOWN"
        if run.committee_decision:
            decision = run.committee_decision.get("recommendation", "UNKNOWN")

        conviction = 0.0
        if run.conviction:
            conviction = run.conviction.get("calibrated_conviction", 0.0)

        regime_str = "UNKNOWN"
        if run.regime:
            regime_str = run.regime.get("overall_regime", "UNKNOWN")

        risk_status = "SAFE"
        if run.risk:
            if run.risk.get("veto_applied", False):
                risk_status = "VETOED"

        approved_size = 0
        if run.sizing:
            approved_size = run.sizing.get("position_quantity", run.sizing.get("approved_quantity", 0))

        preflight_status = "NOT_EVALUATED"
        if run.preflight:
            preflight_status = run.preflight.get("status", "NOT_EVALUATED")

        order_status = "NONE"
        if run.paper_order:
            order_status = run.paper_order.get("status", "NONE")

        fill_status = "UNFILLED"
        if run.paper_order:
            fill_status = f"{run.paper_order.get('filled_quantity', 0)}/{run.paper_order.get('requested_quantity', 0)}"

        # Position and P&L from authoritative paper broker account
        pos = self.paper_broker.account.positions.get(run.symbol)
        final_pos = pos.quantity if pos else 0
        pnl = pos.unrealized_pnl + pos.realized_pnl if pos else 0.0

        failures = [run.failure_reason] if run.failure_reason else []

        return TradingOSRunSummary(
            run_id=run.run_id,
            symbol=run.symbol,
            decision=decision,
            conviction=conviction,
            regime=regime_str,
            risk_status=risk_status,
            approved_size=approved_size,
            preflight_status=preflight_status,
            paper_order_status=order_status,
            fill_status=fill_status,
            final_position=final_pos,
            pnl=round(pnl, 2),
            failures=failures,
            duration_ms=run.total_duration_ms,
            mode="PAPER_ONLY",
        )

    def _mark_skipped_stages(self, run: TradingOSRun, stage_names: List[str]) -> None:
        """Mark subsequent downstream stages as SKIPPED after safety gate halt."""
        now = datetime.now(timezone.utc)
        for name in stage_names:
            run.stages[name] = PipelineStageResult(
                stage_name=name,
                status=StageStatus.SKIPPED,
                started_at=now,
                completed_at=now,
                duration_ms=0.0,
                details={"reason": "Safety gate triggered upstream"},
            )

    def _finalize_run(self, run: TradingOSRun, start_mono: float) -> TradingOSRun:
        """Finalize timestamps and total elapsed duration."""
        run.completed_at = datetime.now(timezone.utc)
        run.total_duration_ms = round((time.monotonic() - start_mono) * 1000.0, 2)

        # Downstream read-only monitoring hook (failsafe: never aborts pipeline)
        try:
            from backend.application.system_health_monitor import global_health_monitor
            global_health_monitor.record_pipeline_run(run)
        except Exception as mon_ex:
            logger.warning(f"[TradingOSOrchestrator] Health monitor hook failed: {mon_ex}")

        return run


# Global singleton instance for application-level routing & execution
global_orchestrator = TradingOSOrchestrator()

