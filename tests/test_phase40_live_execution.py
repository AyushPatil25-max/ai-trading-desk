import unittest
from datetime import datetime, timezone
from backend.domain.preflight_schemas import ExecutionAuthorizationSnapshot, PreflightSide
from backend.domain.broker_schemas import NormalizedOrderStatus
from backend.execution.dhan_live_execution_engine import DhanLiveExecutionEngine

class TestPhase40LiveExecution(unittest.TestCase):
    def test_legacy_engine_is_permanently_blocked_in_phase_42(self):
        engine = DhanLiveExecutionEngine(None)
        auth = ExecutionAuthorizationSnapshot(
            authorization_id="auth-123",
            decision_id="dec-123",
            order_id="ord-123",
            symbol="RELIANCE.NS",
            side=PreflightSide.BUY,
            approved_quantity=10,
            normalized_limit_price=2500.50,
            validation_timestamp=datetime.now(timezone.utc),
            idempotency_token="idem-123"
        )
        res = engine.execute_live_order(auth, "any-token")
        self.assertEqual(res.status, NormalizedOrderStatus.REJECTED)
        self.assertIn("LIVE_EXECUTION_DISABLED", res.message)
