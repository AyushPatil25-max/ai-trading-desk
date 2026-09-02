"""
Phase 24 — Tests for Manual Order REST API Routes

Tests the FastAPI endpoints:
- POST /api/broker/order/preview
- POST /api/broker/order/confirm
- GET /api/broker/order/confirmation/{token}
"""

from datetime import datetime, timezone, timedelta
import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.main import app
from backend.application.confirmation_store import global_confirmation_store
from backend.domain.broker_schemas import SafetyReasonCode


class TestManualOrderRoutes(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        self.env_patcher = patch.dict(
            os.environ,
            {
                "DHAN_ENABLED": "true",
                "DHAN_CLIENT_ID": "1100123456",
                "DHAN_ACCESS_TOKEN": "mock_access_token_xyz",
                "LIVE_EXECUTION_ENABLED": "false",
            },
        )
        self.env_patcher.start()
        global_confirmation_store.reset()

    def tearDown(self):
        self.env_patcher.stop()

    def _sample_order_payload(self, **kwargs) -> dict:
        defaults = {
            "symbol": "TATASTEEL",
            "exchange_segment": "NSE",
            "product_type": "CNC",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": 100,
            "price": 150.0,
            "validity": "DAY",
        }
        defaults.update(kwargs)
        return defaults

    def test_preview_order_success(self):
        payload = self._sample_order_payload()
        response = self.client.post("/api/broker/order/preview", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data["safety_result"]["is_approved"])
        self.assertEqual(data["safety_result"]["reason_code"], "VALID")
        self.assertEqual(data["safety_result"]["estimated_order_value"], 15000.0)
        self.assertIsNotNone(data["confirmation_token"])
        self.assertIsNotNone(data["expires_at"])
        self.assertTrue(data["preview"]["is_valid"])
        self.assertEqual(data["preview"]["dhan_payload"]["securityId"], "TATASTEEL")

    def test_preview_order_invalid_quantity(self):
        payload = self._sample_order_payload(quantity=-10)
        response = self.client.post("/api/broker/order/preview", json=payload)
        self.assertEqual(response.status_code, 422)  # Pydantic validation error (gt=0)

    def test_preview_order_missing_price_for_limit(self):
        payload = self._sample_order_payload(order_type="LIMIT", price=None)
        response = self.client.post("/api/broker/order/preview", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["safety_result"]["is_approved"])
        self.assertEqual(data["safety_result"]["reason_code"], SafetyReasonCode.INVALID_PRICE.value)
        self.assertIsNone(data["confirmation_token"])

    def test_confirmation_status_and_consumption_flow(self):
        # 1. Preview and obtain token
        payload = self._sample_order_payload()
        prev_res = self.client.post("/api/broker/order/preview", json=payload)
        self.assertEqual(prev_res.status_code, 200)
        token = prev_res.json()["confirmation_token"]

        # 2. Check confirmation status
        status_res = self.client.get(f"/api/broker/order/confirmation/{token}")
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()
        self.assertEqual(status_data["status"], "ACTIVE")
        self.assertTrue(status_data["is_valid"])
        self.assertEqual(status_data["symbol"], "TATASTEEL")

        # 3. Confirm order
        confirm_payload = {
            "confirmation_token": token,
            "order": payload,
        }
        confirm_res = self.client.post("/api/broker/order/confirm", json=confirm_payload)
        self.assertEqual(confirm_res.status_code, 200)
        confirm_data = confirm_res.json()
        # In Phase 24, fails closed with LIVE_EXECUTION_LOCKED / LIVE_EXECUTION_DISABLED
        self.assertEqual(confirm_data["status"], "REJECTED")

        # 4. Try to reuse token -> should be rejected as CONSUMED / TOKEN_REUSED
        reuse_res = self.client.post("/api/broker/order/confirm", json=confirm_payload)
        self.assertEqual(reuse_res.status_code, 200)
        reuse_data = reuse_res.json()
        self.assertEqual(reuse_data["status"], "REJECTED")
        self.assertEqual(reuse_data["rejection_reason"], "LIVE_EXECUTION_DISABLED")

    def test_confirmation_not_found(self):
        response = self.client.get("/api/broker/order/confirmation/non_existent_token_123")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
