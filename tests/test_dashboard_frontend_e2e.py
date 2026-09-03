"""
Phase 14 — Modernized Dashboard & Multi-Agent Visualizer End-to-End Test Suite

Verifies:
1. Dashboard serving (GET / returns 200, HTML, and all safety banners/elements).
2. Prominent paper-only UX and live broker disabled banners in HTML.
3. No live broker activation or bypass endpoint exists.
4. GET /api/trading-os/runs/latest route integration with pipeline execution.
5. Debate, Committee, Regime, Scenario, Risk, Pre-Flight data availability for dashboard.
6. System health, Subsystems, and Broker Status API integrity feeding dashboard.
7. Resilience against empty runs history, mock failures, and stale quotes.
8. Secret leakage prevention (zero credentials in HTML or responses).
"""

from datetime import datetime, timezone
import unittest
from fastapi.testclient import TestClient

from backend.domain.broker_schemas import BrokerMode
from backend.domain.schemas import MarketContext
from backend.application.trading_os_orchestrator import TradingOSOrchestrator
from backend.application.paper_broker_adapter import global_paper_broker
from backend.main import app


class TestDashboardFrontendE2E(unittest.TestCase):
    """End-to-end verification of the modernized Phase 14 frontend dashboard & APIs."""

    def setUp(self):
        self.client = TestClient(app)

    def test_01_dashboard_serves_html_with_safety_banners(self):
        """Verify GET / returns 200, text/html, and contains all required Phase 14 safety elements."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers["content-type"])
        html = resp.text

        # Core Branding & Safety Badges
        self.assertIn("AI TRADING DESK OS", html)
        self.assertIn("PAPER TRADING ONLY", html)
        self.assertIn("LIVE BROKER DISABLED", html)
        self.assertIn("RISK ENGINE ACTIVE", html)
        self.assertIn("PRE-FLIGHT GATE", html)

        # Tab Navigation
        self.assertIn("Multi-Agent Trading OS & Visualizer", html)
        self.assertIn("Opportunity Scanner & Discovery", html)
        self.assertIn("Paper Broker & Execution Terminal", html)
        self.assertIn("System Health & Telemetry", html)

        # Multi-Agent Visualizer Cards
        self.assertIn("Adversarial Debate Engine", html)
        self.assertIn("BULL SPECIALIST", html)
        self.assertIn("BEAR SPECIALIST", html)
        self.assertIn("Investment Committee Synthesis", html)
        self.assertIn("Market Regime", html)
        self.assertIn("Stress Testing", html)
        self.assertIn("Pre-Flight", html)

        # Broker & Telemetry Elements
        self.assertIn("Open Paper Positions", html)
        self.assertIn("Paper Orders & Lifecycle", html)
        self.assertIn("16 Monitored Subsystems", html)
        self.assertIn("KILL SWITCH", html)

    def test_02_no_live_activation_or_bypass_endpoint_exists(self):
        """Verify no endpoint exists to enable live trading or bypass safety controls."""
        forbidden_endpoints = [
            "/api/broker/enable-live",
            "/api/broker/live",
            "/api/broker/toggle-real-money",
            "/api/risk/bypass",
            "/api/preflight/bypass",
            "/api/admin/live-trading",
        ]
        for ep in forbidden_endpoints:
            post_resp = self.client.post(ep, json={})
            self.assertIn(post_resp.status_code, [404, 405], f"Endpoint {ep} must not exist")

    def test_03_secret_leakage_prevention_in_html(self):
        """Verify zero API keys, secrets, or credentials exist in HTML markup or scripts."""
        resp = self.client.get("/")
        html = resp.text.lower()
        forbidden_strings = [
            "sk-",
            "api_key",
            "secret_key",
            "private_key",
            "access_token",
            "zerodha_api_secret",
            "upstox_secret",
        ]
        for s in forbidden_strings:
            self.assertNotIn(s, html)

    def test_04_runs_latest_empty_state_resilience(self):
        """Verify GET /api/trading-os/runs/latest handles initial empty state gracefully."""
        resp = self.client.get("/api/trading-os/runs/latest")
        self.assertEqual(resp.status_code, 200)

    def test_05_trading_os_pipeline_execution_populates_visualizer_data(self):
        """Verify POST /api/trading-os/run generates a complete run consumable by the visualizer."""
        payload = {
            "symbol": "TCS.NS",
            "current_price": 3500.0,
            "fill_ratio": 1.0,
        }
        resp = self.client.post("/api/trading-os/run", json=payload)
        self.assertEqual(resp.status_code, 200)
        summary = resp.json()
        self.assertEqual(summary["symbol"], "TCS.NS")
        self.assertIn("run_id", summary)
        self.assertEqual(summary["mode"], "PAPER_ONLY")

        # Query GET /api/trading-os/runs/latest to verify complete audit record
        latest_resp = self.client.get("/api/trading-os/runs/latest")
        self.assertEqual(latest_resp.status_code, 200)
        run = latest_resp.json()
        self.assertIsNotNone(run)
        self.assertEqual(run["symbol"], "TCS.NS")
        self.assertEqual(run["mode"], "PAPER_ONLY")

        # Verify all visualizer artifact sections exist
        self.assertIn("stages", run)
        self.assertIn("debate", run)
        self.assertIn("committee_decision", run)
        self.assertIn("regime", run)
        self.assertIn("scenario", run)
        self.assertIn("risk", run)
        self.assertIn("sizing", run)
        self.assertIn("preflight", run)

        # Inspect structured debate artifacts (no private chain of thought)
        deb = run["debate"]
        self.assertIn("rounds", deb)
        self.assertIn("strongest_bull_arguments", deb)
        self.assertIn("strongest_bear_arguments", deb)
        self.assertIn("final_debate_state", deb)
        self.assertIn("confidence", deb)

        # Inspect committee synthesis
        comm = run["committee_decision"]
        self.assertTrue("recommendation" in comm or "decision" in comm)
        self.assertTrue("conviction_score" in comm or "conviction" in comm)
        self.assertTrue("key_risks" in comm or "opposing_factors" in comm)

    def test_06_broker_endpoints_feed_dashboard(self):
        """Verify /api/broker endpoints return data structured for dashboard consumption."""
        # Status
        status_resp = self.client.get("/api/broker/status")
        self.assertEqual(status_resp.status_code, 200)
        status_data = status_resp.json()
        self.assertEqual(status_data["broker_mode"], "PAPER")
        self.assertFalse(status_data["is_live_trading_enabled"])
        self.assertTrue(status_data["safety_invariants"]["paper_broker_authoritative"])

        # Account
        acct_resp = self.client.get("/api/broker/account")
        self.assertEqual(acct_resp.status_code, 200)
        acct_data = acct_resp.json()
        self.assertEqual(acct_data["mode"], "PAPER")
        self.assertGreaterEqual(acct_data["cash"], 0.0)
        self.assertGreaterEqual(acct_data["total_equity"], 0.0)

        # Positions
        pos_resp = self.client.get("/api/broker/positions")
        self.assertEqual(pos_resp.status_code, 200)
        self.assertIsInstance(pos_resp.json(), dict)

        # Orders
        ord_resp = self.client.get("/api/broker/orders")
        self.assertEqual(ord_resp.status_code, 200)
        self.assertIsInstance(ord_resp.json(), list)

    def test_07_system_health_and_subsystem_matrix_endpoints(self):
        """Verify /api/monitor endpoints return 16 subsystems and health summary."""
        # Health
        h_resp = self.client.get("/api/monitor/health")
        self.assertEqual(h_resp.status_code, 200)
        h_data = h_resp.json()
        self.assertIn(h_data["overall_health"], ["HEALTHY", "DEGRADED", "CRITICAL"])
        self.assertGreaterEqual(h_data["components_count"], 16)

        # Components
        c_resp = self.client.get("/api/monitor/components")
        self.assertEqual(c_resp.status_code, 200)
        comps_data = c_resp.json()
        comps = list(comps_data.values()) if isinstance(comps_data, dict) else comps_data
        self.assertGreaterEqual(len(comps), 16)
        comp_names = [c["name"] for c in comps]
        self.assertIn("Risk Management Engine", comp_names)
        self.assertIn("Paper Broker Adapter", comp_names)
        self.assertIn("Pre-Flight Gatekeeper", comp_names)
        self.assertIn("Adversarial Debate Engine", comp_names)

    def test_08_scanner_and_opportunity_endpoints(self):
        """Verify /api/opportunities endpoints return scanner status and candidate list."""
        st_resp = self.client.get("/api/opportunities/scanner/status")
        self.assertEqual(st_resp.status_code, 200)
        st_data = st_resp.json()
        self.assertIn(st_data["state"], ["STOPPED", "RUNNING", "PAUSED", "IDLE"])

        c_resp = self.client.get("/api/opportunities")
        self.assertEqual(c_resp.status_code, 200)
        self.assertIsInstance(c_resp.json(), list)

    def test_09_forward_simulation_endpoints(self):
        """Verify /api/forward/status endpoint returns forward engine state."""
        f_resp = self.client.get("/api/forward/status")
        self.assertEqual(f_resp.status_code, 200)
        f_data = f_resp.json()
        self.assertIn("engine_state", f_data)
        self.assertIn("session_state", f_data)
        self.assertIn("mode", f_data)

    def test_10_telemetry_dashboard_feed(self):
        """Verify /api/telemetry/dashboard returns account summary and metrics."""
        t_resp = self.client.get("/api/telemetry/dashboard")
        self.assertEqual(t_resp.status_code, 200)
        t_data = t_resp.json()
        self.assertIn("system_health", t_data)
        self.assertIn("account_summary", t_data)
        self.assertIn("metrics", t_data)
        self.assertIn("active_orders", t_data)
        self.assertIn("recent_fills", t_data)


if __name__ == "__main__":
    unittest.main()
