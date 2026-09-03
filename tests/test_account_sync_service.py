"""
Phase 27 — Dedicated Unit Tests for Account Synchronization Service
"""

import unittest
from unittest.mock import MagicMock

from backend.domain.broker_schemas import (
    BrokerAccountState,
    BrokerPosition,
)
from backend.execution.account_sync_service import (
    AccountSyncService,
    global_account_sync_service,
)


class TestAccountSyncServiceDetailed(unittest.TestCase):

    def setUp(self):
        self.service = AccountSyncService(interval_seconds=60)

    def tearDown(self):
        self.service.stop()

    def test_run_once_syncs_and_caches_state(self):
        mock_adapter = MagicMock()
        mock_adapter.get_account_state.return_value = BrokerAccountState(
            account_id="DHAN_TEST_001",
            broker_name="DhanBroker",
            mode="LIVE",
            is_live=True,
            cash=125000.0,
            buying_power=125000.0,
            total_equity=125000.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            positions={},
            open_positions_count=0,
        )
        mock_adapter.get_positions.return_value = {
            "RELIANCE": BrokerPosition(
                symbol="RELIANCE",
                quantity=10,
                average_entry_price=2800.0,
                current_price=2850.0,
                market_value=28500.0,
                realized_pnl=0.0,
                unrealized_pnl=500.0,
            )
        }
        mock_adapter.get_holdings.return_value = [{"tradingSymbol": "TCS", "totalQty": 15}]

        report = self.service.run_once(adapter=mock_adapter)
        self.assertTrue(report["success"])
        self.assertEqual(report["cash"], 125000.0)
        self.assertEqual(report["positions_count"], 1)

        cached_acct = self.service.get_cached_account()
        self.assertIsNotNone(cached_acct)
        self.assertEqual(cached_acct.cash, 125000.0)

        cached_pos = self.service.get_cached_positions()
        self.assertIn("RELIANCE", cached_pos)
        self.assertEqual(cached_pos["RELIANCE"].quantity, 10)

        cached_holdings = self.service.get_cached_holdings()
        self.assertEqual(len(cached_holdings), 1)

    def test_run_once_sync_failure_preserves_safety(self):
        mock_adapter = MagicMock()
        mock_adapter.get_account_state.side_effect = RuntimeError("DHAN_UNAVAILABLE")

        report = self.service.run_once(adapter=mock_adapter)
        self.assertFalse(report["success"])
        self.assertIn("error", report)

    def test_start_stop_lifecycle(self):
        self.assertFalse(self.service.get_status()["is_running"])
        self.service.start()
        self.assertTrue(self.service.get_status()["is_running"])
        self.service.stop()
        self.assertFalse(self.service.get_status()["is_running"])


if __name__ == "__main__":
    unittest.main()
