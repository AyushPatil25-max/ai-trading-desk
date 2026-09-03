"""
Phase 10 — Opportunity Scanner & Continuous Background Discovery Engine

High-throughput, deterministic candidate discovery subsystem.
Coordinates Stage A (cheap deterministic screening) and Stage B (deep Trading OS analysis)
over Point-In-Time market universes (NIFTY 50, NIFTY 500, Custom) with priority queues,
failure isolation, rate limiting, and thread-safe background discovery.
"""

from collections import deque
from datetime import datetime, timezone, timedelta
import math
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from backend.domain.opportunity_schemas import (
    OPPORTUNITY_SCANNER_VERSION,
    CandidatePriority,
    CandidateScreeningStatus,
    DeterministicScreenMetrics,
    MarketUniverse,
    OpportunityCandidate,
    OpportunityScannerConfig,
    ScannerCycleSummary,
    ScannerHealthStatus,
    ScannerState,
    UniverseID,
)
from backend.domain.schemas import MarketContext, HistoricalWindow
from backend.domain.telemetry_schemas import ExecutionEventType, EventSeverity
from backend.application.trading_os_orchestrator import TradingOSOrchestrator, global_orchestrator
from backend.application.execution_telemetry_engine import ExecutionTelemetryEngine, global_telemetry_engine
from backend.infrastructure.security_master import get_security_master


# ── Canonical NIFTY 50 Baseline ─────────────────────────────────────────────
_CANONICAL_NIFTY_50_SYMBOLS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "BHARTIARTL.NS", "ITC.NS", "SBIN.NS", "LICI.NS", "HINDUNILVR.NS",
    "LT.NS", "BAJFINANCE.NS", "HCLTECH.NS", "MARUTI.NS", "SUNPHARMA.NS",
    "ADANIENT.NS", "KOTAKBANK.NS", "TATAMOTORS.NS", "AXISBANK.NS", "NTPC.NS",
    "ONGC.NS", "TITAN.NS", "POWERGRID.NS", "COALINDIA.NS", "ADANIPORTS.NS",
    "ULTRACEMCO.NS", "ASIANPAINT.NS", "BAJAJFINSV.NS", "WIPRO.NS", "BPCL.NS",
    "JSWSTEEL.NS", "TATASTEEL.NS", "GRASIM.NS", "HEROMOTOCO.NS", "TECHM.NS",
    "M&M.NS", "NESTLEIND.NS", "HINDALCO.NS", "CIPLA.NS", "DRREDDY.NS",
    "EICHERMOT.NS", "APOLLOHOSP.NS", "DIVISLAB.NS", "BRITANNIA.NS", "SBILIFE.NS",
    "HDFCLIFE.NS", "INDUSINDBK.NS", "TATACONSUM.NS", "SHRIRAMFIN.NS", "BAJAJ-AUTO.NS",
]


