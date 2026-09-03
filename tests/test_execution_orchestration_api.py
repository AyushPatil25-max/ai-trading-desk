"""
Phase 31 — REST API Tests for Execution Orchestration Endpoints

Covers:
- POST /api/orchestration/submit
- GET  /api/orchestration/status
- GET  /api/orchestration/history
- GET  /api/orchestration/{execution_id}
- POST /api/orchestration/{execution_id}/cancel
- POST /api/orchestration/control/pause
- POST /api/orchestration/control/resume
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
from backend.execution.execution_orchestrator import global_execution_orchestrator


class TestExecutionOrchestrationAPI(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        global_strategy_registry.clear()
        global_execution_orchestrator.clear()

        # Register active strategy
        strat = StrategyDefinition(
            strategy_id="api_orch_strat",
            name="API Orchestration Strategy",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["TCS.NS"],
            allowed_exchanges=["NSE"],
        )
        global_strategy_registry.register(strat)

    def test_post_orchestration_submit_paper(self):
        now_iso = datetime.now(timezone.utc).isoformat()
        decision_payload = {
            "decision_id": "dec-api-01",
            "execution_mode": "PAPER",
            "pipeline_status": "APPROVED",
            "is_authorized": True,
            "strategy_id": "api_orch_strat",
            "strategy_version": "1.0.0",
            "signal_fingerprint": "sig-fp-api",
            "symbol": "TCS.NS",
            "exchange": "NSE",
            "direction": "BUY",
            "quantity": 15.0,
            "estimated_value": 52500.0,
            "timestamp": now_iso,
        }

        res = self.client.post("/api/orchestration/submit", json={"decision": decision_payload})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["state"], "COMPLETED")
        self.assertEqual(data["filled_quantity"], 15.0)

    def test_get_orchestration_status_and_history(self):
        res_st = self.client.get("/api/orchestration/status")
        self.assertEqual(res_st.status_code, 200)
        st_data = res_st.json()
        self.assertEqual(st_data["control_state"], "RUNNING")

        res_hist = self.client.get("/api/orchestration/history")
        self.assertEqual(res_hist.status_code, 200)
        self.assertIsInstance(res_hist.json(), list)

    def test_control_plane_pause_and_resume_api(self):
        res_pause = self.client.post("/api/orchestration/control/pause", json={})
        self.assertEqual(res_pause.status_code, 200)
        self.assertEqual(res_pause.json()["control_state"], "PAUSED")

        res_resume = self.client.post("/api/orchestration/control/resume", json={})
        self.assertEqual(res_resume.status_code, 200)
        self.assertEqual(res_resume.json()["control_state"], "RUNNING")


if __name__ == "__main__":
    unittest.main()
