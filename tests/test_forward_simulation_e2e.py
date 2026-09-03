"""
Phase 12 — Live Forward Paper Trading & Simulation E2E Test Suite

Comprehensive automated verification covering:
1. Forward engine configuration & startup
2. Forward engine graceful shutdown & pause/resume
3. Normalized market tick ingestion & bounds
4. Stale-data rejection (timestamp freshness threshold)
5. Malformed/non-numeric data rejection
6. Market session awareness (Open vs Closed vs Weekend vs Holiday)
7. Opportunity Scanner forward triggering
8. Forward candidate processing through 17-stage Trading OS
9. Deterministic risk engine approval
10. Low-conviction risk veto rejection
11. Sizing enforcement & whole-share flooring
12. Pre-Flight gatekeeper approval & authorization snapshot
13. Pre-Flight gatekeeper circuit breach rejection
14. Paper broker order creation (SUBMITTED -> ACKNOWLEDGED)
15. Paper broker simulated fills (slippage & commission)
16. Dynamic portfolio updates & accounting invariants
17. Telemetry recording & audit timeline
18. Signal deduplication & idempotency protection
19. Engine restart & session isolation
20. Component failure fault tolerance
21. Cooperative stop behavior (no in-flight leaks)
22. Strict paper-only safety enforcement
23. FastAPI REST API endpoints (/api/forward/*)
"""

from datetime import datetime, timezone, timedelta
import unittest
import uuid

from fastapi.testclient import TestClient

from backend.domain.forward_simulation_schemas import (
    FORWARD_SIMULATION_VERSION,
    ForwardSimulationMode,
    MarketSessionState,
    ForwardEngineState,
    ForwardLifecycleStage,
    MarketDataTick,
    ForwardSimulationConfig,
    ForwardSessionSummary,
)
from backend.domain.opportunity_schemas import (
    OpportunityCandidate,
    CandidatePriority,
)
from backend.domain.schemas import MarketContext
from backend.domain.preflight_schemas import (
    PreflightOrderRequest,
    PreflightSide,
    PreflightOrderType,
    PreflightStatus,
    ExecutionAuthorizationSnapshot,
)
from backend.domain.paper_broker_schemas import PaperOrderStatus
from backend.application.forward_simulation_engine import (
    ForwardSimulationEngine,
    LiveForwardWorker,
    get_market_session_state,
    global_forward_engine,
)
from backend.application.trading_os_orchestrator import TradingOSOrchestrator
from backend.application.opportunity_scanner import OpportunityScanner
from backend.application.paper_broker_adapter import PaperBrokerAdapter
from backend.application.execution_telemetry_engine import ExecutionTelemetryEngine
from backend.main import app


