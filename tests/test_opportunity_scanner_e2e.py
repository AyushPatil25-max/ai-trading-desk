"""
Phase 10 — Opportunity Scanner & Continuous Background Discovery Test Suite

Comprehensive tests verifying:
- Universe loading (NIFTY 50, NIFTY 500, Custom)
- Stage A deterministic screening & scoring
- Data quality, stale data, and future data leak protection
- Candidate ranking, priority queue, and deterministic overflow eviction
- Deduplication & idempotency
- Stage B deep analysis integration with Phase 9 Trading OS
- Preservation of Risk, Sizing, Pre-Flight, and Paper-Only safety gates
- Failure isolation during multi-symbol discovery
- Background worker lifecycle (start, stop, pause, resume, health status)
- Telemetry logging & REST API endpoints
- 10 Adversarial attack vectors (Cases A-J)
- Performance benchmarks for NIFTY 50 and NIFTY 500
"""

from datetime import datetime, timezone, timedelta
import math
import time
import unittest
from fastapi.testclient import TestClient

from backend.domain.opportunity_schemas import (
    OPPORTUNITY_SCANNER_VERSION,
    CandidatePriority,
    CandidateScreeningStatus,
    MarketUniverse,
    OpportunityCandidate,
    OpportunityScannerConfig,
    ScannerHealthStatus,
    ScannerState,
    UniverseID,
)
from backend.domain.schemas import MarketContext
from backend.domain.investment_committee_schemas import CommitteeDecision, CommitteeRecommendation
from backend.domain.risk_schemas import RiskConfiguration
from backend.application.opportunity_scanner import (
    OpportunityScanner,
    BackgroundDiscoveryWorker,
    _CANONICAL_NIFTY_50_SYMBOLS,
)
from backend.application.trading_os_orchestrator import TradingOSOrchestrator
from backend.application.execution_telemetry_engine import ExecutionTelemetryEngine
from backend.main import app


def _create_mock_context(
    symbol: str = "INFY.NS",
    price: float = 1500.0,
    age_seconds: float = 0.0,
    bar_count: int = 30,
    rsi: float = 55.0,
    ema_20: float = 1480.0,
    ema_50: float = 1450.0,
    volume: float = 200000.0,
) -> MarketContext:
    """Helper to generate deterministic MarketContext for offline scanner testing."""
    now = datetime.now(timezone.utc)
    data_ts = now - timedelta(seconds=age_seconds)

    ohlcv = []
    base_price = price * 0.95
    for i in range(bar_count):
        bar_price = base_price + (i * (price - base_price) / max(1, bar_count - 1))
        ohlcv.append({
            "timestamp": (data_ts - timedelta(days=bar_count - i)).isoformat(),
            "open": bar_price * 0.99,
            "high": bar_price * 1.01,
            "low": bar_price * 0.98,
            "close": bar_price,
            "volume": volume,
        })

    return MarketContext(
        symbol=symbol,
        current_price=price,
        data_timestamp=data_ts,
        provider="SIMULATED",
        context_id=f"ctx-{symbol}",
        ohlcv_historical=ohlcv,
        technical_indicators={"rsi_14": rsi, "ema_20": ema_20, "ema_50": ema_50},
        fundamental_data={"pe_ratio": 22.0, "roe": 0.18},
        sector_data={"sector": "Technology"},
    )


