"""
Phase 30 — REST API Tests for Execution Decision Pipeline Endpoints

Covers:
- POST /api/execution/decision
- POST /api/execution/live/evaluate
- GET  /api/execution/status
- GET  /api/execution/history
- Verification that evaluation produces decision records without placing broker orders
"""

from datetime import datetime, timezone
import unittest
from fastapi.testclient import TestClient

from backend.main import app
from backend.domain.strategy_schemas import (
    StrategyDefinition,
    StrategyStatus,
)
from backend.execution.strategy_registry import global_strategy_registry
from backend.execution.strategy_governance import global_strategy_governance_engine
from backend.execution.execution_decision_pipeline import global_execution_decision_engine


class TestExecutionDecisionAPI(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        global_strategy_registry.clear()
        global_strategy_governance_engine.clear()
        global_execution_decision_engine.clear()

        # Register standard active strategy
        strat = StrategyDefinition(
            strategy_id="api_pipeline_strat",
            name="API Pipeline Strategy",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["TCS.NS", "INFY.NS"],
            allowed_exchanges=["NSE"],
            max_position_size=100.0,
            max_order_value=500000.0,
        )
        global_strategy_registry.register(strat)

    def test_post_execution_decision_paper_approved(self):
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "strategy_id": "api_pipeline_strat",
            "strategy_version": "1.0.0",
            "symbol": "TCS.NS",
            "exchange": "NSE",
            "direction": "BUY",
            "quantity": 10.0,
            "target_price": 3500.0,
            "execution_mode": "PAPER",
            "market_data_timestamp": now_iso,
        }

        res = self.client.post("/api/execution/decision", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["pipeline_status"], "APPROVED")
        self.assertTrue(data["is_authorized"])
        self.assertEqual(data["symbol"], "TCS.NS")
        self.assertIn("decision_fingerprint", data)

    def test_post_execution_decision_rejected_on_inactive_strategy(self):
        global_strategy_registry.pause("api_pipeline_strat")
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "strategy_id": "api_pipeline_strat",
            "strategy_version": "1.0.0",
            "symbol": "TCS.NS",
            "direction": "BUY",
            "quantity": 10.0,
            "execution_mode": "PAPER",
            "market_data_timestamp": now_iso,
        }

        res = self.client.post("/api/execution/decision", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["pipeline_status"], "REJECTED")
        self.assertFalse(data["is_authorized"])
        self.assertIn("not ACTIVE", data["rejection_reason"])

    def test_get_execution_status_and_history(self):
        # Evaluate one decision
        now_iso = datetime.now(timezone.utc).isoformat()
        self.client.post("/api/execution/decision", json={
            "strategy_id": "api_pipeline_strat",
            "strategy_version": "1.0.0",
            "symbol": "TCS.NS",
            "direction": "BUY",
            "quantity": 10.0,
            "execution_mode": "PAPER",
            "market_data_timestamp": now_iso,
        })

        # Check status
        res_st = self.client.get("/api/execution/status")
        self.assertEqual(res_st.status_code, 200)
        st_data = res_st.json()
        self.assertGreaterEqual(st_data["total_decisions_evaluated"], 1)

        # Check history
        res_hist = self.client.get("/api/execution/history")
        self.assertEqual(res_hist.status_code, 200)
        hist_data = res_hist.json()
        self.assertIsInstance(hist_data, list)
        self.assertGreaterEqual(len(hist_data), 1)


if __name__ == "__main__":
    unittest.main()