class OpportunityScanner:
    """
    Two-stage opportunity discovery engine:
    - Stage A: Inexpensive deterministic filtering & multi-factor scoring (pure Python).
    - Stage B: Shortlisted candidate evaluation through the authoritative Phase 9 Trading OS.
    """

    def __init__(
        self,
        config: Optional[OpportunityScannerConfig] = None,
        orchestrator: Optional[TradingOSOrchestrator] = None,
        telemetry_engine: Optional[ExecutionTelemetryEngine] = None,
        market_data_provider: Optional[Any] = None,
    ) -> None:
        self.config = config or OpportunityScannerConfig()
        self.orchestrator = orchestrator or global_orchestrator
        self.telemetry_engine = telemetry_engine or global_telemetry_engine
        self.market_data_provider = market_data_provider

        # Universe registry (universe_id -> MarketUniverse)
        self._universes: Dict[str, MarketUniverse] = {}
        self._initialize_default_universes()

        # Thread-safe candidate and history storage
        self._lock = threading.RLock()
        self._candidates: Dict[str, OpportunityCandidate] = {}
        self._candidate_queue: deque = deque()
        self._seen_candidate_tokens: Dict[str, float] = {}  # token -> timestamp
        self._cycle_history: List[ScannerCycleSummary] = []
        self._total_cycles_completed: int = 0
        self._last_scan_duration_ms: float = 0.0
        self._last_scan_at: Optional[datetime] = None
        self._errors_count: int = 0

    # ── Universe Management ─────────────────────────────────────────────────

    def _initialize_default_universes(self) -> None:
        """Initialize standard NIFTY_50 and NIFTY_500 universes."""
        # NIFTY 50
        nifty_50 = MarketUniverse(
            universe_id=UniverseID.NIFTY_50.value,
            name="NIFTY 50",
            description="Top 50 large-cap blue-chip equities listed on National Stock Exchange of India",
            symbols=list(_CANONICAL_NIFTY_50_SYMBOLS),
            metadata={"source": "NSE_OFFICIAL", "tier": "LARGE_CAP"},
        )
        self._universes[UniverseID.NIFTY_50.value] = nifty_50

        # NIFTY 500 (from SecurityMaster)
        nifty_500_symbols: List[str] = []
        try:
            sm = get_security_master()
            all_secs = sm.list_securities(active_only=True)
            for sec in all_secs:
                sym = sec.nse_symbol or f"{sec.canonical_symbol}.NS"
                if sym not in nifty_500_symbols:
                    nifty_500_symbols.append(sym)
        except Exception:
            # Fallback to Nifty 50 if SecurityMaster fails
            nifty_500_symbols = list(_CANONICAL_NIFTY_50_SYMBOLS)

        nifty_500 = MarketUniverse(
            universe_id=UniverseID.NIFTY_500.value,
            name="NIFTY 500",
            description="Top 500 companies representing ~96% of free-float market cap on NSE",
            symbols=nifty_500_symbols,
            metadata={"source": "SECURITY_MASTER", "count": len(nifty_500_symbols)},
        )
        self._universes[UniverseID.NIFTY_500.value] = nifty_500

    def register_universe(self, universe: MarketUniverse) -> None:
        """Register or update an approved stock universe."""
        with self._lock:
            self._universes[universe.universe_id] = universe

    def get_universe(self, universe_id: str) -> Optional[MarketUniverse]:
        """Retrieve a market universe definition by ID."""
        with self._lock:
            return self._universes.get(universe_id)

    def list_universes(self) -> List[MarketUniverse]:
        """List all registered market universes."""
        with self._lock:
            return list(self._universes.values())

    # ── Stage A: Deterministic Screening & Scoring ──────────────────────────

    def screen_candidate(
        self,
        symbol: str,
        market_context: MarketContext,
        universe_id: str = "NIFTY_50",
        market_regime: Optional[Any] = None,
        portfolio_state: Optional[Any] = None,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> OpportunityCandidate:
        """
        Execute Stage A: Inexpensive deterministic filtering and multi-factor scoring.
        Zero LLM usage — pure Python quantitative evaluation.
        """
        now = evaluation_timestamp or datetime.now(timezone.utc)
        rejection_reasons: List[str] = []
        is_degraded = False

        # 1. Price Validity Check
        current_price = getattr(market_context, "current_price", 0.0)
        if math.isnan(current_price) or math.isinf(current_price) or current_price <= 0:
            rejection_reasons.append(f"INVALID_PRICE: Price ₹{current_price} is non-positive or non-finite.")

        if current_price < self.config.min_price:
            rejection_reasons.append(f"PRICE_BELOW_MIN: Price ₹{current_price:.2f} < ₹{self.config.min_price:.2f}.")
        elif current_price > self.config.max_price:
            rejection_reasons.append(f"PRICE_ABOVE_MAX: Price ₹{current_price:.2f} > ₹{self.config.max_price:.2f}.")

        # 2. Historical Bar Count Sufficiency
        ohlcv = getattr(market_context, "ohlcv_historical", []) or []
        bar_count = len(ohlcv)
        if bar_count < self.config.min_historical_bars:
            rejection_reasons.append(f"INSUFFICIENT_BARS: Bar count {bar_count} < {self.config.min_historical_bars} minimum.")

        data_ts = getattr(market_context, "data_timestamp", now)
        if data_ts:
            norm_now = now.replace(tzinfo=timezone.utc) if not now.tzinfo else now
            norm_ts = data_ts.replace(tzinfo=timezone.utc) if not data_ts.tzinfo else data_ts
            data_age = (norm_now - norm_ts).total_seconds()
        else:
            data_age = 0.0
        if data_age < 0:
            # Future data leak detected
            rejection_reasons.append(f"FUTURE_DATA_LEAK: Data timestamp {data_ts} is ahead of evaluation timestamp {now}.")
        elif data_age > self.config.max_market_data_age_seconds:
            rejection_reasons.append(f"STALE_MARKET_DATA: Data age {data_age:.1f}s > {self.config.max_market_data_age_seconds:.1f}s limit.")
            is_degraded = True

        # 4. Extract Technical Indicators & Liquidity
        tech = getattr(market_context, "technical_indicators", {}) or {}
        rsi = tech.get("rsi_14", tech.get("rsi", None))
        ema_20 = tech.get("ema_20", None)
        ema_50 = tech.get("ema_50", None)

        # Fallback calculation if technical indicators are missing but OHLCV is present
        closes = [float(b.get("close", 0.0)) for b in ohlcv if b.get("close") is not None]
        volumes = [float(b.get("volume", 0.0)) for b in ohlcv if b.get("volume") is not None]

        if not closes and current_price > 0:
            closes = [current_price] * bar_count if bar_count else [current_price]

        if len(closes) >= 20 and (ema_20 is None or rsi is None):
            ema_20 = sum(closes[-20:]) / 20.0
        if len(closes) >= 50 and ema_50 is None:
            ema_50 = sum(closes[-50:]) / 50.0

        # Calculate average volume and turnover in Crores (1 Cr = 10,000,000 INR)
        avg_volume_20 = sum(volumes[-20:]) / len(volumes[-20:]) if len(volumes) >= 20 else (volumes[-1] if volumes else 100000.0)
        turnover_cr = (current_price * avg_volume_20) / 10000000.0

        # 5. Liquidity Floor Check
        if turnover_cr < self.config.min_liquidity_cr:
            rejection_reasons.append(f"ILLIQUID: 20-day turnover ₹{turnover_cr:.2f} Cr < ₹{self.config.min_liquidity_cr:.2f} Cr minimum.")

        # Calculate Annualized Volatility
        volatility_annualized = 0.20  # Default 20%
        if len(closes) >= 10:
            pct_changes = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes)) if closes[i-1] > 0]
            if pct_changes:
                mean_change = sum(pct_changes) / len(pct_changes)
                var = sum((x - mean_change) ** 2 for x in pct_changes) / len(pct_changes)
                volatility_annualized = round(math.sqrt(var) * math.sqrt(252), 4)

        # 6. Deterministic Multi-Factor Scoring (0.0 to 100.0)
        # Factor A: Trend Alignment (0 to 30 pts)
        trend_score = 0.0
        if ema_20 and current_price > ema_20:
            trend_score += 15.0
        if ema_20 and ema_50 and ema_20 > ema_50:
            trend_score += 15.0

        # Factor B: Momentum (0 to 30 pts)
        momentum_score = 0.0
        if rsi is not None:
            if 45.0 <= rsi <= 65.0:
                momentum_score = 30.0
            elif 40.0 <= rsi <= 72.0:
                momentum_score = 22.0
            elif 30.0 <= rsi < 40.0 or 72.0 < rsi <= 80.0:
                momentum_score = 12.0
            else:
                momentum_score = 5.0
        else:
            momentum_score = 15.0  # Neutral midpoint

        # Factor C: Liquidity & Turnover (0 to 20 pts)
        liquidity_score = 0.0
        if turnover_cr >= 15.0:
            liquidity_score = 20.0
        elif turnover_cr >= 5.0:
            liquidity_score = 15.0
        elif turnover_cr >= 1.0:
            liquidity_score = 10.0
        else:
            liquidity_score = 5.0

        # Factor D: Volatility Health (0 to 20 pts)
        vol_score = 0.0
        if 0.12 <= volatility_annualized <= 0.40:
            vol_score = 20.0
        elif 0.08 <= volatility_annualized <= 0.55:
            vol_score = 14.0
        else:
            vol_score = 6.0

        # Factor E: Market Regime Alignment (-15 to +10 pts)
        regime_alignment = 0.0
        regime_name = "UNKNOWN"
        if market_regime:
            regime_name = str(getattr(market_regime, "overall_regime", "UNKNOWN"))
            if "BULL" in regime_name:
                regime_alignment = 10.0
            elif "BEAR" in regime_name:
                regime_alignment = -15.0
            elif "VOLATILE" in regime_name or "HIGH_VOLATILITY" in regime_name:
                regime_alignment = -10.0

        # Factor F: Portfolio Overlap Adjustment (-15 pts)
        portfolio_adjustment = 0.0
        if portfolio_state and hasattr(portfolio_state, "positions"):
            if symbol in portfolio_state.positions:
                portfolio_adjustment = -15.0

        raw_score = trend_score + momentum_score + liquidity_score + vol_score + regime_alignment + portfolio_adjustment
        discovery_score = round(max(0.0, min(100.0, raw_score)), 2)

        # 7. Priority Assignment
        if discovery_score >= 75.0:
            priority = CandidatePriority.HIGH
        elif discovery_score >= 50.0:
            priority = CandidatePriority.MEDIUM
        else:
            priority = CandidatePriority.LOW

        # 8. Screening Status & Reasons
        passed = (len(rejection_reasons) == 0) and (discovery_score >= self.config.min_discovery_score)
        if passed:
            status = CandidateScreeningStatus.SCREENED
            reasons = [f"Passed deterministic screen with score {discovery_score}/100."]
        else:
            status = CandidateScreeningStatus.DEGRADED if (is_degraded and not rejection_reasons) else CandidateScreeningStatus.REJECTED
            reasons = list(rejection_reasons)
            if discovery_score < self.config.min_discovery_score:
                reasons.append(f"SCORE_BELOW_MIN: Discovery score {discovery_score} < {self.config.min_discovery_score} threshold.")

        metrics = DeterministicScreenMetrics(
            current_price=current_price,
            volume_20d_avg=avg_volume_20,
            turnover_cr=turnover_cr,
            rsi_14=rsi,
            ema_20=ema_20,
            ema_50=ema_50,
            trend_alignment_score=trend_score,
            momentum_score=momentum_score,
            volatility_annualized=volatility_annualized,
            liquidity_score=liquidity_score,
            regime_alignment_score=regime_alignment,
            data_age_seconds=data_age,
            bar_count=bar_count,
        )

        candidate_id = OpportunityCandidate.generate_candidate_id(symbol, universe_id, now)

        return OpportunityCandidate(
            candidate_id=candidate_id,
            symbol=symbol,
            universe=universe_id,
            discovered_at=now,
            discovery_score=discovery_score,
            priority=priority,
            screening_status=status,
            screening_reasons=reasons,
            metrics=metrics,
            data_quality="DEGRADED" if is_degraded else "HIGH",
            market_regime=regime_name,
            created_at=now,
            updated_at=now,
        )

    # ── Stage B: Deep Analysis via Phase 9 Trading OS ───────────────────────

    def evaluate_candidate_deep(
        self,
        candidate: OpportunityCandidate,
        market_context: MarketContext,
        allow_execution: Optional[bool] = None,
        fill_ratio: Optional[float] = None,
        committee_decision: Optional[Any] = None,
        debate_result: Optional[Any] = None,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> OpportunityCandidate:
        """
        Execute Stage B: Dispatch shortlisted candidate to the authoritative 17-stage Trading OS.
        Does NOT bypass any Risk, Sizing, Pre-Flight, or Paper Broker gatekeepers.
        """
        now = evaluation_timestamp or datetime.now(timezone.utc)
        exec_allowed = self.config.allow_execution if allow_execution is None else allow_execution
        f_ratio = self.config.fill_ratio if fill_ratio is None else fill_ratio

        # Record candidate analysis started in telemetry
        self.telemetry_engine.record_event(
            event_type=ExecutionEventType.ORDER_CREATED,
            execution_id=candidate.candidate_id,
            symbol=candidate.symbol,
            reason=f"Deep Trading OS analysis started for candidate {candidate.symbol} (Score: {candidate.discovery_score})",
            timestamp=now,
        )

        candidate.screening_status = CandidateScreeningStatus.PASSED_TO_TRADING_OS
        candidate.updated_at = now

        try:
            # Execute Phase 9 unified pipeline
            run = self.orchestrator.run_pipeline(
                market_context=market_context,
                committee_decision=committee_decision,
                debate_result=debate_result,
                allow_execution=exec_allowed,
                fill_ratio=f_ratio,
                evaluation_timestamp=now,
            )

            summary = self.orchestrator.get_summary(run)

            # Update candidate with authoritative downstream outcomes
            candidate.trading_os_run_id = run.run_id
            candidate.pipeline_status = run.final_status.value
            candidate.final_decision = summary.decision
            candidate.conviction = summary.conviction
            candidate.risk_status = summary.risk_status
            candidate.approved_quantity = summary.approved_size
            candidate.screening_status = CandidateScreeningStatus.ANALYZED
            candidate.updated_at = datetime.now(timezone.utc)

            if run.paper_order:
                candidate.execution_order_id = run.paper_order.get("order_id")

            # Telemetry record completion
            self.telemetry_engine.record_event(
                event_type=ExecutionEventType.ORDER_ACKNOWLEDGED,
                execution_id=candidate.candidate_id,
                symbol=candidate.symbol,
                reason=f"Deep Trading OS analysis completed: Decision={summary.decision}, Status={run.final_status.value}",
                timestamp=now,
            )

        except Exception as ex:
            candidate.pipeline_status = "FAILED"
            candidate.screening_reasons.append(f"TRADING_OS_FAILURE: {str(ex)}")
            candidate.updated_at = datetime.now(timezone.utc)
            self._errors_count += 1
            self.telemetry_engine.record_event(
                event_type=ExecutionEventType.EXECUTION_ERROR,
                execution_id=candidate.candidate_id,
                symbol=candidate.symbol,
                reason=f"Trading OS execution error for {candidate.symbol}: {str(ex)}",
                severity=EventSeverity.ERROR,
                timestamp=now,
            )

        with self._lock:
            self._candidates[candidate.candidate_id] = candidate

        return candidate

    # ── Discovery Cycle Orchestration ───────────────────────────────────────

    def execute_scan_cycle(
        self,
        universe_id: Optional[str] = None,
        datasets: Optional[Dict[str, Any]] = None,
        market_regime: Optional[Any] = None,
        portfolio_state: Optional[Any] = None,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> ScannerCycleSummary:
        """
        Execute a single complete discovery cycle:
        1. Load Universe
        2. Filter & Screen (Stage A)
        3. Rank & Shortlist Top-K
        4. Deduplicate against recent window
        5. Deep Analyze Shortlist (Stage B via Phase 9 Trading OS)
        6. Update Queue and Emit Telemetry
        """
        start_mono = time.monotonic()
        now = evaluation_timestamp or datetime.now(timezone.utc)
        u_id = universe_id or self.config.universe_id
        scan_id = f"scan-{math.floor(now.timestamp())}"

        universe = self.get_universe(u_id)
        if not universe or not universe.symbols:
            summary = ScannerCycleSummary(
                scan_id=scan_id,
                universe_id=u_id,
                started_at=now,
                completed_at=now,
                errors=[f"Universe '{u_id}' not found or contains no symbols."],
            )
            return summary

        symbols = universe.symbols
        universe_size = len(symbols)
        errors: List[str] = []
        screened_candidates: List[OpportunityCandidate] = []
        shortlisted_candidates: List[OpportunityCandidate] = []

        # ── Stage A: Screen all symbols with failure isolation ────────────────
        batch_size = self.config.batch_size

        for i in range(0, universe_size, batch_size):
            batch = symbols[i : i + batch_size]
            for sym in batch:
                try:
                    ctx: Optional[MarketContext] = None
                    if datasets and sym in datasets:
                        d = datasets[sym]
                        if isinstance(d, MarketContext):
                            ctx = d
                        elif isinstance(d, dict):
                            ctx = MarketContext(
                                symbol=sym,
                                current_price=d.get("current_price", 1000.0),
                                data_timestamp=d.get("data_timestamp", now),
                                provider="SIMULATED",
                                context_id=f"ctx-{sym}",
                                ohlcv_historical=d.get("ohlcv_historical", []),
                                technical_indicators=d.get("technical_indicators", {}),
                                fundamental_data=d.get("fundamental_data", {}),
                                sector_data={"sector": d.get("sector", "General")},
                            )
                    elif self.market_data_provider:
                        ctx = self.market_data_provider.get_market_context(sym, window=HistoricalWindow.RECENT)
                    else:
                        # Synthetic default fallback for offline tests
                        bars = [
                            {
                                "timestamp": (now - timedelta(days=30 - j)).isoformat(),
                                "open": round(1490.0 + j * 2.0, 2),
                                "high": round(1510.0 + j * 2.0, 2),
                                "low": round(1485.0 + j * 2.0, 2),
                                "close": round(1500.0 + j * 2.0, 2),
                                "volume": 500000.0,
                            }
                            for j in range(30)
                        ]
                        ctx = MarketContext(
                            symbol=sym,
                            current_price=1560.0,
                            data_timestamp=now,
                            provider="SIMULATED",
                            context_id=f"ctx-{sym}",
                            ohlcv_historical=bars,
                            technical_indicators={
                                "rsi_14": 58.0,
                                "ema_20": 1540.0,
                                "ema_50": 1510.0,
                                "volatility_252": 0.18,
                            },
                        )

                    cand = self.screen_candidate(
                        symbol=sym,
                        market_context=ctx,
                        universe_id=u_id,
                        market_regime=market_regime,
                        portfolio_state=portfolio_state,
                        evaluation_timestamp=now,
                    )
                    screened_candidates.append(cand)

                except Exception as ex:
                    # Failure Isolation: single symbol failure must not abort entire scan
                    errors.append(f"Symbol {sym} screening failed: {str(ex)}")
                    self._errors_count += 1

        # ── Deduplicate and Rank Candidates ──────────────────────────────────
        valid_candidates = [c for c in screened_candidates if c.screening_status == CandidateScreeningStatus.SCREENED]
        valid_candidates.sort(key=lambda c: (c.discovery_score, c.priority.value), reverse=True)

        dedup_window = self.config.dedup_window_seconds
        now_ts = now.timestamp()

        with self._lock:
            # Clean expired deduplication tokens
            self._seen_candidate_tokens = {
                tok: ts for tok, ts in self._seen_candidate_tokens.items()
                if (now_ts - ts) < dedup_window
            }

            for cand in valid_candidates:
                token = f"{cand.symbol}:{cand.universe}"
                if token not in self._seen_candidate_tokens:
                    shortlisted_candidates.append(cand)
                    self._seen_candidate_tokens[token] = now_ts
                    if len(shortlisted_candidates) >= self.config.max_candidates_per_cycle:
                        break

            # Add to internal priority queue with bounded overflow handling
            for cand in shortlisted_candidates:
                cand.screening_status = CandidateScreeningStatus.SHORTLISTED
                self._enqueue_candidate(cand)

        # ── Stage B: Deep Trading OS Analysis on Shortlisted Top-K ───────────
        analyzed_count = 0
        passed_count = 0
        risk_rejected_count = 0
        paper_exec_count = 0

        for cand in shortlisted_candidates:
            # Retrieve or reconstruct candidate's MarketContext
            ctx = None
            if datasets and cand.symbol in datasets:
                d = datasets[cand.symbol]
                if isinstance(d, MarketContext):
                    ctx = d
                elif isinstance(d, dict):
                    ctx = MarketContext(
                        symbol=cand.symbol,
                        current_price=d.get("current_price", cand.metrics.current_price if cand.metrics else 1500.0),
                        data_timestamp=d.get("data_timestamp", now),
                        provider="SIMULATED",
                        context_id=f"ctx-{cand.symbol}",
                        ohlcv_historical=d.get("ohlcv_historical", []),
                        technical_indicators=d.get("technical_indicators", {}),
                        fundamental_data=d.get("fundamental_data", {}),
                        sector_data={"sector": d.get("sector", "General")},
                    )
            else:
                ctx = MarketContext(
                    symbol=cand.symbol,
                    current_price=cand.metrics.current_price if cand.metrics else 1500.0,
                    data_timestamp=now,
                    provider="SIMULATED",
                    context_id=f"ctx-{cand.symbol}",
                )

            analyzed_cand = self.evaluate_candidate_deep(
                candidate=cand,
                market_context=ctx,
                allow_execution=self.config.allow_execution,
                fill_ratio=self.config.fill_ratio,
                evaluation_timestamp=now,
            )
            analyzed_count += 1

            if analyzed_cand.final_decision in ("BUY", "STRONG_BUY") and analyzed_cand.pipeline_status == "COMPLETED":
                passed_count += 1
            if analyzed_cand.risk_status == "VETOED" or analyzed_cand.pipeline_status == "REJECTED":
                risk_rejected_count += 1
            if analyzed_cand.execution_order_id:
                paper_exec_count += 1

        duration_ms = round((time.monotonic() - start_mono) * 1000.0, 2)
        summary = ScannerCycleSummary(
            scan_id=scan_id,
            universe_id=u_id,
            started_at=now,
            completed_at=datetime.now(timezone.utc),
            duration_ms=duration_ms,
            universe_size=universe_size,
            screened_count=len(screened_candidates),
            shortlisted_count=len(shortlisted_candidates),
            analyzed_count=analyzed_count,
            passed_count=passed_count,
            risk_rejected_count=risk_rejected_count,
            paper_execution_count=paper_exec_count,
            shortlisted_candidates=shortlisted_candidates,
            errors=errors,
        )

        with self._lock:
            self._cycle_history.append(summary)
            self._total_cycles_completed += 1
            self._last_scan_duration_ms = duration_ms
            self._last_scan_at = now

        return summary

    # ── Queue Management & Overflow ─────────────────────────────────────────

    def _enqueue_candidate(self, candidate: OpportunityCandidate) -> None:
        """
        Thread-safe candidate enqueueing with deterministic overflow handling.
        If queue is full, low-priority candidates are dropped first.
        """
        max_q = self.config.max_queue_size
        if len(self._candidate_queue) >= max_q:
            # Deterministic eviction: sort existing queue, remove lowest priority
            priority_weights = {CandidatePriority.HIGH: 3, CandidatePriority.MEDIUM: 2, CandidatePriority.LOW: 1}
            sorted_items = sorted(
                list(self._candidate_queue),
                key=lambda c: (priority_weights.get(c.priority, 1), c.discovery_score),
            )
            # Evict the single lowest-ranked item
            evicted = sorted_items.pop(0)
            self._candidate_queue = deque(sorted_items)

        self._candidate_queue.append(candidate)
        self._candidates[candidate.candidate_id] = candidate

    def get_candidate(self, candidate_id: str) -> Optional[OpportunityCandidate]:
        """Retrieve candidate by ID."""
        with self._lock:
            return self._candidates.get(candidate_id)

    def list_candidates(
        self,
        universe: Optional[str] = None,
        priority: Optional[CandidatePriority] = None,
        status: Optional[CandidateScreeningStatus] = None,
        limit: int = 50,
    ) -> List[OpportunityCandidate]:
        """Query discovered candidates with optional filters."""
        with self._lock:
            res = list(self._candidates.values())

        if universe:
            res = [c for c in res if c.universe == universe]
        if priority:
            res = [c for c in res if c.priority == priority]
        if status:
            res = [c for c in res if c.screening_status == status]

        def _safe_dt(c: OpportunityCandidate) -> datetime:
            dt = c.discovered_at
            if dt is None:
                return datetime.min.replace(tzinfo=timezone.utc)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        res.sort(key=_safe_dt, reverse=True)
        return res[:limit]

    def get_health_status(self) -> ScannerHealthStatus:
        """Return operational health metrics of the scanner."""
        with self._lock:
            return ScannerHealthStatus(
                state=ScannerState.STOPPED,
                is_healthy=self._errors_count < 10,
                queue_size=len(self._candidate_queue),
                total_cycles_completed=self._total_cycles_completed,
                last_scan_at=self._last_scan_at,
                last_scan_duration_ms=self._last_scan_duration_ms,
                active_workers=0,
                errors_count=self._errors_count,
                current_universe=self.config.universe_id,
            )


# ── Background Discovery Worker ─────────────────────────────────────────────

class BackgroundDiscoveryWorker:
    """
    Thread-safe continuous background discovery worker.
    Manages periodic scan cycles, pausing, graceful stopping, and health status reporting.
    """

    def __init__(
        self,
        scanner: Optional[OpportunityScanner] = None,
        scan_interval_seconds: Optional[float] = None,
    ) -> None:
        self.scanner = scanner or OpportunityScanner()
        if scan_interval_seconds:
            self.scanner.config.scan_interval_seconds = scan_interval_seconds

        self._state = ScannerState.STOPPED
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._lock = threading.RLock()

    @property
    def state(self) -> ScannerState:
        with self._lock:
            return self._state

    def start(self) -> bool:
        """Start the background discovery worker loop."""
        with self._lock:
            if self._state in (ScannerState.RUNNING, ScannerState.STARTING):
                return False

            self._state = ScannerState.STARTING
            self._stop_event.clear()
            self._pause_event.clear()

            self._thread = threading.Thread(
                target=self._worker_loop,
                name="OpportunityScannerWorker",
                daemon=True,
            )
            self._thread.start()
            self._state = ScannerState.RUNNING
            return True

    def stop(self, timeout: float = 5.0) -> bool:
        """Gracefully stop the background discovery worker."""
        with self._lock:
            if self._state == ScannerState.STOPPED:
                return True

            self._state = ScannerState.STOPPING
            self._stop_event.set()
            self._pause_event.clear()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

        with self._lock:
            self._state = ScannerState.STOPPED
            self._thread = None
            return True

    def pause(self) -> bool:
        """Pause continuous discovery scans."""
        with self._lock:
            if self._state != ScannerState.RUNNING:
                return False
            self._pause_event.set()
            self._state = ScannerState.PAUSED
            return True

    def resume(self) -> bool:
        """Resume paused continuous discovery scans."""
        with self._lock:
            if self._state != ScannerState.PAUSED:
                return False
            self._pause_event.clear()
            self._state = ScannerState.RUNNING
            return True

    def get_status(self) -> ScannerHealthStatus:
        """Get live health and worker status."""
        health = self.scanner.get_health_status()
        with self._lock:
            health.state = self._state
            health.active_workers = 1 if (self._thread and self._thread.is_alive()) else 0
        return health

    def _worker_loop(self) -> None:
        """Main periodic discovery loop running in background thread."""
        interval = self.scanner.config.scan_interval_seconds

        while not self._stop_event.is_set():
            if not self._pause_event.is_set():
                try:
                    self.scanner.execute_scan_cycle()
                except Exception:
                    # Catch all exceptions to prevent thread dying unhandled
                    pass

            # Controlled interruptible sleep
            self._stop_event.wait(timeout=interval)


# Global singleton instances for API routing
global_scanner = OpportunityScanner()
global_opportunity_scanner = global_scanner
global_worker = BackgroundDiscoveryWorker(scanner=global_scanner)
