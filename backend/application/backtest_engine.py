"""
Phase 6.8 — Historical Backtesting & Decision Validation Engine

Production-grade deterministic historical backtesting service for Trading OS.
Evaluates historical trading setups strictly under Point-In-Time (PIT) boundaries
with zero look-ahead bias, measuring forward outcomes deterministically.
"""

from datetime import datetime, timezone
import math
import statistics
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from backend.domain.schemas import MarketContext
from backend.domain.risk_schemas import (
    PositionDirection,
    PositionSizingPlan,
    RiskConfiguration,
)
from backend.domain.regime_schemas import (
    OverallMarketRegime,
    MarketRegime,
)
from backend.domain.portfolio_schemas import (
    PortfolioIntelligence,
)
from backend.domain.scenario_schemas import (
    ScenarioResult,
    ScenarioSeverity,
)
from backend.domain.investment_committee_schemas import (
    CommitteeDecision,
    CommitteeRecommendation,
)
from backend.domain.backtest_schemas import (
    BACKTEST_ENGINE_VERSION,
    BacktestMode,
    EntryExecutionRule,
    OutcomeStatus,
    BacktestDataQuality,
    BacktestConfig,
    ForwardOutcome,
    HistoricalDecisionSnapshot,
    SingleDecisionBacktestResult,
    AggregatePerformanceReport,
    RiskVetoAnalysis,
    BatchBacktestResult,
)
from backend.simulation.pit_filter import PointInTimeFilter, _normalize_dt, _parse_timestamp
from backend.application.risk_engine import RiskEngine
from backend.application.scenario_engine import ScenarioEngine
from backend.application.market_regime_engine import MarketRegimeEngine
from backend.application.portfolio_intelligence_engine import PortfolioIntelligenceEngine
from backend.application.conviction_calibrator import ConvictionCalibrator


