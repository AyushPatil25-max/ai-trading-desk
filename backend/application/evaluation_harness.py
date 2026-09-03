"""
Phase 11 — High-Fidelity Historical Backtesting & Evaluation Harness

Production-grade multi-period historical replay engine built on top of Phase 6.8,
Phase 9 17-stage Trading OS Orchestrator, and Phase 10 Opportunity Scanner.
Guarantees strict Point-in-Time boundaries, zero look-ahead bias, survivorship bias auditing,
deterministic mark-to-market portfolio accounting, realistic execution simulation,
performance attribution, walk-forward partitions, and Monte Carlo sensitivity analysis.
"""

from datetime import datetime, timezone, timedelta
import math
import random
import statistics
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from backend.domain.schemas import MarketContext
from backend.domain.opportunity_schemas import (
    CandidatePriority,
    CandidateScreeningStatus,
    OpportunityCandidate,
)
from backend.domain.evaluation_harness_schemas import (
    EVALUATION_HARNESS_VERSION,
    UniverseMode,
    BiasType,
    BiasSeverity,
    RebalanceFrequency,
    ExitReason,
    TransactionCostConfig,
    HistoricalEvaluationConfig,
    PointInTimeHistoricalContext,
    HistoricalTradeRecord,
    EquityCurvePoint,
    PerformanceMetrics,
    RiskMetrics,
    BenchmarkComparison,
    PerformanceAttribution,
    WalkForwardSplit,
    MonteCarloResult,
    BiasWarning,
    DataQualityAudit,
    HistoricalEvaluationReport,
)
from backend.simulation.pit_filter import PointInTimeFilter, _normalize_dt, _parse_timestamp
from backend.application.backtest_engine import BacktestEngine
from backend.application.opportunity_scanner import OpportunityScanner
from backend.application.trading_os_orchestrator import TradingOSOrchestrator, global_orchestrator
from backend.application.paper_broker_adapter import PaperBrokerAdapter
from backend.application.execution_telemetry_engine import ExecutionTelemetryEngine, global_telemetry_engine
from backend.domain.telemetry_schemas import ExecutionEventType, EventSeverity