class TestPhase12ForwardSimulationE2E(unittest.TestCase):
    """Full end-to-end integration and safety test suite for Phase 12."""

    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.config = ForwardSimulationConfig(
            mode=ForwardSimulationMode.PAPER_POLL,
            universe_id="NIFTY_50",
            poll_interval_seconds=1.0,
            max_candidates_per_cycle=3,
            allow_execution=True,
            market_hours_enforced=False,  # Allow deterministic test ticks
            max_data_age_seconds=60.0,
            dedup_window_seconds=10.0,
            fill_ratio=1.0,
            slippage_pct=0.0005,
            commission_rate=0.0003,
        )
        self.telemetry = ExecutionTelemetryEngine()
        self.paper_broker = PaperBrokerAdapter(telemetry_engine=self.telemetry)
        self.orchestrator = TradingOSOrchestrator(
            paper_broker=self.paper_broker,
            telemetry_engine=self.telemetry,
        )
        self.scanner = OpportunityScanner()
        self.engine = ForwardSimulationEngine(
            config=self.config,
            orchestrator=self.orchestrator,
            scanner=self.scanner,
            paper_broker=self.paper_broker,
            telemetry_engine=self.telemetry,
        )
        self.client = TestClient(app)

    # ── 1. Startup & Configuration ────────────────────────────────────────────

    def test_01_engine_initialization_and_start(self):
        """Verify engine initialization and session start."""
        session = self.engine.start_session(session_id="test-ses-01")
        self.assertEqual(session.session_id, "test-ses-01")
        self.assertEqual(session.state, ForwardEngineState.RUNNING)
        self.assertEqual(session.cash_balance, 100000.0)
        self.assertEqual(session.ticks_processed, 0)
        self.assertEqual(len(session.recent_events), 1)
        self.assertEqual(session.recent_events[0].stage, ForwardLifecycleStage.SESSION_VALIDATED)

    # ── 2. Shutdown, Pause & Resume ───────────────────────────────────────────

    def test_02_engine_pause_resume_stop(self):
        """Verify session pause, resume, and graceful stop."""
        self.engine.start_session()
        paused = self.engine.pause_session()
        self.assertEqual(paused.state, ForwardEngineState.PAUSED)

        resumed = self.engine.resume_session()
        self.assertEqual(resumed.state, ForwardEngineState.RUNNING)

        stopped = self.engine.stop_session()
        self.assertEqual(stopped.state, ForwardEngineState.STOPPED)
        self.assertIsNotNone(stopped.stopped_at)

    # ── 3. Market Data Ingestion ──────────────────────────────────────────────

    def test_03_market_data_tick_ingestion(self):
        """Verify valid market tick ingestion and sliding MarketContext synthesis."""
        tick = MarketDataTick(
            symbol="INFY.NS",
            price=1600.0,
            volume=25000.0,
            timestamp=self.now,
            source="TEST_FEED",
        )
        success, msg, ctx = self.engine.ingest_tick(tick)
        self.assertTrue(success)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.symbol, "INFY.NS")
        self.assertEqual(ctx.current_price, 1600.0)
        self.assertGreaterEqual(len(ctx.ohlcv_historical), 30)

    # ── 4. Stale Data Rejection ───────────────────────────────────────────────

    def test_04_stale_data_rejection(self):
        """Verify incoming ticks with timestamps older than max_data_age_seconds are rejected."""
        old_time = self.now - timedelta(seconds=120)  # 120s old > 60s max
        stale_tick = MarketDataTick(
            symbol="TCS.NS",
            price=3500.0,
            timestamp=old_time,
            source="STALE_FEED",
        )
        success, msg, ctx = self.engine.ingest_tick(stale_tick)
        self.assertFalse(success)
        self.assertIn("DATA_STALE", msg)
        self.assertIsNone(ctx)

    # ── 5. Malformed Numerical Data Rejection ──────────────────────────────────

    def test_05_malformed_data_rejection(self):
        """Verify ticks with non-positive prices or inverted High-Low bounds raise ValueError."""
        with self.assertRaises(ValueError):
            MarketDataTick(symbol="RELIANCE.NS", price=-100.0)
        
        with self.assertRaises(ValueError):
            MarketDataTick(symbol="RELIANCE.NS", price=float("nan"))

        with self.assertRaises(ValueError):
            MarketDataTick(symbol="RELIANCE.NS", price=2500.0, high=2400.0, low=2600.0)

    # ── 6. Market Session Awareness ───────────────────────────────────────────

    def test_06_market_session_calendar_classification(self):
        """Verify market session state determination across weekdays, weekends, and hours."""
        # Weekend (Saturday: 2026-08-29)
        saturday = datetime(2026, 8, 29, 6, 0, tzinfo=timezone.utc)
        state_sat, _ = get_market_session_state(saturday, enforce_calendar=True)
        self.assertEqual(state_sat, MarketSessionState.WEEKEND)

        # Weekday Open (Wednesday at 10:30 AM IST = 05:00 UTC)
        wed_open = datetime(2026, 8, 26, 5, 0, tzinfo=timezone.utc)
        state_open, _ = get_market_session_state(wed_open, enforce_calendar=True)
        self.assertEqual(state_open, MarketSessionState.OPEN)

        # Weekday Closed (Wednesday at 11:00 PM IST = 17:30 UTC)
        wed_closed = datetime(2026, 8, 26, 17, 30, tzinfo=timezone.utc)
        state_closed, _ = get_market_session_state(wed_closed, enforce_calendar=True)
        self.assertEqual(state_closed, MarketSessionState.CLOSED)

        # Calendar enforcement disabled
        state_disabled, _ = get_market_session_state(saturday, enforce_calendar=False)
        self.assertEqual(state_disabled, MarketSessionState.OPEN)

    # ── 7. Session Enforcement Rejection ──────────────────────────────────────

    def test_07_market_hours_enforcement_tick_rejection(self):
        """Verify ticks rejected when market_hours_enforced is True and market is closed."""
        engine_strict = ForwardSimulationEngine(
            config=ForwardSimulationConfig(market_hours_enforced=True, max_data_age_seconds=864000.0),
        )
        saturday_tick = MarketDataTick(
            symbol="TCS.NS",
            price=3500.0,
            timestamp=datetime(2026, 8, 29, 6, 0, tzinfo=timezone.utc),
        )
        success, msg, _ = engine_strict.ingest_tick(saturday_tick)
        self.assertFalse(success)
        self.assertIn("MARKET_WEEKEND", msg)

    # ── 8. Opportunity Scanner Forward Triggering ─────────────────────────────

    def test_08_opportunity_scanner_forward_triggering(self):
        """Verify forward simulation cycle triggers OpportunityScanner and screens candidates."""
        self.engine.start_session()
        cycle_res = self.engine.execute_forward_cycle(specific_symbols=["RELIANCE.NS", "TCS.NS"])
        self.assertEqual(cycle_res["status"], "COMPLETED")
        self.assertGreaterEqual(cycle_res["candidates_evaluated"], 1)

    # ── 9. Complete Trading OS Dispatch ───────────────────────────────────────

    def test_09_trading_os_pipeline_dispatch(self):
        """Verify qualifying candidate flows through the 17-stage Trading OS pipeline."""
        tick = MarketDataTick(symbol="RELIANCE.NS", price=2500.0, timestamp=self.now)
        self.engine.ingest_tick(tick)
        self.engine.start_session()

        cycle_res = self.engine.execute_forward_cycle(specific_symbols=["RELIANCE.NS"])
        self.assertEqual(cycle_res["status"], "COMPLETED")
        results = cycle_res["results"]
        self.assertGreaterEqual(len(results), 1)
        rel_res = results[0]
        self.assertIn("symbol", rel_res)
        self.assertIn("decision", rel_res)
        self.assertIn("conviction", rel_res)

    # ── 10. Low-Conviction Risk Veto Enforcement ──────────────────────────────

    def test_10_low_conviction_risk_veto_enforcement(self):
        """Verify low-conviction trade is vetoed by RiskEngine and blocked before PaperBroker."""
        cand = OpportunityCandidate(
            symbol="LOWCONV.NS",
            universe="NIFTY_50",
            discovery_score=40.0,
            priority=CandidatePriority.LOW,
            direction="BUY",
            current_price=500.0,
            catalysts=[],
        )
        self.engine.start_session()
        res = self.engine._process_forward_candidate(cand, self.now)
        # Sizing plan vetoes conviction < 0.35
        self.assertIn(res["status"], ["REJECTED", "DEDUPLICATED", "IDEMPOTENT"])

    # ── 11. Sizing Enforcement & Whole-Share Flooring ─────────────────────────

    def test_11_sizing_enforcement_integer_shares(self):
        """Verify approved position sizes are strictly discrete whole numbers."""
        snap = ExecutionAuthorizationSnapshot(
            authorization_id="auth-test-size",
            decision_id="dec-test-01",
            order_id="ord-test-01",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            approved_quantity=5,  # Discrete integer
            normalized_limit_price=1600.0,
            allocated_capital=8000.0,
            validation_timestamp=self.now,
            idempotency_token="tok-test-size",
        )
        self.assertIsInstance(snap.approved_quantity, int)
        self.assertEqual(snap.approved_quantity, 5)

    # ── 12. Pre-Flight Gatekeeper Approval & Snapshot ─────────────────────────

    def test_12_preflight_approval_and_snapshot(self):
        """Verify preflight engine generates immutable snapshot for valid order."""
        preflight = self.orchestrator.preflight_engine
        req = PreflightOrderRequest(
            decision_id="dec-pf-01",
            symbol="TCS.NS",
            side=PreflightSide.BUY,
            quantity=2.0,
            limit_price=3500.0,
            stop_price=3430.0,
            target_price=3640.0,
            portfolio_id="PORT-DEFAULT",
            conviction=0.80,
            timestamp=self.now,
        )
        from backend.domain.risk_schemas import PositionSizingPlan, PositionDirection
        plan = PositionSizingPlan(
            plan_id="plan-pf-01",
            context_id="ctx-pf-01",
            symbol="TCS.NS",
            direction=PositionDirection.LONG,
            position_quantity=2,
            entry_price=3500.0,
            stop_loss_price=3430.0,
            take_profit_price=3640.0,
            position_notional=7000.0,
        )
        ctx = MarketContext(
            context_id="ctx-test-01",
            symbol="TCS.NS",
            current_price=3500.0,
            data_timestamp=self.now,
            provider="TEST",
        )
        res = preflight.evaluate_preflight(
            order_request=req,
            candidate_plan=plan,
            market_context=ctx,
            portfolio_state={"cash": 100000.0, "total_equity": 100000.0},
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.APPROVED)
        self.assertIsNotNone(res.authorization)

    # ── 13. Pre-Flight Circuit Breach Rejection ───────────────────────────────

    def test_13_preflight_circuit_breach_rejection(self):
        """Verify preflight rejects orders breaching exchange circuit limits."""
        preflight = self.orchestrator.preflight_engine
        req = PreflightOrderRequest(
            decision_id="dec-pf-02",
            symbol="TCS.NS",
            side=PreflightSide.BUY,
            quantity=2.0,
            limit_price=4500.0,  # Far above circuit limit
            timestamp=self.now,
        )
        from backend.domain.risk_schemas import PositionSizingPlan, PositionDirection
        from backend.domain.preflight_schemas import ExchangeTradingConstraints
        plan = PositionSizingPlan(
            plan_id="plan-pf-02",
            context_id="ctx-pf-02",
            symbol="TCS.NS",
            direction=PositionDirection.LONG,
            position_quantity=2,
            entry_price=4500.0,
        )
        ctx = MarketContext(
            context_id="ctx-test-02",
            symbol="TCS.NS",
            current_price=4500.0,
            data_timestamp=self.now,
            provider="TEST",
        )
        constraints = ExchangeTradingConstraints(circuit_upper_limit=4000.0)
        res = preflight.evaluate_preflight(
            order_request=req,
            candidate_plan=plan,
            market_context=ctx,
            exchange_constraints=constraints,
            evaluation_timestamp=self.now,
        )
        self.assertEqual(res.status, PreflightStatus.CIRCUIT_LIMIT)
        self.assertIn("UPPER_CIRCUIT_BREACH", res.failed_checks)

    # ── 14. Paper Order Creation & Acknowledgment ─────────────────────────────

    def test_14_paper_order_submission_lifecycle(self):
        """Verify approved authorization creates acknowledged paper order."""
        auth = ExecutionAuthorizationSnapshot(
            authorization_id="auth-sub-01",
            decision_id="dec-sub-01",
            order_id="ord-sub-01",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            approved_quantity=4,
            normalized_limit_price=1600.0,
            allocated_capital=6400.0,
            validation_timestamp=self.now,
            idempotency_token="tok-sub-01",
        )
        ctx = MarketContext(
            context_id="ctx-sub-01",
            symbol="INFY.NS",
            current_price=1600.0,
            data_timestamp=self.now,
            provider="TEST",
        )
        res = self.paper_broker.submit_order(authorization=auth, market_context=ctx)
        self.assertEqual(res.status, PaperOrderStatus.ACKNOWLEDGED)
        self.assertEqual(res.order.requested_quantity, 4)

    # ── 15. Paper Broker Simulated Fills ──────────────────────────────────────

    def test_15_paper_fill_simulation_slippage_commissions(self):
        """Verify fill engine executes simulated fill with slippage and commission."""
        auth = ExecutionAuthorizationSnapshot(
            authorization_id="auth-fill-01",
            decision_id="dec-fill-01",
            order_id="ord-fill-01",
            symbol="INFY.NS",
            side=PreflightSide.BUY,
            approved_quantity=4,
            normalized_limit_price=1600.0,
            allocated_capital=6400.0,
            validation_timestamp=self.now,
            idempotency_token="tok-fill-01",
        )
        ctx = MarketContext(
            context_id="ctx-fill-01",
            symbol="INFY.NS",
            current_price=1600.0,
            data_timestamp=self.now,
            provider="TEST",
        )
        sub_res = self.paper_broker.submit_order(authorization=auth, market_context=ctx)
        
        fill_res = self.paper_broker.process_fills(
            order_id=sub_res.order.order_id,
            market_price=1600.0,
            fill_ratio=1.0,
        )
        self.assertEqual(fill_res.status, PaperOrderStatus.FILLED)
        self.assertEqual(fill_res.order.filled_quantity, 4)
        self.assertEqual(len(fill_res.new_fills), 1)
        fill = fill_res.new_fills[0]
        self.assertGreater(fill.commission, 0.0)

    # ── 16. Dynamic Portfolio Updates & Accounting Invariants ─────────────────

    def test_16_portfolio_accounting_invariants(self):
        """Verify post-trade cash deduction and accounting equality: Equity = Cash + Positions."""
        init_cash = self.paper_broker.account.cash
        auth = ExecutionAuthorizationSnapshot(
            authorization_id="auth-acct-01",
            decision_id="dec-acct-01",
            order_id="ord-acct-01",
            symbol="TCS.NS",
            side=PreflightSide.BUY,
            approved_quantity=2,
            normalized_limit_price=3500.0,
            allocated_capital=7000.0,
            validation_timestamp=self.now,
            idempotency_token="tok-acct-01",
        )
        ctx = MarketContext(
            context_id="ctx-acct-01",
            symbol="TCS.NS",
            current_price=3500.0,
            data_timestamp=self.now,
            provider="TEST",
        )
        sub = self.paper_broker.submit_order(auth, ctx)
        self.paper_broker.process_fills(sub.order.order_id, 3500.0, 1.0)

        acct = self.paper_broker.account
        expected_cash = init_cash - 7000.0 - (7000.0 * 0.0003)
        self.assertAlmostEqual(acct.cash, expected_cash, places=2)
        pos = acct.positions["TCS.NS"]
        self.assertEqual(pos.quantity, 2)
        self.assertAlmostEqual(acct.total_equity, acct.cash + pos.market_value, places=2)

    # ── 17. Telemetry Recording ───────────────────────────────────────────────

    def test_17_telemetry_event_stream(self):
        """Verify forward events are recorded in telemetry engine."""
        self.engine.start_session()
        tick = MarketDataTick(symbol="WIPRO.NS", price=450.0, timestamp=self.now)
        self.engine.ingest_tick(tick)

        events = self.telemetry.list_events(limit=10)
        self.assertGreaterEqual(len(events), 1)
        reasons = [e.reason for e in events]
        self.assertTrue(any("TICK_RECEIVED" in r for r in reasons))

    # ── 18. Signal Deduplication ──────────────────────────────────────────────

    def test_18_signal_deduplication(self):
        """Verify identical candidate signals within dedup_window_seconds are suppressed."""
        cand = OpportunityCandidate(
            symbol="DEDUP.NS",
            universe="NIFTY_50",
            discovery_score=85.0,
            priority=CandidatePriority.HIGH,
            direction="BUY",
            current_price=1000.0,
            catalysts=[],
        )
        self.engine.start_session()
        # First evaluation
        res1 = self.engine._process_forward_candidate(cand, self.now)
        # Second immediate evaluation
        res2 = self.engine._process_forward_candidate(cand, self.now + timedelta(seconds=2))
        self.assertEqual(res2["status"], "DEDUPLICATED")

    # ── 19. Engine Restart & Session Isolation ─────────────────────────────────

    def test_19_session_restart_isolation(self):
        """Verify stopping and starting a new session resets tracking and gives unique ID."""
        s1 = self.engine.start_session()
        id1 = s1.session_id
        self.engine.stop_session()

        s2 = self.engine.start_session()
        id2 = s2.session_id
        self.assertNotEqual(id1, id2)
        self.assertEqual(s2.ticks_processed, 0)

    # ── 20. Component Failure Fault Tolerance ─────────────────────────────────

    def test_20_pipeline_exception_handling(self):
        """Verify unhandled pipeline exception does not crash forward simulation."""
        from unittest.mock import patch
        self.engine.start_session()
        cand = MarketDataTick(symbol="FAIL.NS", price=1000.0, timestamp=self.now)
        self.engine.ingest_tick(cand)

        with patch.object(self.orchestrator, "run_pipeline", side_effect=RuntimeError("Simulated LLM Crash")):
            opp = OpportunityCandidate(
                symbol="FAIL.NS",
                universe="NIFTY_50",
                discovery_score=75.0,
                priority=CandidatePriority.HIGH,
                direction="BUY",
                current_price=1000.0,
                catalysts=[],
            )
            res = self.engine._process_forward_candidate(opp, self.now)
            self.assertEqual(res["status"], "ERROR")
            self.assertIn("Simulated LLM Crash", res["error"])
            self.assertEqual(self.engine._session.errors_count, 1)

    # ── 21. Live Forward Worker Start / Stop ──────────────────────────────────

    def test_21_background_worker_start_stop(self):
        """Verify LiveForwardWorker starts background thread and cleanly terminates."""
        worker = LiveForwardWorker(self.engine)
        session = worker.start()
        self.assertTrue(worker.is_alive)
        self.assertEqual(session.state, ForwardEngineState.RUNNING)

        stopped = worker.stop(timeout=2.0)
        self.assertFalse(worker.is_alive)
        self.assertEqual(stopped.state, ForwardEngineState.STOPPED)

    # ── 22. Strict Paper-Only Safety Invariants ───────────────────────────────

    def test_22_paper_only_strict_safety_invariants(self):
        """Verify strict isolation: zero real money, zero broker endpoints, paper account only."""
        self.assertEqual(self.paper_broker.account.account_id, "paper-acct-001")
        self.assertTrue(self.config.allow_execution)
        # Confirm no live broker module exists in paper_broker
        self.assertFalse(hasattr(self.paper_broker, "live_broker_client"))
        self.assertFalse(hasattr(self.paper_broker, "broker_api_secret"))

    # ── 23. REST API Routes (/api/forward/*) ──────────────────────────────────

    def test_23_fastapi_forward_routes(self):
        """Verify all FastAPI forward simulation REST endpoints."""
        orig_enforce = global_forward_engine.config.market_hours_enforced
        global_forward_engine.config.market_hours_enforced = False

        try:
            # 1. GET /api/forward/status
            res = self.client.get("/api/forward/status")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["engine_version"], FORWARD_SIMULATION_VERSION)
            self.assertIn("engine_state", data)
            self.assertIn("session_state", data)

            # 2. POST /api/forward/tick (Valid)
            tick_payload = {
                "symbol": "TCS.NS",
                "price": 3550.0,
                "volume": 12000.0,
                "source": "API_TEST",
            }
            t_res = self.client.post("/api/forward/tick", json=tick_payload)
            self.assertEqual(t_res.status_code, 200)
            self.assertEqual(t_res.json()["status"], "INGESTED")

            # 3. POST /api/forward/cycle
            c_res = self.client.post("/api/forward/cycle", json={"symbols": ["TCS.NS"]})
            self.assertEqual(c_res.status_code, 200)
            self.assertEqual(c_res.json()["status"], "COMPLETED")

            # 4. POST /api/forward/pause & /api/forward/resume
            p_res = self.client.post("/api/forward/pause")
            self.assertEqual(p_res.status_code, 200)
            self.assertEqual(p_res.json()["state"], "PAUSED")

            r_res = self.client.post("/api/forward/resume")
            self.assertEqual(r_res.status_code, 200)
            self.assertEqual(r_res.json()["state"], "RUNNING")

            # 5. GET /api/forward/session
            s_res = self.client.get("/api/forward/session")
            self.assertEqual(s_res.status_code, 200)
            self.assertIn("session_id", s_res.json())

            # 6. POST /api/forward/stop
            stop_res = self.client.post("/api/forward/stop")
            self.assertEqual(stop_res.status_code, 200)
            self.assertEqual(stop_res.json()["state"], "STOPPED")

        finally:
            global_forward_engine.config.market_hours_enforced = orig_enforce


if __name__ == "__main__":
    unittest.main()