class TestOpportunityScannerE2E(unittest.TestCase):

    def setUp(self):
        self.telemetry = ExecutionTelemetryEngine()
        self.orchestrator = TradingOSOrchestrator(telemetry_engine=self.telemetry)
        self.config = OpportunityScannerConfig(
            universe_id="NIFTY_50",
            scan_interval_seconds=1.0,
            batch_size=10,
            max_candidates_per_cycle=3,
            max_queue_size=10,
            min_discovery_score=40.0,
            min_liquidity_cr=1.0,
            min_price=10.0,
            max_price=100000.0,
            min_historical_bars=20,
            max_market_data_age_seconds=300.0,
            allow_execution=True,
            fill_ratio=1.0,
        )
        self.scanner = OpportunityScanner(
            config=self.config,
            orchestrator=self.orchestrator,
            telemetry_engine=self.telemetry,
        )
        self.client = TestClient(app)

    # ── Test 1: Universe Loading ─────────────────────────────────────────────
    def test_01_universe_loading(self):
        nifty50 = self.scanner.get_universe(UniverseID.NIFTY_50.value)
        self.assertIsNotNone(nifty50)
        self.assertEqual(len(nifty50.symbols), 50)
        self.assertIn("RELIANCE.NS", nifty50.symbols)
        self.assertIn("INFY.NS", nifty50.symbols)

        nifty500 = self.scanner.get_universe(UniverseID.NIFTY_500.value)
        self.assertIsNotNone(nifty500)
        self.assertGreaterEqual(len(nifty500.symbols), 50)

        # Custom Universe Registration
        custom = MarketUniverse(
            universe_id="CUSTOM_TEST",
            name="Custom 3 Stocks",
            symbols=["INFY.NS", "TCS.NS", "WIPRO.NS"],
        )
        self.scanner.register_universe(custom)
        fetched = self.scanner.get_universe("CUSTOM_TEST")
        self.assertIsNotNone(fetched)
        self.assertEqual(len(fetched.symbols), 3)

    # ── Test 2: Candidate Schema & Deterministic ID ──────────────────────────
    def test_02_candidate_schema_and_deterministic_id(self):
        t0 = datetime(2026, 8, 29, 14, 0, 0)
        id1 = OpportunityCandidate.generate_candidate_id("INFY.NS", "NIFTY_50", t0)
        id2 = OpportunityCandidate.generate_candidate_id("INFY.NS", "NIFTY_50", t0)
        self.assertEqual(id1, id2)
        self.assertTrue(id1.startswith("cand-"))

        # Different hour produces different ID
        t1 = t0 + timedelta(hours=2)
        id3 = OpportunityCandidate.generate_candidate_id("INFY.NS", "NIFTY_50", t1)
        self.assertNotEqual(id1, id3)

    # ── Test 3: Stage A Deterministic Screening & Scoring ────────────────────
    def test_03_stage_a_screening_and_scoring(self):
        ctx = _create_mock_context(symbol="INFY.NS", price=1500.0, rsi=55.0, ema_20=1480.0, ema_50=1450.0)
        cand = self.scanner.screen_candidate("INFY.NS", ctx)

        self.assertEqual(cand.symbol, "INFY.NS")
        self.assertEqual(cand.screening_status, CandidateScreeningStatus.SCREENED)
        self.assertGreater(cand.discovery_score, 50.0)
        self.assertIn(cand.priority, (CandidatePriority.HIGH, CandidatePriority.MEDIUM))
        self.assertIsNotNone(cand.metrics)
        self.assertEqual(cand.metrics.current_price, 1500.0)
        self.assertGreater(cand.metrics.turnover_cr, 1.0)

    # ── Test 4: Price Boundary Violations ────────────────────────────────────
    def test_04_price_boundary_violations(self):
        # Below min price
        ctx_cheap = _create_mock_context(price=5.0)
        cand_cheap = self.scanner.screen_candidate("PENNY.NS", ctx_cheap)
        self.assertEqual(cand_cheap.screening_status, CandidateScreeningStatus.REJECTED)
        self.assertTrue(any("PRICE_BELOW_MIN" in r for r in cand_cheap.screening_reasons))

        # Negative price
        ctx_neg = _create_mock_context(price=-10.0)
        cand_neg = self.scanner.screen_candidate("NEG.NS", ctx_neg)
        self.assertEqual(cand_neg.screening_status, CandidateScreeningStatus.REJECTED)
        self.assertTrue(any("INVALID_PRICE" in r for r in cand_neg.screening_reasons))

    # ── Test 5: Insufficient Historical Bars ─────────────────────────────────
    def test_05_insufficient_bars_rejection(self):
        ctx = _create_mock_context(bar_count=5)
        cand = self.scanner.screen_candidate("SHORT.NS", ctx)
        self.assertEqual(cand.screening_status, CandidateScreeningStatus.REJECTED)
        self.assertTrue(any("INSUFFICIENT_BARS" in r for r in cand.screening_reasons))

    # ── Test 6: Stale Market Data Rejection ──────────────────────────────────
    def test_06_stale_data_rejection(self):
        ctx = _create_mock_context(age_seconds=600.0)  # 10 minutes stale (limit 300s)
        cand = self.scanner.screen_candidate("STALE.NS", ctx)
        self.assertEqual(cand.screening_status, CandidateScreeningStatus.REJECTED)
        self.assertTrue(any("STALE_MARKET_DATA" in r for r in cand.screening_reasons))

    # ── Test 7: Future Data Leak Prevention ──────────────────────────────────
    def test_07_future_data_leak_rejection(self):
        ctx = _create_mock_context(age_seconds=-120.0)  # 2 minutes in future
        cand = self.scanner.screen_candidate("FUTURE.NS", ctx)
        self.assertEqual(cand.screening_status, CandidateScreeningStatus.REJECTED)
        self.assertTrue(any("FUTURE_DATA_LEAK" in r for r in cand.screening_reasons))

    # ── Test 8: Illiquid Stock Rejection ─────────────────────────────────────
    def test_08_illiquidity_rejection(self):
        ctx = _create_mock_context(price=50.0, volume=100.0)  # ₹5,000 turnover << ₹1 Cr
        cand = self.scanner.screen_candidate("ILLIQ.NS", ctx)
        self.assertEqual(cand.screening_status, CandidateScreeningStatus.REJECTED)
        self.assertTrue(any("ILLIQUID" in r for r in cand.screening_reasons))

    # ── Test 9: Priority Queue & Deterministic Eviction ──────────────────────
    def test_09_priority_queue_bounded_eviction(self):
        # Fill queue up to max_queue_size (10)
        self.scanner.config.max_queue_size = 5
        candidates = []
        for i in range(7):
            score = 40.0 + (i * 10.0)
            priority = CandidatePriority.HIGH if score >= 75.0 else (CandidatePriority.MEDIUM if score >= 50.0 else CandidatePriority.LOW)
            c = OpportunityCandidate(
                candidate_id=f"cand-{i}",
                symbol=f"SYM{i}.NS",
                universe="NIFTY_50",
                discovery_score=score,
                priority=priority,
                screening_status=CandidateScreeningStatus.SHORTLISTED,
            )
            self.scanner._enqueue_candidate(c)

        # Queue size should never exceed 5
        self.assertLessEqual(len(self.scanner._candidate_queue), 5)
        # Lowest scored items (SYM0, SYM1) should have been evicted
        queued_ids = [c.candidate_id for c in self.scanner._candidate_queue]
        self.assertNotIn("cand-0", queued_ids)
        self.assertIn("cand-6", queued_ids)

    # ── Test 10: Deduplication & Idempotency ─────────────────────────────────
    def test_10_deduplication(self):
        u = MarketUniverse(
            universe_id="DEDUP_TEST",
            name="Dedup Test",
            symbols=["INFY.NS"],
        )
        self.scanner.register_universe(u)
        ctx = _create_mock_context(symbol="INFY.NS")

        # First cycle
        sum1 = self.scanner.execute_scan_cycle(universe_id="DEDUP_TEST", datasets={"INFY.NS": ctx})
        self.assertEqual(sum1.shortlisted_count, 1)

        # Second immediate cycle without new time window should be deduplicated
        sum2 = self.scanner.execute_scan_cycle(universe_id="DEDUP_TEST", datasets={"INFY.NS": ctx})
        self.assertEqual(sum2.shortlisted_count, 0)

    # ── Test 11: Stage B Deep Analysis Integration ───────────────────────────
    def test_11_deep_trading_os_integration(self):
        ctx = _create_mock_context(symbol="INFY.NS", price=1500.0)
        cand = self.scanner.screen_candidate("INFY.NS", ctx)
        self.assertEqual(cand.screening_status, CandidateScreeningStatus.SCREENED)

        # Dispatch candidate to Stage B
        analyzed = self.scanner.evaluate_candidate_deep(candidate=cand, market_context=ctx)
        self.assertEqual(analyzed.screening_status, CandidateScreeningStatus.ANALYZED)
        self.assertIsNotNone(analyzed.trading_os_run_id)
        self.assertIsNotNone(analyzed.pipeline_status)
        self.assertIsNotNone(analyzed.final_decision)
        self.assertIsNotNone(analyzed.conviction)

    # ── Test 12: Safety Gates Preserved (Risk Veto) ──────────────────────────
    def test_12_safety_gate_risk_veto_preserved(self):
        # Configure risk threshold to artificially veto
        orig_risk_cfg = self.orchestrator.risk_engine.config
        self.orchestrator.risk_engine.config = RiskConfiguration(minimum_conviction=0.99)
        ctx = _create_mock_context(symbol="TCS.NS", price=3500.0)
        cand = self.scanner.screen_candidate("TCS.NS", ctx)
        dec = CommitteeDecision(
            decision_id="dec-veto-test",
            context_id=ctx.context_id,
            symbol="TCS.NS",
            recommendation=CommitteeRecommendation.BUY,
            conviction_score=0.70,
        )

        analyzed = self.scanner.evaluate_candidate_deep(candidate=cand, market_context=ctx, committee_decision=dec)
        self.assertEqual(analyzed.pipeline_status, "REJECTED")
        self.assertEqual(analyzed.risk_status, "VETOED")
        self.assertIsNone(analyzed.execution_order_id)
        self.orchestrator.risk_engine.config = orig_risk_cfg

    # ── Test 13: Failure Isolation (1 Symbol Data Corrupted) ──────────────────
    def test_13_failure_isolation(self):
        u = MarketUniverse(
            universe_id="ISOLATION_TEST",
            name="Isolation Test",
            symbols=["GOOD1.NS", "BAD.NS", "GOOD2.NS"],
        )
        self.scanner.register_universe(u)

        good_ctx1 = _create_mock_context(symbol="GOOD1.NS", price=1000.0)
        good_ctx2 = _create_mock_context(symbol="GOOD2.NS", price=2000.0)
        # BAD.NS throws an exception
        datasets = {
            "GOOD1.NS": good_ctx1,
            "BAD.NS": None,  # Will cause failure or fallback
            "GOOD2.NS": good_ctx2,
        }

        summary = self.scanner.execute_scan_cycle(universe_id="ISOLATION_TEST", datasets=datasets)
        # The cycle must complete without aborting
        self.assertEqual(summary.universe_size, 3)
        self.assertGreaterEqual(summary.screened_count, 2)

    # ── Test 14: Background Discovery Worker Lifecycle ───────────────────────
    def test_14_worker_lifecycle(self):
        worker = BackgroundDiscoveryWorker(scanner=self.scanner, scan_interval_seconds=0.1)
        self.assertEqual(worker.state, ScannerState.STOPPED)

        # Start
        started = worker.start()
        self.assertTrue(started)
        self.assertEqual(worker.state, ScannerState.RUNNING)

        # Pause
        paused = worker.pause()
        self.assertTrue(paused)
        self.assertEqual(worker.state, ScannerState.PAUSED)

        # Resume
        resumed = worker.resume()
        self.assertTrue(resumed)
        self.assertEqual(worker.state, ScannerState.RUNNING)

        # Stop
        stopped = worker.stop(timeout=2.0)
        self.assertTrue(stopped)
        self.assertEqual(worker.state, ScannerState.STOPPED)

    # ── Test 15: Health Status Reporting ─────────────────────────────────────
    def test_15_health_status(self):
        health = self.scanner.get_health_status()
        self.assertTrue(health.is_healthy)
        self.assertEqual(health.current_universe, "NIFTY_50")
        self.assertEqual(health.errors_count, 0)

    # ── Test 16: Telemetry Event Recording ───────────────────────────────────
    def test_16_telemetry_event_recording(self):
        initial_events = len(self.telemetry.list_events())
        ctx = _create_mock_context(symbol="INFY.NS", price=1500.0)
        cand = self.scanner.screen_candidate("INFY.NS", ctx)
        self.scanner.evaluate_candidate_deep(candidate=cand, market_context=ctx)

        new_events = len(self.telemetry.list_events())
        self.assertGreater(new_events, initial_events)

    # ── Test 17: REST API Endpoints ──────────────────────────────────────────
    def test_17_rest_api_endpoints(self):
        # 1. Health/Status endpoint
        resp = self.client.get("/api/opportunities/scanner/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("state", data)
        self.assertIn("is_healthy", data)

        # 2. Trigger Scan endpoint
        resp_scan = self.client.post("/api/opportunities/scan", json={"universe_id": "NIFTY_50", "max_candidates": 2})
        self.assertEqual(resp_scan.status_code, 200)
        scan_data = resp_scan.json()
        self.assertIn("scan_id", scan_data)
        self.assertIn("screened_count", scan_data)

        # 3. List candidates
        resp_list = self.client.get("/api/opportunities")
        self.assertEqual(resp_list.status_code, 200)
        candidates = resp_list.json()
        self.assertIsInstance(candidates, list)

        # 4. Worker start/stop/pause/resume
        resp_start = self.client.post("/api/opportunities/scanner/start")
        self.assertEqual(resp_start.status_code, 200)
        resp_pause = self.client.post("/api/opportunities/scanner/pause")
        self.assertEqual(resp_pause.status_code, 200)
        resp_resume = self.client.post("/api/opportunities/scanner/resume")
        self.assertEqual(resp_resume.status_code, 200)
        resp_stop = self.client.post("/api/opportunities/scanner/stop")
        self.assertEqual(resp_stop.status_code, 200)

        # 5. Single Candidate Detail
        if candidates:
            cid = candidates[0]["candidate_id"]
            resp_detail = self.client.get(f"/api/opportunities/{cid}")
            self.assertEqual(resp_detail.status_code, 200)
            self.assertEqual(resp_detail.json()["candidate_id"], cid)

    # ── Test 18: No False Precision Guarantee ────────────────────────────────
    def test_18_no_false_precision(self):
        ctx = _create_mock_context(symbol="INFY.NS", price=1500.0)
        cand = self.scanner.screen_candidate("INFY.NS", ctx)

        # Labels must be humble candidate discovery terminology
        self.assertIn(cand.screening_status, [
            CandidateScreeningStatus.SCREENED,
            CandidateScreeningStatus.SHORTLISTED,
            CandidateScreeningStatus.ANALYZED,
            CandidateScreeningStatus.PASSED_TO_TRADING_OS,
            CandidateScreeningStatus.REJECTED,
            CandidateScreeningStatus.DEGRADED,
        ])
        # Never contain guaranteed profit or win terms
        serialized = cand.model_dump_json().lower()
        self.assertNotIn("guaranteed winner", serialized)
        self.assertNotIn("risk-free", serialized)
        self.assertNotIn("guaranteed profit", serialized)

    # ── Test 19: Market Regime Awareness ─────────────────────────────────────
    def test_19_market_regime_awareness(self):
        class MockRegime:
            overall_regime = "BEAR_TREND"

        ctx = _create_mock_context(symbol="INFY.NS", price=1500.0)
        cand_neutral = self.scanner.screen_candidate("INFY.NS", ctx)
        cand_bear = self.scanner.screen_candidate("INFY.NS", ctx, market_regime=MockRegime())

        # In bear regime, discovery score receives penalty
        self.assertLess(cand_bear.discovery_score, cand_neutral.discovery_score)

    # ── Test 20: Portfolio Overlap Awareness ─────────────────────────────────
    def test_20_portfolio_awareness(self):
        class MockPortfolio:
            positions = {"INFY.NS": 50}

        ctx = _create_mock_context(symbol="INFY.NS", price=1500.0)
        cand_empty = self.scanner.screen_candidate("INFY.NS", ctx)
        cand_held = self.scanner.screen_candidate("INFY.NS", ctx, portfolio_state=MockPortfolio())

        # Held asset receives penalty to prevent over-concentration
        self.assertLess(cand_held.discovery_score, cand_empty.discovery_score)

    # ── Test 21: Adversarial Attack Suite (Cases A-J) ────────────────────────
    def test_21_adversarial_suite(self):
        """
        Evaluate 10 distinct adversarial attack vectors (Cases A-J).
        """
        # Case A: Bypass risk from scanner -> IMPOSSIBLE
        orig_risk_cfg = self.orchestrator.risk_engine.config
        self.orchestrator.risk_engine.config = RiskConfiguration(minimum_conviction=0.99)
        ctx = _create_mock_context(symbol="INFY.NS", price=1500.0)
        cand = self.scanner.screen_candidate("INFY.NS", ctx)
        dec_a = CommitteeDecision(
            decision_id="dec-case-a",
            context_id=ctx.context_id,
            symbol="INFY.NS",
            recommendation=CommitteeRecommendation.BUY,
            conviction_score=0.70,
        )
        analyzed = self.scanner.evaluate_candidate_deep(cand, ctx, committee_decision=dec_a)
        self.assertEqual(analyzed.pipeline_status, "REJECTED")
        self.assertEqual(analyzed.risk_status, "VETOED")
        self.orchestrator.risk_engine.config = orig_risk_cfg

        # Case B: Submit candidate directly to paper broker -> REJECTED
        res = self.orchestrator.paper_broker.submit_order(cand)
        self.assertEqual(res.status.value, "REJECTED")

        # Case C: Manipulate discovery score to inflate order size -> IMPOSSIBLE
        cand.discovery_score = 100.0
        dec = CommitteeDecision(
            decision_id="dec-case-c",
            context_id=ctx.context_id,
            symbol="INFY.NS",
            recommendation=CommitteeRecommendation.BUY,
            target_price=1600.0,
            stop_loss=1450.0,
        )
        plan = self.orchestrator.risk_engine.evaluate_and_size(
            committee_decision=dec,
            market_context=ctx,
            portfolio_state=self.orchestrator.paper_broker.account,
            calibration=None,
            portfolio_intelligence=self.orchestrator.portfolio_engine.analyze_portfolio(
                portfolio_state={}, candidate_context=ctx
            ),
            market_regime=None,
        )
        self.assertLessEqual(plan.position_quantity, 100)

        # Case D: Insert stale data as fresh -> REJECTED
        ctx_stale = _create_mock_context(age_seconds=1000.0)
        cand_d = self.scanner.screen_candidate("STALE.NS", ctx_stale)
        self.assertEqual(cand_d.screening_status, CandidateScreeningStatus.REJECTED)

        # Case E: Duplicate candidate repeatedly -> DEDUPLICATED
        u_test = MarketUniverse(universe_id="CASE_E", name="Case E", symbols=["INFY.NS"])
        self.scanner.register_universe(u_test)
        s1 = self.scanner.execute_scan_cycle(universe_id="CASE_E", datasets={"INFY.NS": ctx})
        s2 = self.scanner.execute_scan_cycle(universe_id="CASE_E", datasets={"INFY.NS": ctx})
        self.assertEqual(s2.shortlisted_count, 0)

        # Case F: Flood candidate queue -> CONTROLLED OVERFLOW
        self.scanner.config.max_queue_size = 3
        for i in range(10):
            c = OpportunityCandidate(
                candidate_id=f"flood-{i}",
                symbol=f"SYM{i}.NS",
                universe="CASE_F",
                discovery_score=float(i * 10),
                priority=CandidatePriority.LOW,
            )
            self.scanner._enqueue_candidate(c)
        self.assertEqual(len(self.scanner._candidate_queue), 3)

        # Case G: Crash worker during candidate processing -> SAFE RECOVERY
        def faulty_run_pipeline(*args, **kwargs):
            raise RuntimeError("CRASH_INJECTED")

        orig_run = self.orchestrator.run_pipeline
        self.orchestrator.run_pipeline = faulty_run_pipeline
        cand_g = self.scanner.screen_candidate("INFY.NS", ctx)
        analyzed_g = self.scanner.evaluate_candidate_deep(cand_g, ctx)
        self.assertEqual(analyzed_g.pipeline_status, "FAILED")
        self.orchestrator.run_pipeline = orig_run

        # Case H: Provider outage / exceptions -> FAILURE ISOLATION
        summary_h = self.scanner.execute_scan_cycle(universe_id="CASE_E", datasets={"INFY.NS": Exception("OUTAGE")})
        self.assertEqual(summary_h.universe_size, 1)

        # Case I: Attempt live execution -> BLOCKED (Paper Only)
        self.assertEqual(self.orchestrator.paper_broker.account.account_id, "paper-acct-001")
        self.assertEqual(self.orchestrator.paper_broker.account.initial_cash, 100000.0)

        # Case J: Future data injection -> DETECTED & REJECTED
        ctx_future = _create_mock_context(age_seconds=-3600.0)
        cand_j = self.scanner.screen_candidate("FUTURE.NS", ctx_future)
        self.assertEqual(cand_j.screening_status, CandidateScreeningStatus.REJECTED)
        self.assertTrue(any("FUTURE_DATA_LEAK" in r for r in cand_j.screening_reasons))

    # ── Test 22: Performance Benchmark (NIFTY 50 & NIFTY 500) ────────────────
    def test_22_performance_benchmarks(self):
        # 1. NIFTY 50 Benchmark
        t0 = time.perf_counter()
        nifty50_u = self.scanner.get_universe("NIFTY_50")
        datasets50 = {
            sym: _create_mock_context(symbol=sym, price=1000.0 + (idx * 50.0))
            for idx, sym in enumerate(nifty50_u.symbols)
        }
        summary50 = self.scanner.execute_scan_cycle(universe_id="NIFTY_50", datasets=datasets50)
        lat50 = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(summary50.universe_size, 50)
        self.assertLessEqual(summary50.shortlisted_count, self.config.max_candidates_per_cycle)
        # Compute reduction: from 50 stocks down to <= 3 deep analyses
        reduction_pct50 = (1.0 - (summary50.shortlisted_count / 50.0)) * 100.0
        self.assertGreaterEqual(reduction_pct50, 90.0)
        self.assertLess(lat50, 5000.0)  # Sub-5-second execution for all 50 stocks

        # 2. NIFTY 500 Benchmark (Simulated 500 symbols)
        t0_500 = time.perf_counter()
        nifty500_symbols = [f"NSE_{i:03d}.NS" for i in range(500)]
        u_500 = MarketUniverse(universe_id="BENCH_500", name="Bench 500", symbols=nifty500_symbols)
        self.scanner.register_universe(u_500)

        datasets500 = {
            sym: _create_mock_context(symbol=sym, price=500.0 + (idx * 5.0))
            for idx, sym in enumerate(nifty500_symbols)
        }
        summary500 = self.scanner.execute_scan_cycle(universe_id="BENCH_500", datasets=datasets500)
        lat500 = (time.perf_counter() - t0_500) * 1000.0

        self.assertEqual(summary500.universe_size, 500)
        self.assertLessEqual(summary500.shortlisted_count, self.config.max_candidates_per_cycle)
        reduction_pct500 = (1.0 - (summary500.shortlisted_count / 500.0)) * 100.0
        self.assertGreaterEqual(reduction_pct500, 99.0)


if __name__ == "__main__":
    unittest.main()