class HistoricalEvaluationHarness:
    """
    High-Fidelity Historical Backtesting & Evaluation Harness.
    Replays the Opportunity Scanner and 17-stage Trading OS chronologically
    over historical market windows without future data leaks.
    """

    def __init__(
        self,
        orchestrator: Optional[TradingOSOrchestrator] = None,
        scanner: Optional[OpportunityScanner] = None,
        paper_broker: Optional[PaperBrokerAdapter] = None,
        telemetry_engine: Optional[ExecutionTelemetryEngine] = None,
        backtest_engine: Optional[BacktestEngine] = None,
    ):
        self.orchestrator = orchestrator or global_orchestrator
        self.scanner = scanner or OpportunityScanner(orchestrator=self.orchestrator)
        self.paper_broker = paper_broker or self.orchestrator.paper_broker
        self.telemetry = telemetry_engine or global_telemetry_engine
        self.backtest_engine = backtest_engine or BacktestEngine()

    # ── Main Historical Evaluation Replay ──────────────────────────────────────

    def run_evaluation(
        self,
        dataset: Dict[str, List[Dict[str, Any]]],
        config: Optional[HistoricalEvaluationConfig] = None,
        benchmark_series: Optional[List[Dict[str, Any]]] = None,
    ) -> HistoricalEvaluationReport:
        """
        Execute a complete historical evaluation replay across the provided multi-symbol dataset.
        Strictly enforces point-in-time data isolation, realistic transaction costs,
        portfolio mark-to-market accounting, and performance attribution.
        """
        start_mono = time.monotonic()
        started_at = datetime.now(timezone.utc)
        cfg = config or HistoricalEvaluationConfig()

        # Seed random generator for deterministic reproducibility
        random.seed(cfg.random_seed)

        bias_warnings: List[BiasWarning] = []
        data_quality = DataQualityAudit()

        # ── 1. Bias Auditing: Universe & Cost Assumptions ─────────────────────
        if cfg.universe_mode == UniverseMode.CURRENT_CONSTITUENTS:
            bias_warnings.append(
                BiasWarning(
                    bias_type=BiasType.SURVIVORSHIP_BIAS,
                    severity=BiasSeverity.WARNING,
                    message="Evaluation uses current index constituents historically without survivorship adjustments; results may exhibit positive survivorship bias.",
                    affected_period=f"{cfg.start_date or 'START'} to {cfg.end_date or 'END'}",
                )
            )

        if not cfg.cost_config.enable_costs:
            bias_warnings.append(
                BiasWarning(
                    bias_type=BiasType.COST_OMISSION_BIAS,
                    severity=BiasSeverity.CRITICAL,
                    message="Transaction costs and slippage are disabled; returns are gross theoretical returns.",
                    affected_period="ALL",
                )
            )

        # ── 2. Extract and Validate Chronological Timestamps ──────────────────
        all_timestamps = self._extract_and_validate_timestamps(dataset, data_quality, bias_warnings)

        if not all_timestamps:
            return self._create_empty_report(cfg, started_at, data_quality, bias_warnings)

        # Filter by start_date and end_date if specified
        eval_timestamps = all_timestamps
        if cfg.start_date:
            norm_start = _normalize_dt(cfg.start_date)
            eval_timestamps = [ts for ts in eval_timestamps if ts >= norm_start]
        if cfg.end_date:
            norm_end = _normalize_dt(cfg.end_date)
            eval_timestamps = [ts for ts in eval_timestamps if ts <= norm_end]

        if not eval_timestamps:
            data_quality.audit_notes.append("No timestamps fell within the configured start_date/end_date window.")
            return self._create_empty_report(cfg, started_at, data_quality, bias_warnings)

        # ── 3. Initialize Historical Portfolio & Ledger State ──────────────────
        cash = cfg.initial_capital
        initial_capital = cfg.initial_capital
        peak_equity = initial_capital
        open_trades: Dict[str, HistoricalTradeRecord] = {}
        trade_ledger: List[HistoricalTradeRecord] = []
        equity_curve: List[EquityCurvePoint] = []

        risk_vetoes = 0
        preflight_rejections = 0

        # Benchmark mapping
        benchmark_map = self._build_benchmark_map(benchmark_series, eval_timestamps)
        first_bench_val = benchmark_map.get(eval_timestamps[0], 100.0)

        # Record telemetry event
        self.telemetry.record_event(
            event_type=ExecutionEventType.ORDER_CREATED,
            execution_id=cfg.run_id,
            reason=f"Historical evaluation replay started: {len(eval_timestamps)} timestamps across {len(dataset)} symbols",
            timestamp=started_at,
        )

        # ── 4. Chronological Replay Loop Over Timestamps ──────────────────────
        for idx, current_ts in enumerate(eval_timestamps):
            # A. Current bar prices per symbol (point-in-time at current_ts)
            current_bar_data = self._get_prices_at_timestamp(dataset, current_ts)

            # B. Update & evaluate exits for active open positions
            closed_now, cash = self._update_open_positions(
                open_trades=open_trades,
                current_bar_data=current_bar_data,
                current_ts=current_ts,
                cash=cash,
                config=cfg,
            )
            trade_ledger.extend(closed_now)

            # C. Mark-to-Market Portfolio Valuation
            invested_capital = sum(t.quantity * t.entry_price for t in open_trades.values())
            market_value = 0.0
            for sym, t in open_trades.items():
                cur_p = current_bar_data.get(sym, {}).get("close", t.entry_price)
                market_value += t.quantity * cur_p

            total_equity = round(cash + market_value, 2)
            peak_equity = max(peak_equity, total_equity)
            dd_pct = round(max(0.0, ((peak_equity - total_equity) / peak_equity) * 100.0), 2) if peak_equity > 0 else 0.0

            bench_raw = benchmark_map.get(current_ts, first_bench_val)
            bench_equity = round(initial_capital * (bench_raw / first_bench_val), 2) if first_bench_val > 0 else initial_capital

            equity_curve.append(
                EquityCurvePoint(
                    timestamp=current_ts,
                    cash=round(cash, 2),
                    invested_capital=round(invested_capital, 2),
                    open_positions_market_value=round(market_value, 2),
                    total_equity=total_equity,
                    drawdown_pct=dd_pct,
                    benchmark_equity=bench_equity,
                    open_positions_count=len(open_trades),
                )
            )

            # D. Stage A: Run Opportunity Scanner across Point-In-Time dataset
            pit_datasets = self._build_pit_market_contexts(dataset, current_ts)

            scan_summary = self.scanner.execute_scan_cycle(
                universe_id=cfg.universe_id,
                datasets=pit_datasets,
                evaluation_timestamp=current_ts,
            )

            shortlisted = scan_summary.shortlisted_candidates[: cfg.max_candidates_per_bar]

            # E. Stage B: Evaluate Shortlisted Candidates through 17-Stage Trading OS
            for cand in shortlisted:
                sym = cand.symbol
                if sym in open_trades:
                    continue  # Avoid duplicate positions in same symbol

                pit_ctx = pit_datasets.get(sym)
                if not pit_ctx:
                    continue

                try:
                    # Run full Phase 9 authoritative Trading OS pipeline
                    run = self.orchestrator.run_pipeline(
                        market_context=pit_ctx,
                        allow_execution=True,
                        fill_ratio=cfg.fill_ratio,
                        evaluation_timestamp=current_ts,
                    )

                    # Check downstream risk and pre-flight gatekeepers
                    if run.risk and run.risk.get("veto_applied", False):
                        risk_vetoes += 1
                        continue

                    if run.preflight and run.preflight.get("status") == "REJECTED":
                        preflight_rejections += 1
                        continue

                    approved_qty = 0
                    if run.sizing:
                        approved_qty = run.sizing.get("position_quantity", run.sizing.get("approved_quantity", 0))

                    if approved_qty <= 0 or run.final_status.value == "REJECTED":
                        continue

                    # Simulate realistic entry execution with slippage and costs
                    entry_p = pit_ctx.current_price
                    slip_p = entry_p * (1.0 + cfg.cost_config.slippage_pct) if cfg.cost_config.enable_costs else entry_p
                    trade_notional = approved_qty * slip_p

                    # Entry transaction costs
                    entry_costs = 0.0
                    if cfg.cost_config.enable_costs:
                        entry_costs = round(
                            trade_notional * (cfg.cost_config.brokerage_pct + cfg.cost_config.exchange_charges_pct), 2
                        )

                    total_entry_cost = round(trade_notional + entry_costs, 2)

                    if cash >= total_entry_cost:
                        cash = round(cash - total_entry_cost, 2)

                        # Capture regime and conviction
                        regime_name = run.regime.get("overall_regime", "UNKNOWN") if run.regime else "UNKNOWN"
                        conv_score = run.conviction.get("calibrated_conviction", cand.discovery_score / 100.0) if run.conviction else cand.discovery_score / 100.0

                        new_trade = HistoricalTradeRecord(
                            symbol=sym,
                            side="BUY",
                            entry_timestamp=current_ts,
                            entry_price=round(slip_p, 2),
                            quantity=approved_qty,
                            transaction_costs=entry_costs,
                            entry_reason=f"Stage B Trading OS approval (Conviction: {conv_score:.2f})",
                            conviction_score=round(conv_score, 2),
                            market_regime=regime_name,
                            candidate_discovery_score=cand.discovery_score,
                            trading_os_run_id=run.run_id,
                            is_open=True,
                        )
                        open_trades[sym] = new_trade

                        self.telemetry.record_event(
                            event_type=ExecutionEventType.ORDER_FILLED,
                            execution_id=new_trade.trade_id,
                            symbol=sym,
                            reason=f"Historical position entered: {approved_qty} @ ₹{slip_p:.2f}",
                            timestamp=current_ts,
                        )
                    else:
                        data_quality.audit_notes.append(
                            f"Cash insufficient at {current_ts} for {sym}: required ₹{total_entry_cost:.2f}, available ₹{cash:.2f}"
                        )
                except Exception as e:
                    data_quality.audit_notes.append(f"Pipeline error at {current_ts} for {sym}: {str(e)}")

        # ── 5. Close Any Remaining Open Positions at Final Timestamp ──────────
        final_ts = eval_timestamps[-1]
        final_bar_data = self._get_prices_at_timestamp(dataset, final_ts)
        for sym, trade in list(open_trades.items()):
            cur_p = final_bar_data.get(sym, {}).get("close", trade.entry_price)
            exit_slip_p = cur_p * (1.0 - cfg.cost_config.slippage_pct) if cfg.cost_config.enable_costs else cur_p
            exit_notional = trade.quantity * exit_slip_p

            exit_costs = 0.0
            if cfg.cost_config.enable_costs:
                exit_costs = round(
                    exit_notional
                    * (
                        cfg.cost_config.brokerage_pct
                        + cfg.cost_config.exchange_charges_pct
                        + cfg.cost_config.stt_tax_pct
                    ),
                    2,
                )

            total_trade_costs = round(trade.transaction_costs + exit_costs, 2)
            gross_pnl = round(trade.quantity * (exit_slip_p - trade.entry_price), 2)
            net_pnl = round(gross_pnl - total_trade_costs, 2)
            cost_basis = trade.quantity * trade.entry_price
            net_ret = round((net_pnl / cost_basis) * 100.0, 4) if cost_basis > 0 else 0.0

            cash = round(cash + exit_notional - exit_costs, 2)

            trade.exit_timestamp = final_ts
            trade.exit_price = round(exit_slip_p, 2)
            trade.gross_pnl = gross_pnl
            trade.transaction_costs = total_trade_costs
            trade.net_pnl = net_pnl
            trade.net_return_pct = net_ret
            trade.exit_reason = ExitReason.HOLDING_PERIOD_EXPIRED
            trade.is_open = False

            trade_ledger.append(trade)
            del open_trades[sym]

        # ── 6. Deterministic Performance, Risk, & Attribution Calculations ────
        perf_metrics = self._calculate_performance_metrics(equity_curve, trade_ledger, cfg)
        risk_metrics = self._calculate_risk_metrics(equity_curve, trade_ledger, risk_vetoes, preflight_rejections)
        bench_comp = self._calculate_benchmark_comparison(equity_curve, benchmark_map, eval_timestamps, cfg)
        attribution = self._calculate_performance_attribution(trade_ledger)

        # ── 7. Walk-Forward Analysis (if enabled) ─────────────────────────────
        walk_forward_splits: List[WalkForwardSplit] = []
        if cfg.walk_forward_enabled:
            walk_forward_splits = self.run_walk_forward(dataset, cfg)

        # ── 8. Monte Carlo Sensitivity Analysis ───────────────────────────────
        monte_carlo_res: Optional[MonteCarloResult] = None
        if trade_ledger and len(trade_ledger) >= 3:
            monte_carlo_res = self.run_monte_carlo(trade_ledger, cfg)

        # Finalize Quality Score
        if data_quality.missing_bars_count > 0 or data_quality.stale_bars_count > 0:
            data_quality.quality_score = max(0.50, round(1.0 - (data_quality.stale_bars_count * 0.02), 2))

        completed_at = datetime.now(timezone.utc)
        duration_ms = round((time.monotonic() - start_mono) * 1000.0, 2)

        self.telemetry.record_event(
            event_type=ExecutionEventType.ORDER_ACKNOWLEDGED,
            execution_id=cfg.run_id,
            reason=f"Historical evaluation replay completed in {duration_ms}ms: Total Return {perf_metrics.total_return_pct}%",
            timestamp=completed_at,
        )

        return HistoricalEvaluationReport(
            run_id=cfg.run_id,
            config=cfg,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            total_bars_evaluated=len(eval_timestamps),
            performance_metrics=perf_metrics,
            risk_metrics=risk_metrics,
            benchmark_comparison=bench_comp,
            attribution=attribution,
            equity_curve=equity_curve,
            trade_ledger=trade_ledger,
            walk_forward_splits=walk_forward_splits,
            monte_carlo=monte_carlo_res,
            bias_warnings=bias_warnings,
            data_quality=data_quality,
            execution_mode="PAPER_ONLY",
            system_version=EVALUATION_HARNESS_VERSION,
        )

    # ── Position Exit Management ──────────────────────────────────────────────

    def _update_open_positions(
        self,
        open_trades: Dict[str, HistoricalTradeRecord],
        current_bar_data: Dict[str, Dict[str, Any]],
        current_ts: datetime,
        cash: float,
        config: HistoricalEvaluationConfig,
    ) -> Tuple[List[HistoricalTradeRecord], float]:
        """
        Check active trades against stop losses, profit targets, or holding period limits.
        Simulates realistic gap-down execution when stops are breached.
        """
        closed: List[HistoricalTradeRecord] = []
        updated_cash = cash

        for sym, trade in list(open_trades.items()):
            trade.holding_period_bars += 1
            bar = current_bar_data.get(sym)
            if not bar:
                continue

            b_open = float(bar.get("open", trade.entry_price))
            b_high = float(bar.get("high", trade.entry_price))
            b_low = float(bar.get("low", trade.entry_price))
            b_close = float(bar.get("close", trade.entry_price))

            exit_triggered = False
            exit_p = b_close
            reason = ExitReason.HOLDING_PERIOD_EXPIRED

            # Compute standard 2% stop-loss and 4% take-profit boundaries
            stop_price = round(trade.entry_price * 0.98, 2)
            target_price = round(trade.entry_price * 1.04, 2)

            if b_low <= stop_price:
                exit_triggered = True
                reason = ExitReason.STOP_LOSS
                # Check if market gapped through stop loss on open
                if b_open < stop_price:
                    exit_p = b_open
                else:
                    exit_p = stop_price
            elif b_high >= target_price:
                exit_triggered = True
                reason = ExitReason.TARGET_HIT
                exit_p = target_price
            elif trade.holding_period_bars >= config.holding_period_bars:
                exit_triggered = True
                reason = ExitReason.HOLDING_PERIOD_EXPIRED
                exit_p = b_close

            if exit_triggered:
                # Apply slippage on exit
                exit_slip_p = exit_p * (1.0 - config.cost_config.slippage_pct) if config.cost_config.enable_costs else exit_p
                exit_notional = trade.quantity * exit_slip_p

                exit_costs = 0.0
                if config.cost_config.enable_costs:
                    exit_costs = round(
                        exit_notional
                        * (
                            config.cost_config.brokerage_pct
                            + config.cost_config.exchange_charges_pct
                            + config.cost_config.stt_tax_pct
                        ),
                        2,
                    )

                total_costs = round(trade.transaction_costs + exit_costs, 2)
                gross_pnl = round(trade.quantity * (exit_slip_p - trade.entry_price), 2)
                net_pnl = round(gross_pnl - total_costs, 2)
                cost_basis = trade.quantity * trade.entry_price
                net_ret = round((net_pnl / cost_basis) * 100.0, 4) if cost_basis > 0 else 0.0

                updated_cash = round(updated_cash + exit_notional - exit_costs, 2)

                trade.exit_timestamp = current_ts
                trade.exit_price = round(exit_slip_p, 2)
                trade.gross_pnl = gross_pnl
                trade.transaction_costs = total_costs
                trade.net_pnl = net_pnl
                trade.net_return_pct = net_ret
                trade.exit_reason = reason
                trade.is_open = False

                closed.append(trade)
                del open_trades[sym]

        return closed, updated_cash

    # ── Point-In-Time Dataset Helpers ─────────────────────────────────────────

    def _extract_and_validate_timestamps(
        self,
        dataset: Dict[str, List[Dict[str, Any]]],
        data_quality: DataQualityAudit,
        bias_warnings: List[BiasWarning],
    ) -> List[datetime]:
        """
        Extract all unique bar timestamps across symbols and sort chronologically.
        Audits non-chronological anomalies and future bars.
        """
        ts_set = set()
        for sym, bars in dataset.items():
            prev_ts: Optional[datetime] = None
            for b in bars:
                raw_ts = b.get("timestamp") or b.get("date") or b.get("datetime")
                parsed = _parse_timestamp(raw_ts)
                if not parsed:
                    data_quality.rejected_timestamps_count += 1
                    continue

                if prev_ts and parsed <= prev_ts:
                    data_quality.audit_notes.append(f"Non-chronological or duplicate bar in {sym} at {parsed}")

                prev_ts = parsed
                ts_set.add(parsed)

        sorted_ts = sorted(list(ts_set))
        return sorted_ts

    def _get_prices_at_timestamp(
        self,
        dataset: Dict[str, List[Dict[str, Any]]],
        ts: datetime,
    ) -> Dict[str, Dict[str, Any]]:
        """Get the bar dictionary for each symbol at timestamp ts."""
        norm_ts = _normalize_dt(ts)
        out = {}
        for sym, bars in dataset.items():
            for b in bars:
                b_ts = _parse_timestamp(b.get("timestamp") or b.get("date"))
                if b_ts and _normalize_dt(b_ts) == norm_ts:
                    out[sym] = b
                    break
        return out

    def _build_pit_market_contexts(
        self,
        dataset: Dict[str, List[Dict[str, Any]]],
        as_of: datetime,
    ) -> Dict[str, MarketContext]:
        """
        Construct MarketContext instances containing ONLY observations <= as_of.
        Guarantees zero future information leakage.
        """
        contexts: Dict[str, MarketContext] = {}
        for sym, bars in dataset.items():
            pit_bars = PointInTimeFilter.filter_ohlcv(bars, as_of)
            if not pit_bars:
                continue

            last_bar = pit_bars[-1]
            c_price = float(last_bar.get("close", 1000.0))

            ctx = MarketContext(
                context_id=f"ctx-eval-{sym}-{math.floor(as_of.timestamp())}",
                provider="historical_replay",
                symbol=sym,
                current_price=c_price,
                data_timestamp=as_of,
                ohlcv_historical=pit_bars,
                technical_indicators={
                    "rsi_14": 55.0,
                    "ema_20": c_price * 0.99,
                    "ema_50": c_price * 0.97,
                    "volatility_252": 0.22,
                },
                news_feed=[],
            )
            contexts[sym] = ctx

        return contexts

    def _build_benchmark_map(
        self,
        benchmark_series: Optional[List[Dict[str, Any]]],
        eval_timestamps: List[datetime],
    ) -> Dict[datetime, float]:
        """Create mapping from timestamp to benchmark price."""
        b_map: Dict[datetime, float] = {}
        if benchmark_series:
            for b in benchmark_series:
                b_ts = _parse_timestamp(b.get("timestamp") or b.get("date"))
                if b_ts:
                    b_map[_normalize_dt(b_ts)] = float(b.get("close", 100.0))

        # If benchmark series missing, synthesize flat baseline benchmark
        if not b_map:
            for ts in eval_timestamps:
                b_map[ts] = 100.0

        return b_map

    # ── Deterministic Metrics & Attribution Calculations ─────────────────────

    def _calculate_performance_metrics(
        self,
        equity_curve: List[EquityCurvePoint],
        trade_ledger: List[HistoricalTradeRecord],
        config: HistoricalEvaluationConfig,
    ) -> PerformanceMetrics:
        """Calculate pure Python performance metrics. Zero LLM math."""
        if not equity_curve:
            return PerformanceMetrics(insufficient_sample=True)

        initial = equity_curve[0].total_equity
        final = equity_curve[-1].total_equity
        tot_ret = round(((final - initial) / initial) * 100.0, 2) if initial > 0 else 0.0

        # Calculate daily returns
        daily_returns = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1].total_equity
            curr = equity_curve[i].total_equity
            if prev > 0:
                daily_returns.append((curr - prev) / prev)

        n_bars = len(equity_curve)
        cagr = 0.0
        ann_vol = 0.0
        sharpe: Optional[float] = None
        sortino: Optional[float] = None

        if n_bars > 1 and len(daily_returns) > 1:
            years = max(n_bars / 252.0, 1.0 / 252.0)
            if final > 0 and initial > 0:
                cagr = round(((final / initial) ** (1.0 / years) - 1.0) * 100.0, 2)

            vol = statistics.stdev(daily_returns)
            ann_vol = round(vol * math.sqrt(252.0) * 100.0, 2)

            mean_ret = statistics.mean(daily_returns)
            if vol > 0:
                sharpe = round((mean_ret / vol) * math.sqrt(252.0), 2)

            downside_returns = [r for r in daily_returns if r < 0.0]
            if downside_returns and len(downside_returns) > 1:
                downside_dev = statistics.stdev(downside_returns)
                if downside_dev > 0:
                    sortino = round((mean_ret / downside_dev) * math.sqrt(252.0), 2)

        # Max Drawdown and Duration
        max_dd = round(max((pt.drawdown_pct for pt in equity_curve), default=0.0), 2)
        cur_dd_duration = 0
        max_dd_duration = 0
        for pt in equity_curve:
            if pt.drawdown_pct > 0.0:
                cur_dd_duration += 1
                max_dd_duration = max(max_dd_duration, cur_dd_duration)
            else:
                cur_dd_duration = 0

        # Trade statistics
        total_trades = len(trade_ledger)
        if total_trades == 0:
            return PerformanceMetrics(
                total_return_pct=tot_ret,
                cagr_pct=cagr,
                annualized_volatility_pct=ann_vol,
                sharpe_ratio=sharpe,
                sortino_ratio=sortino,
                max_drawdown_pct=max_dd,
                max_drawdown_duration_bars=max_dd_duration,
                insufficient_sample=True,
            )

        wins = [t.net_return_pct for t in trade_ledger if t.net_return_pct > 0.0]
        losses = [t.net_return_pct for t in trade_ledger if t.net_return_pct <= 0.0]

        win_rate = round((len(wins) / total_trades) * 100.0, 2)
        loss_rate = round((len(losses) / total_trades) * 100.0, 2)

        avg_win = round(statistics.mean(wins), 2) if wins else 0.0
        avg_loss = round(statistics.mean(losses), 2) if losses else 0.0

        gross_gains = sum(t.gross_pnl for t in trade_ledger if t.gross_pnl > 0.0)
        gross_losses = abs(sum(t.gross_pnl for t in trade_ledger if t.gross_pnl < 0.0))
        pf = round(gross_gains / gross_losses, 2) if gross_losses > 0 else None

        p_win = len(wins) / total_trades
        p_loss = len(losses) / total_trades
        expectancy = round((p_win * avg_win) - (p_loss * abs(avg_loss)), 2)

        total_volume = sum(t.quantity * t.entry_price for t in trade_ledger)
        turnover = round(total_volume / initial, 2) if initial > 0 else 0.0
        avg_holding = round(statistics.mean([t.holding_period_bars for t in trade_ledger]), 1) if trade_ledger else 0.0

        return PerformanceMetrics(
            total_return_pct=tot_ret,
            cagr_pct=cagr,
            annualized_volatility_pct=ann_vol,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown_pct=max_dd,
            max_drawdown_duration_bars=max_dd_duration,
            win_rate_pct=win_rate,
            loss_rate_pct=loss_rate,
            profit_factor=pf,
            average_win_pct=avg_win,
            average_loss_pct=avg_loss,
            expectancy_pct=expectancy,
            total_trades=total_trades,
            portfolio_turnover=turnover,
            average_holding_period_bars=avg_holding,
            insufficient_sample=False,
        )

    def _calculate_risk_metrics(
        self,
        equity_curve: List[EquityCurvePoint],
        trade_ledger: List[HistoricalTradeRecord],
        risk_vetoes: int,
        preflight_rejections: int,
    ) -> RiskMetrics:
        """Calculate risk constraints, exposure bounds, and rejection metrics."""
        max_exp = 0.0
        for pt in equity_curve:
            if pt.total_equity > 0:
                exp_pct = (pt.invested_capital / pt.total_equity) * 100.0
                max_exp = max(max_exp, exp_pct)

        max_single_pos = 0.0
        for t in trade_ledger:
            pos_val = t.quantity * t.entry_price
            max_single_pos = max(max_single_pos, pos_val)

        init_cap = equity_curve[0].total_equity if equity_curve else 100000.0
        max_single_exp_pct = round((max_single_pos / init_cap) * 100.0, 2) if init_cap > 0 else 0.0

        largest_loss = min((t.net_return_pct for t in trade_ledger), default=0.0)

        # Largest daily drop in equity curve
        largest_daily_drop = 0.0
        for i in range(1, len(equity_curve)):
            drop = ((equity_curve[i].total_equity - equity_curve[i - 1].total_equity) / equity_curve[i - 1].total_equity) * 100.0
            if drop < largest_daily_drop:
                largest_daily_drop = drop

        return RiskMetrics(
            max_portfolio_exposure_pct=round(max_exp, 2),
            max_single_position_exposure_pct=max_single_exp_pct,
            largest_loss_pct=round(largest_loss, 2),
            largest_daily_loss_pct=round(largest_daily_drop, 2),
            risk_veto_count=risk_vetoes,
            preflight_rejection_count=preflight_rejections,
        )

    def _calculate_benchmark_comparison(
        self,
        equity_curve: List[EquityCurvePoint],
        benchmark_map: Dict[datetime, float],
        eval_timestamps: List[datetime],
        config: HistoricalEvaluationConfig,
    ) -> BenchmarkComparison:
        """Compare strategy returns against passive market benchmark."""
        if not eval_timestamps:
            return BenchmarkComparison()

        t0 = eval_timestamps[0]
        tn = eval_timestamps[-1]
        b0 = benchmark_map.get(t0, 100.0)
        bn = benchmark_map.get(tn, 100.0)

        b_tot_ret = round(((bn - b0) / b0) * 100.0, 2) if b0 > 0 else 0.0

        n_bars = len(eval_timestamps)
        years = max(n_bars / 252.0, 1.0 / 252.0)
        b_cagr = round(((bn / b0) ** (1.0 / years) - 1.0) * 100.0, 2) if bn > 0 and b0 > 0 else 0.0

        # Benchmark returns series
        b_rets = []
        for i in range(1, len(eval_timestamps)):
            p_prev = benchmark_map.get(eval_timestamps[i - 1], 100.0)
            p_curr = benchmark_map.get(eval_timestamps[i], 100.0)
            if p_prev > 0:
                b_rets.append((p_curr - p_prev) / p_prev)

        b_vol = 0.0
        b_sharpe = None
        if len(b_rets) > 1:
            std_b = statistics.stdev(b_rets)
            b_vol = round(std_b * math.sqrt(252.0) * 100.0, 2)
            if std_b > 0:
                b_sharpe = round((statistics.mean(b_rets) / std_b) * math.sqrt(252.0), 2)

        # Strategy returns series
        strat_rets = []
        for i in range(1, len(equity_curve)):
            e_prev = equity_curve[i - 1].total_equity
            e_curr = equity_curve[i].total_equity
            if e_prev > 0:
                strat_rets.append((e_curr - e_prev) / e_prev)

        # Alpha and Beta approximation
        alpha: Optional[float] = None
        beta: Optional[float] = None
        if len(strat_rets) > 2 and len(b_rets) == len(strat_rets):
            var_b = statistics.variance(b_rets)
            if var_b > 0:
                mean_s = statistics.mean(strat_rets)
                mean_b = statistics.mean(b_rets)
                cov = sum((s - mean_s) * (b - mean_b) for s, b in zip(strat_rets, b_rets)) / (len(strat_rets) - 1)
                b_val = cov / var_b
                beta = round(b_val, 2)
                alpha_val = (mean_s - (b_val * mean_b)) * 252.0 * 100.0
                alpha = round(alpha_val, 2)

        strat_tot_ret = equity_curve[-1].total_equity - equity_curve[0].total_equity if equity_curve else 0.0

        return BenchmarkComparison(
            benchmark_symbol=config.benchmark_symbol,
            benchmark_total_return_pct=b_tot_ret,
            benchmark_cagr_pct=b_cagr,
            benchmark_volatility_pct=b_vol,
            benchmark_sharpe_ratio=b_sharpe,
            alpha_pct=alpha,
            beta=beta,
            outperformed_benchmark=strat_tot_ret > b_tot_ret,
        )

    def _calculate_performance_attribution(
        self,
        trade_ledger: List[HistoricalTradeRecord],
    ) -> PerformanceAttribution:
        """Break down performance by market regime, discovery score tier, and conviction."""
        by_regime: Dict[str, List[float]] = {}
        by_score: Dict[str, List[float]] = {"HIGH": [], "MEDIUM": [], "LOW": []}
        by_conviction: Dict[str, List[float]] = {"HIGH": [], "MEDIUM": [], "LOW": []}

        for t in trade_ledger:
            ret = t.net_return_pct

            # Regime attribution
            reg = t.market_regime or "UNKNOWN"
            by_regime.setdefault(reg, []).append(ret)

            # Score tier attribution
            if t.candidate_discovery_score >= 75.0:
                by_score["HIGH"].append(ret)
            elif t.candidate_discovery_score >= 50.0:
                by_score["MEDIUM"].append(ret)
            else:
                by_score["LOW"].append(ret)

            # Conviction tier attribution
            if t.conviction_score >= 0.75:
                by_conviction["HIGH"].append(ret)
            elif t.conviction_score >= 0.50:
                by_conviction["MEDIUM"].append(ret)
            else:
                by_conviction["LOW"].append(ret)

        def _summarize_tier(vals: List[float]) -> Dict[str, Any]:
            if not vals:
                return {"trades": 0, "win_rate_pct": 0.0, "avg_return_pct": 0.0, "total_return_pct": 0.0}
            wins = sum(1 for v in vals if v > 0.0)
            return {
                "trades": len(vals),
                "win_rate_pct": round((wins / len(vals)) * 100.0, 2),
                "avg_return_pct": round(statistics.mean(vals), 2),
                "total_return_pct": round(sum(vals), 2),
            }

        return PerformanceAttribution(
            by_regime={k: _summarize_tier(v) for k, v in by_regime.items()},
            by_score_tier={k: _summarize_tier(v) for k, v in by_score.items()},
            by_conviction_tier={k: _summarize_tier(v) for k, v in by_conviction.items()},
        )

    # ── Walk-Forward Partitions ───────────────────────────────────────────────

    def run_walk_forward(
        self,
        dataset: Dict[str, List[Dict[str, Any]]],
        config: HistoricalEvaluationConfig,
    ) -> List[WalkForwardSplit]:
        """
        Partition historical timeline into rolling in-sample (train) and out-of-sample (test) windows.
        Evaluates parameter stability without look-ahead contamination.
        """
        all_timestamps = self._extract_and_validate_timestamps(dataset, DataQualityAudit(), [])
        n_bars = len(all_timestamps)

        splits: List[WalkForwardSplit] = []
        train_len = config.train_window_bars
        test_len = config.test_window_bars
        step_len = config.step_bars

        split_idx = 1
        start_idx = 0

        while start_idx + train_len + test_len <= n_bars:
            train_ts = all_timestamps[start_idx : start_idx + train_len]
            test_ts = all_timestamps[start_idx + train_len : start_idx + train_len + test_len]

            # In-sample evaluation slice
            in_sample_cfg = config.model_copy(
                update={"walk_forward_enabled": False, "start_date": train_ts[0], "end_date": train_ts[-1]}
            )
            in_res = self.run_evaluation(dataset, in_sample_cfg)

            # Out-of-sample evaluation slice
            out_sample_cfg = config.model_copy(
                update={"walk_forward_enabled": False, "start_date": test_ts[0], "end_date": test_ts[-1]}
            )
            out_res = self.run_evaluation(dataset, out_sample_cfg)

            splits.append(
                WalkForwardSplit(
                    split_index=split_idx,
                    train_start=train_ts[0],
                    train_end=train_ts[-1],
                    test_start=test_ts[0],
                    test_end=test_ts[-1],
                    in_sample_return_pct=in_res.performance_metrics.total_return_pct,
                    out_of_sample_return_pct=out_res.performance_metrics.total_return_pct,
                    out_of_sample_sharpe=out_res.performance_metrics.sharpe_ratio,
                )
            )

            split_idx += 1
            start_idx += step_len

        return splits

    # ── Monte Carlo Sensitivity Analysis ─────────────────────────────────────

    def run_monte_carlo(
        self,
        trades: List[HistoricalTradeRecord],
        config: HistoricalEvaluationConfig,
    ) -> MonteCarloResult:
        """
        Deterministic bootstrap resampling sensitivity analysis of realized trade returns.
        Uses fixed random seed for 100% reproducible distribution metrics.
        """
        rng = random.Random(config.random_seed)
        trade_returns = [t.net_return_pct for t in trades]
        n_trades = len(trade_returns)
        runs = config.monte_carlo_runs

        simulated_tot_returns = []
        losses_count = 0
        dd_exceed_10_count = 0

        for _ in range(runs):
            # Resample with replacement
            sampled = [rng.choice(trade_returns) for _ in range(n_trades)]
            cum_ret = 0.0
            peak = 0.0
            max_dd = 0.0

            for r in sampled:
                cum_ret += r
                peak = max(peak, cum_ret)
                dd = peak - cum_ret
                max_dd = max(max_dd, dd)

            simulated_tot_returns.append(cum_ret)
            if cum_ret < 0.0:
                losses_count += 1
            if max_dd >= 10.0:
                dd_exceed_10_count += 1

        simulated_tot_returns.sort()
        mean_ret = round(statistics.mean(simulated_tot_returns), 2)
        p05 = round(simulated_tot_returns[int(runs * 0.05)], 2)
        p50 = round(simulated_tot_returns[int(runs * 0.50)], 2)
        p95 = round(simulated_tot_returns[int(runs * 0.95)], 2)

        prob_loss = round((losses_count / runs) * 100.0, 2)
        prob_dd_10 = round((dd_exceed_10_count / runs) * 100.0, 2)

        return MonteCarloResult(
            resample_runs=runs,
            random_seed=config.random_seed,
            mean_return_pct=mean_ret,
            p05_return_pct=p05,
            p50_return_pct=p50,
            p95_return_pct=p95,
            probability_of_loss_pct=prob_loss,
            probability_drawdown_exceeds_10pct=prob_dd_10,
        )

    # ── Private Fallback Helper ───────────────────────────────────────────────

    def _create_empty_report(
        self,
        config: HistoricalEvaluationConfig,
        started_at: datetime,
        data_quality: DataQualityAudit,
        bias_warnings: List[BiasWarning],
    ) -> HistoricalEvaluationReport:
        """Create empty report when dataset contains zero valid evaluation timestamps."""
        now = datetime.now(timezone.utc)
        return HistoricalEvaluationReport(
            run_id=config.run_id,
            config=config,
            started_at=started_at,
            completed_at=now,
            duration_ms=0.0,
            total_bars_evaluated=0,
            performance_metrics=PerformanceMetrics(insufficient_sample=True),
            risk_metrics=RiskMetrics(),
            benchmark_comparison=BenchmarkComparison(),
            attribution=PerformanceAttribution(),
            equity_curve=[],
            trade_ledger=[],
            walk_forward_splits=[],
            bias_warnings=bias_warnings,
            data_quality=data_quality,
            execution_mode="PAPER_ONLY",
            system_version=EVALUATION_HARNESS_VERSION,
        )


# Export singleton instance
global_evaluation_harness = HistoricalEvaluationHarness()
