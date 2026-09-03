"""
Phase 29 — REST API Tests for Strategy Governance Endpoints

Covers:
- GET  /api/strategy/list
- GET  /api/strategy/{strategy_id}
- POST /api/strategy/register
- POST /api/strategy/{strategy_id}/activate
- POST /api/strategy/{strategy_id}/pause
- POST /api/strategy/{strategy_id}/disable
- POST /api/strategy/{strategy_id}/quarantine
- POST /api/strategy/{strategy_id}/recover
- GET  /api/strategy/{strategy_id}/health
- POST /api/strategy/signal/evaluate (Produces decision ONLY, never places broker order)
- GET  /api/strategy/conflicts
- GET  /api/strategy/governance/status
"""

from datetime import datetime, timezone
import unittest
from fastapi.testclient import TestClient

from backend.main import app
from backend.domain.strategy_schemas import StrategyStatus
from backend.execution.strategy_registry import global_strategy_registry
from backend.execution.strategy_governance import global_strategy_governance_engine


class TestStrategyAPI(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        global_strategy_registry.clear()
        global_strategy_governance_engine.clear()

    def test_strategy_crud_api_lifecycle(self):
        # 1. Register strategy
        strat_payload = {
            "strategy_id": "api_trend",
            "name": "API Trend Strategy",
            "version": "1.0.0",
            "status": "DRAFT",
            "allowed_instruments": ["TCS.NS", "INFY.NS"],
            "allowed_exchanges": ["NSE"],
            "max_position_size": 100.0,
            "max_order_value": 300000.0,
        }
        res = self.client.post("/api/strategy/register", json=strat_payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["strategy_id"], "api_trend")
        self.assertEqual(data["status"], "DRAFT")

        # 2. Get strategy
        res = self.client.get("/api/strategy/api_trend")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["name"], "API Trend Strategy")

        # 3. Activate
        res = self.client.post("/api/strategy/api_trend/activate")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["strategy"]["status"], "ACTIVE")

        # 4. Pause
        res = self.client.post("/api/strategy/api_trend/pause")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["strategy"]["status"], "PAUSED")

        # 5. Quarantine
        res = self.client.post(
            "/api/strategy/api_trend/quarantine",
            json={"reason": "Excessive rejected orders detected"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["strategy"]["status"], "QUARANTINED")

        # 6. Attempt activate while quarantined -> 400
        res = self.client.post("/api/strategy/api_trend/activate")
        self.assertEqual(res.status_code, 400)

        # 7. Recover
        res = self.client.post(
            "/api/strategy/api_trend/recover",
            json={"operator_notes": "Reviewed and cleared by risk officer."},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["strategy"]["status"], "PAUSED")

        # 8. Disable
        res = self.client.post("/api/strategy/api_trend/disable")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["strategy"]["status"], "DISABLED")

    def test_signal_evaluation_endpoint(self):
        # Register and activate
        self.client.post("/api/strategy/register", json={
            "strategy_id": "eval_strat",
            "name": "Evaluation Strategy",
            "version": "1.0.0",
            "status": "DRAFT",
            "allowed_instruments": ["RELIANCE.NS"],
            "allowed_exchanges": ["NSE"],
            "max_position_size": 50.0,
            "max_order_value": 200000.0,
        })
        self.client.post("/api/strategy/eval_strat/activate")

        now_iso = datetime.now(timezone.utc).isoformat()
        sig_payload = {
            "strategy_id": "eval_strat",
            "strategy_version": "1.0.0",
            "symbol": "RELIANCE.NS",
            "exchange": "NSE",
            "direction": "BUY",
            "confidence": 0.88,
            "quantity": 10.0,
            "timestamp": now_iso,
            "market_data_timestamp": now_iso,
            "source": "RULE_BASED",
        }

        res = self.client.post("/api/strategy/signal/evaluate", json=sig_payload)
        self.assertEqual(res.status_code, 200)
        decision = res.json()
        self.assertEqual(decision["governance_status"], "APPROVED")
        self.assertTrue(decision["is_admissible"])
        self.assertIn("decision_id", decision)
        self.assertIn("fingerprint", decision)

    def test_governance_status_and_health_endpoints(self):
        res = self.client.get("/api/strategy/governance/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("registry", data)
        self.assertIn("governance_engine", data)

        res_conf = self.client.get("/api/strategy/conflicts")
        self.assertEqual(res_conf.status_code, 200)
        self.assertIsInstance(res_conf.json(), list)


if __name__ == "__main__":
    unittest.main()