class BacktestEngine:
    """
    Deterministic Historical Backtesting & Decision Validation service.
    Guarantees strict Point-In-Time (PIT) execution without future leakage.
    Zero LLM numerical calculations.
    """

    def __init__(
        self,
        risk_engine: Optional[RiskEngine] = None,
        scenario_engine: Optional[ScenarioEngine] = None,
        regime_engine: Optional[MarketRegimeEngine] = None,
        portfolio_engine: Optional[PortfolioIntelligenceEngine] = None,
        calibrator: Optional[ConvictionCalibrator] = None,
    ):
        self.risk_engine = risk_engine or RiskEngine()
        self.scenario_engine = scenario_engine or ScenarioEngine(default_risk_engine=self.risk_engine)
        self.regime_engine = regime_engine or MarketRegimeEngine()
        self.portfolio_engine = portfolio_engine or PortfolioIntelligenceEngine()
        self.calibrator = calibrator or ConvictionCalibrator()

    # ── Single Decision Backtest ──────────────────────────────────────────────

    def run_single_backtest(
        self,
        raw_context: MarketContext,
        as_of: datetime,
        portfolio_state: Optional[Any] = None,
        config: Optional[BacktestConfig] = None,
        committee_decision: Optional[CommitteeDecision] = None,
        candidate_plan: Optional[PositionSizingPlan] = None,
        market_regime: Optional[MarketRegime] = None,
        scenario_result: Optional[ScenarioResult] = None,
    ) -> SingleDecisionBacktestResult:
        """
        Evaluate a single historical decision at timestamp `as_of` strictly using
        information available at or before `as_of`, then measure forward outcomes.
        """
        cfg = config or BacktestConfig()
        norm_as_of = _normalize_dt(as_of)
        warnings: List[str] = []
        provenance: List[Dict[str, Any]] = []

        # ── 1. Apply Strict Point-In-Time (PIT) Boundary ───────────────────────
        pit_ctx = PointInTimeFilter.filter_market_context(raw_context, as_of)

        if not pit_ctx.ohlcv_historical:
            warnings.append("INSUFFICIENT_HISTORY: No historical OHLCV available at or before evaluation timestamp.")
            dq = BacktestDataQuality.UNAVAILABLE
        else:
            dq = BacktestDataQuality.FRESH

        # ── 2. Derive / Sizing Pipeline at T ───────────────────────────────────
        # Use provided models or evaluate deterministically on PIT state
        regime = market_regime
        if regime is None:
            try:
                regime = self.regime_engine.evaluate_regime(pit_ctx)
            except Exception:
                regime = None

        decision = committee_decision
        if decision is None:
            # Construct standard baseline committee decision at T
            decision = CommitteeDecision(
                decision_id=f"hist-dec-{uuid.uuid4().hex[:8]}",
                context_id=pit_ctx.context_id,
                symbol=pit_ctx.symbol,
                recommendation=CommitteeRecommendation.BUY,
                conviction_score=0.75,
                risk_score=0.25,
                risk_veto_applied=False,
            )

        plan = candidate_plan
        if plan is None:
            plan = self.risk_engine.evaluate_and_size(
                committee_decision=decision,
                market_context=pit_ctx,
                portfolio_state=portfolio_state,
                market_regime=regime,
            )

        scenario_res = scenario_result
        if scenario_res is None:
            try:
                scenario_res = self.scenario_engine.run_scenario(
                    candidate_context=pit_ctx,
                    candidate_plan=plan,
                    portfolio_state=portfolio_state,
                    market_regime=regime,
                )
            except Exception:
                scenario_res = None

        provenance.append({
            "source": "BacktestEngine",
            "version": BACKTEST_ENGINE_VERSION,
            "as_of": str(as_of),
            "symbol": raw_context.symbol,
            "entry_rule": cfg.entry_rule.value,
            "holding_period_bars": cfg.holding_period_bars,
        })

        # ── 3. Freeze Historical Decision Snapshot at T ────────────────────────
        snapshot = self._create_decision_snapshot(
            pit_ctx=pit_ctx,
            as_of=as_of,
            decision=decision,
            plan=plan,
            regime=regime,
            portfolio_state=portfolio_state,
            scenario_res=scenario_res,
            data_quality=dq,
            provenance=list(provenance),
        )

        # ── 4. Measure Post-Decision Forward Outcomes (Strictly > as_of) ───────
        future_bars = self._extract_future_bars(raw_context.ohlcv_historical, as_of)

        forward_outcomes: Dict[int, ForwardOutcome] = {}
        for horizon in cfg.forward_horizons:
            outcome = self.measure_forward_outcome(
                future_bars=future_bars,
                horizon_bars=horizon,
                candidate_plan=plan,
                as_of=as_of,
                config=cfg,
            )
            forward_outcomes[horizon] = outcome

        # Primary outcome corresponding to holding period
        primary_horizon = cfg.holding_period_bars
        if primary_horizon in forward_outcomes:
            primary_outcome = forward_outcomes[primary_horizon]
        elif forward_outcomes:
            primary_outcome = list(forward_outcomes.values())[0]
        else:
            primary_outcome = self._create_empty_outcome(as_of, primary_horizon, plan.entry_price)

        # ── 5. Scenario vs Actual Outcome Comparison ───────────────────────────
        scenario_vs_actual = self._compare_scenario_vs_actual(scenario_res, primary_outcome)

        # ── 6. Decision Quality Scoring ────────────────────────────────────────
        dq_score = self._compute_decision_quality_score(
            plan=plan,
            primary_outcome=primary_outcome,
            scenario_res=scenario_res,
        )

        provenance.append({
            "source": "BacktestEngine",
            "version": BACKTEST_ENGINE_VERSION,
            "as_of": str(as_of),
            "symbol": raw_context.symbol,
            "entry_rule": cfg.entry_rule.value,
            "holding_period_bars": cfg.holding_period_bars,
            "forward_bars_available": len(future_bars),
        })

        return SingleDecisionBacktestResult(
            decision_snapshot=snapshot,
            forward_outcomes=forward_outcomes,
            primary_outcome=primary_outcome,
            decision_quality_score=dq_score,
            scenario_vs_actual=scenario_vs_actual,
            warnings=warnings,
            data_quality=dq,
        )

    # ── Batch Historical Backtest ─────────────────────────────────────────────

    def run_batch_backtest(
        self,
        evaluations: List[Tuple[MarketContext, datetime]],
        portfolio_state: Optional[Any] = None,
        config: Optional[BacktestConfig] = None,
    ) -> BatchBacktestResult:
        """
        Execute a batch of historical backtests across multiple timestamps/symbols
        and aggregate performance statistics deterministically.
        """
        cfg = config or BacktestConfig(mode=BacktestMode.BATCH)
        results: List[SingleDecisionBacktestResult] = []

        for raw_ctx, as_of in evaluations:
            res = self.run_single_backtest(
                raw_context=raw_ctx,
                as_of=as_of,
                portfolio_state=portfolio_state,
                config=cfg,
            )
            results.append(res)

        perf_report = self._generate_aggregate_performance_report(results, cfg)
        veto_analysis = self._generate_risk_veto_analysis(results)

        return BatchBacktestResult(
            config=cfg,
            results=results,
            performance_report=perf_report,
            risk_veto_analysis=veto_analysis,
            generated_at=datetime.now(timezone.utc),
        )

    # ── Forward Outcome Measurement ───────────────────────────────────────────

    def measure_forward_outcome(
        self,
        future_bars: List[Dict[str, Any]],
        horizon_bars: int,
        candidate_plan: PositionSizingPlan,
        as_of: datetime,
        config: BacktestConfig,
    ) -> ForwardOutcome:
        """
        Deterministically calculate forward return, MFE, MAE, drawdown, stop-loss trigger,
        and transaction-cost-adjusted net P&L over the forward horizon.
        """
        direction = getattr(candidate_plan, "direction", PositionDirection.LONG)
        base_price = candidate_plan.entry_price or 1.0
        qty = candidate_plan.position_quantity if not candidate_plan.veto_applied else 0
        stop_loss = getattr(candidate_plan, "stop_loss_price", None)
        target_price = getattr(candidate_plan, "take_profit_price", getattr(candidate_plan, "target_price", None))

        if not future_bars:
            return self._create_empty_outcome(as_of, horizon_bars, base_price)

        # 1. Determine Entry Price
        if config.entry_rule == EntryExecutionRule.NEXT_OPEN and len(future_bars) > 0:
            first_bar = future_bars[0]
            entry_p = float(first_bar.get("open") or first_bar.get("close") or base_price)
            entry_ts = _parse_timestamp(first_bar.get("timestamp") or first_bar.get("date")) or as_of
            eval_bars = future_bars[:horizon_bars]
        else:
            entry_p = base_price
            entry_ts = as_of
            eval_bars = future_bars[:horizon_bars]

        exit_p = entry_p
        exit_ts = entry_ts
        stop_hit = False
        gap_through = False
        target_hit = False

        highest_p = entry_p
        lowest_p = entry_p

        # 2. Iterate Forward Price Path
        for bar in eval_bars:
            b_high = float(bar.get("high", bar.get("close", entry_p)))
            b_low = float(bar.get("low", bar.get("close", entry_p)))
            b_open = float(bar.get("open", bar.get("close", entry_p)))
            b_close = float(bar.get("close", entry_p))
            b_ts = _parse_timestamp(bar.get("timestamp") or bar.get("date")) or exit_ts

            highest_p = max(highest_p, b_high)
            lowest_p = min(lowest_p, b_low)

            # Check Stop Loss
            if stop_loss and stop_loss > 0:
                if direction == PositionDirection.LONG:
                    if b_low <= stop_loss:
                        stop_hit = True
                        # Check gap down
                        if b_open < stop_loss:
                            gap_through = True
                            exit_p = b_open
                        else:
                            exit_p = stop_loss
                        exit_ts = b_ts
                        break
                else:
                    if b_high >= stop_loss:
                        stop_hit = True
                        if b_open > stop_loss:
                            gap_through = True
                            exit_p = b_open
                        else:
                            exit_p = stop_loss
                        exit_ts = b_ts
                        break

            # Check Target
            if target_price and target_price > 0:
                if direction == PositionDirection.LONG:
                    if b_high >= target_price:
                        target_hit = True
                        exit_p = target_price
                        exit_ts = b_ts
                        break
                else:
                    if b_low <= target_price:
                        target_hit = True
                        exit_p = target_price
                        exit_ts = b_ts
                        break

            # Default exit is latest evaluated close
            exit_p = b_close
            exit_ts = b_ts

        # 3. Calculate Returns, Excursions, and Drawdown
        if direction == PositionDirection.LONG:
            fwd_ret = ((exit_p - entry_p) / entry_p) * 100.0 if entry_p > 0 else 0.0
            mfe = ((highest_p - entry_p) / entry_p) * 100.0 if entry_p > 0 else 0.0
            mae = ((lowest_p - entry_p) / entry_p) * 100.0 if entry_p > 0 else 0.0
            dd = max(0.0, ((entry_p - lowest_p) / entry_p) * 100.0) if entry_p > 0 else 0.0
        else:
            fwd_ret = ((entry_p - exit_p) / entry_p) * 100.0 if entry_p > 0 else 0.0
            mfe = ((entry_p - lowest_p) / entry_p) * 100.0 if entry_p > 0 else 0.0
            mae = ((entry_p - highest_p) / entry_p) * 100.0 if entry_p > 0 else 0.0
            dd = max(0.0, ((highest_p - entry_p) / entry_p) * 100.0) if entry_p > 0 else 0.0

        # 4. Financial Realization & Transaction Costs
        notional = round(qty * entry_p, 2)
        if direction == PositionDirection.LONG:
            gross_pnl = round(qty * (exit_p - entry_p), 2)
        else:
            gross_pnl = round(qty * (entry_p - exit_p), 2)

        total_cost = 0.0
        if config.enable_costs and notional > 0:
            total_friction_pct = config.brokerage_pct + config.slippage_pct + config.stt_tax_pct
            total_cost = round(notional * total_friction_pct, 2)

        net_pnl = round(gross_pnl - total_cost, 2)
        net_ret = round((net_pnl / notional) * 100.0, 4) if notional > 0 else 0.0

        # 5. Outcome Status
        if candidate_plan.veto_applied:
            status = OutcomeStatus.VETOED
        elif stop_hit:
            status = OutcomeStatus.STOPPED_OUT
        elif target_hit:
            status = OutcomeStatus.TARGET_HIT
        elif abs(fwd_ret) < 0.20:
            status = OutcomeStatus.SCRATCH
        elif fwd_ret > 0.0:
            status = OutcomeStatus.WIN
        else:
            status = OutcomeStatus.LOSS

        return ForwardOutcome(
            horizon_bars=horizon_bars,
            entry_timestamp=entry_ts,
            exit_timestamp=exit_ts,
            entry_price=round(entry_p, 2),
            exit_price=round(exit_p, 2),
            forward_return_pct=round(fwd_ret, 2),
            mfe_pct=round(mfe, 2),
            mae_pct=round(mae, 2),
            drawdown_pct=round(dd, 2),
            stop_loss_hit=stop_hit,
            gap_through_stop=gap_through,
            target_hit=target_hit,
            gross_pnl=gross_pnl,
            total_cost=total_cost,
            net_pnl=net_pnl,
            net_return_pct=net_ret,
            outcome_status=status,
        )

    # ── Private Calculation Helpers ───────────────────────────────────────────

    def _extract_future_bars(
        self,
        ohlcv_bars: List[Dict[str, Any]],
        as_of: datetime,
    ) -> List[Dict[str, Any]]:
        """Extract bars strictly after the evaluation timestamp `as_of`."""
        norm_as_of = _normalize_dt(as_of)
        future = []
        for bar in ohlcv_bars:
            ts_val = bar.get("timestamp") or bar.get("date") or bar.get("datetime")
            bar_time = _parse_timestamp(ts_val)
            if bar_time and norm_as_of and bar_time > norm_as_of:
                future.append(bar)
        return future

    def _create_decision_snapshot(
        self,
        pit_ctx: MarketContext,
        as_of: datetime,
        decision: CommitteeDecision,
        plan: PositionSizingPlan,
        regime: Optional[MarketRegime],
        portfolio_state: Optional[Any],
        scenario_res: Optional[ScenarioResult],
        data_quality: BacktestDataQuality,
        provenance: List[Dict[str, Any]],
    ) -> HistoricalDecisionSnapshot:
        """Freeze decision-time context at timestamp T."""
        return HistoricalDecisionSnapshot(
            decision_id=decision.decision_id,
            evaluation_timestamp=as_of,
            symbol=pit_ctx.symbol,
            market_context_summary={
                "current_price": pit_ctx.current_price,
                "history_length": len(pit_ctx.ohlcv_historical),
                "indicators_count": len(pit_ctx.technical_indicators),
            },
            committee_snapshot={
                "recommendation": decision.recommendation.value,
                "conviction_score": decision.conviction_score,
                "risk_score": decision.risk_score,
                "veto_applied": decision.risk_veto_applied,
            },
            sizing_snapshot={
                "quantity": plan.position_quantity,
                "notional": plan.position_notional,
                "exposure_pct": plan.exposure_pct,
                "stop_loss": plan.stop_loss_price,
            },
            regime_snapshot={
                "overall_regime": regime.overall_regime.value if regime else "UNKNOWN",
                "alignment": regime.stock_alignment.value if regime else "UNKNOWN",
            },
            scenario_snapshot={
                "stress_score": scenario_res.stress_score if scenario_res else None,
                "severity": scenario_res.severity.value if scenario_res else None,
                "resilience": scenario_res.resilience.value if scenario_res else None,
            },
            data_quality=data_quality,
            provenance=provenance,
        )

    def _compare_scenario_vs_actual(
        self,
        scenario_res: Optional[ScenarioResult],
        outcome: ForwardOutcome,
    ) -> Dict[str, Any]:
        """Compare scenario stress expectation against realized outcome without leakage."""
        if not scenario_res:
            return {"status": "UNAVAILABLE", "note": "No scenario test attached."}

        stress_score = scenario_res.stress_score
        actual_mae = abs(min(0.0, outcome.mae_pct))

        # Check if actual adverse excursion exceeded scenario expectation
        stress_expectation_exceeded = actual_mae > (stress_score * 25.0)

        return {
            "scenario_severity": scenario_res.severity.value,
            "scenario_resilience": scenario_res.resilience.value,
            "stress_score": stress_score,
            "actual_drawdown_pct": outcome.drawdown_pct,
            "actual_mae_pct": outcome.mae_pct,
            "stress_expectation_exceeded": stress_expectation_exceeded,
            "stop_loss_triggered_actual": outcome.stop_loss_hit,
        }

    def _compute_decision_quality_score(
        self,
        plan: PositionSizingPlan,
        primary_outcome: ForwardOutcome,
        scenario_res: Optional[ScenarioResult],
    ) -> float:
        """Deterministic evaluation of decision quality vs outcome."""
        score = 0.50

        # Veto evaluation: Did a veto correctly prevent a loss?
        if plan.veto_applied:
            if primary_outcome.forward_return_pct < 0.0:
                # Correct risk veto: saved capital
                score += 0.40
            else:
                # Conservative risk veto: missed gain, but preserved risk discipline
                score += 0.10
            return round(min(1.0, score), 4)

        # Non-vetoed trade evaluation
        if primary_outcome.forward_return_pct > 0.0:
            score += 0.25
        else:
            # Losing trade, check if stop loss respected
            if primary_outcome.stop_loss_hit and not primary_outcome.gap_through_stop:
                score += 0.10  # Controlled risk execution

        if scenario_res and scenario_res.resilience.value in ("STRONG", "MODERATE"):
            score += 0.15

        return round(max(0.0, min(1.0, score)), 4)

    def _create_empty_outcome(self, as_of: datetime, horizon: int, price: float) -> ForwardOutcome:
        """Fallback empty outcome when future bars are unavailable."""
        return ForwardOutcome(
            horizon_bars=horizon,
            entry_timestamp=as_of,
            exit_timestamp=as_of,
            entry_price=round(price, 2),
            exit_price=round(price, 2),
            forward_return_pct=0.0,
            outcome_status=OutcomeStatus.ACTIVE,
        )

    def _generate_aggregate_performance_report(
        self,
        results: List[SingleDecisionBacktestResult],
        config: BacktestConfig,
    ) -> AggregatePerformanceReport:
        """Generate statistical performance metrics across batch runs."""
        total = len(results)
        if total == 0:
            return AggregatePerformanceReport(insufficient_sample=True, sample_notes="Zero decisions provided.")

        accepted = sum(1 for r in results if not r.decision_snapshot.sizing_snapshot.get("veto_applied", False) and r.primary_outcome.outcome_status != OutcomeStatus.VETOED)
        vetoed = total - accepted

        wins = sum(1 for r in results if r.primary_outcome.outcome_status in (OutcomeStatus.WIN, OutcomeStatus.TARGET_HIT))
        losses = sum(1 for r in results if r.primary_outcome.outcome_status in (OutcomeStatus.LOSS, OutcomeStatus.STOPPED_OUT))
        scratches = sum(1 for r in results if r.primary_outcome.outcome_status == OutcomeStatus.SCRATCH)

        if accepted < config.min_sample_size:
            return AggregatePerformanceReport(
                total_decisions=total,
                accepted_decisions=accepted,
                vetoed_decisions=vetoed,
                wins=wins,
                losses=losses,
                scratches=scratches,
                insufficient_sample=True,
                sample_notes=f"Accepted trades ({accepted}) below minimum threshold ({config.min_sample_size}); skipping statistical aggregation.",
            )

        returns = [r.primary_outcome.net_return_pct for r in results if r.primary_outcome.outcome_status != OutcomeStatus.VETOED]
        win_returns = [r for r in returns if r > 0.0]
        loss_returns = [r for r in returns if r < 0.0]

        win_rate = round((wins / (wins + losses) * 100.0), 2) if (wins + losses) > 0 else 0.0
        avg_ret = round(statistics.mean(returns), 2) if returns else 0.0
        med_ret = round(statistics.median(returns), 2) if returns else 0.0
        avg_win = round(statistics.mean(win_returns), 2) if win_returns else 0.0
        avg_loss = round(statistics.mean(loss_returns), 2) if loss_returns else 0.0

        gross_gains = sum(win_returns)
        gross_losses = abs(sum(loss_returns))
        profit_factor = round(gross_gains / gross_losses, 2) if gross_losses > 0 else None

        drawdowns = [r.primary_outcome.drawdown_pct for r in results if r.primary_outcome.outcome_status != OutcomeStatus.VETOED]
        max_dd = round(max(drawdowns), 2) if drawdowns else 0.0

        # Expectancy = (Win% * AvgWin) - (Loss% * AvgLoss)
        win_prob = wins / max(1, (wins + losses))
        loss_prob = losses / max(1, (wins + losses))
        expectancy = round((win_prob * avg_win) - (loss_prob * abs(avg_loss)), 2)

        # Sharpe ratio approximation
        sharpe = None
        if len(returns) >= 3:
            std_dev = statistics.stdev(returns)
            if std_dev > 0:
                sharpe = round((avg_ret / std_dev) * math.sqrt(252 / config.holding_period_bars), 2)

        return AggregatePerformanceReport(
            total_decisions=total,
            accepted_decisions=accepted,
            vetoed_decisions=vetoed,
            wins=wins,
            losses=losses,
            scratches=scratches,
            win_rate_pct=win_rate,
            avg_return_pct=avg_ret,
            median_return_pct=med_ret,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            max_drawdown_pct=max_dd,
            profit_factor=profit_factor,
            expectancy=expectancy,
            sharpe_ratio=sharpe,
            insufficient_sample=False,
        )

    def _generate_risk_veto_analysis(
        self,
        results: List[SingleDecisionBacktestResult],
    ) -> RiskVetoAnalysis:
        """Audit performance of vetoed candidates."""
        vetoed = [r for r in results if r.primary_outcome.outcome_status == OutcomeStatus.VETOED]
        total_v = len(vetoed)

        reasons: Dict[str, int] = {}
        prevented_losses = 0
        missed_gains = 0
        returns: List[float] = []

        for r in vetoed:
            fwd = r.primary_outcome.forward_return_pct
            returns.append(fwd)
            if fwd < 0.0:
                prevented_losses += 1
            elif fwd > 0.0:
                missed_gains += 1

        avg_ret = round(statistics.mean(returns), 2) if returns else None
        summary = (
            f"Analyzed {total_v} risk vetoes: {prevented_losses} prevented capital loss, "
            f"{missed_gains} bypassed potential gains."
        ) if total_v > 0 else "Zero risk vetoes encountered."

        return RiskVetoAnalysis(
            total_vetoes=total_v,
            veto_reasons_distribution=reasons,
            vetoed_fwd_return_avg=avg_ret,
            prevented_loss_count=prevented_losses,
            missed_gain_count=missed_gains,
            summary=summary,
        )
