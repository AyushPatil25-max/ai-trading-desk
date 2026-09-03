import os
import unittest
from unittest.mock import patch, MagicMock
import urllib.error
from datetime import datetime, timezone
from backend.adapters.dhan_adapter import DhanBrokerAdapter, DhanHTTPClient
from backend.domain.broker_schemas import BrokerMode, BrokerConnectionState
from backend.application.broker_interface import LiveBrokerDisabledError
from backend.domain.preflight_schemas import ExecutionAuthorizationSnapshot

class TestDhanBrokerAdapter(unittest.TestCase):
    def setUp(self):
        # Default env for most tests
        os.environ["DHAN_ENABLED"] = "true"
        os.environ["DHAN_CLIENT_ID"] = "test_client"
        os.environ["DHAN_ACCESS_TOKEN"] = "secret"
        os.environ["DHAN_STATIC_IP_CONFIGURED"] = "true"
        os.environ["LIVE_EXECUTION_ENABLED"] = "false"

    @patch("backend.adapters.dhan_adapter.urllib.request.urlopen")
    def test_dhan_connection_connected(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"clientId": "test_client"}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        adapter = DhanBrokerAdapter()
        self.assertEqual(adapter.get_connection_state(), BrokerConnectionState.DHAN_CONNECTED)

    @patch("backend.adapters.dhan_adapter.urllib.request.urlopen")
    def test_dhan_connection_auth_failed(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)
        adapter = DhanBrokerAdapter()
        self.assertEqual(adapter.get_connection_state(), BrokerConnectionState.DHAN_AUTH_FAILED)

    def test_dhan_disabled(self):
        os.environ["DHAN_ENABLED"] = "false"
        adapter = DhanBrokerAdapter()
        self.assertEqual(adapter.get_connection_state(), BrokerConnectionState.DHAN_DISABLED)

    def test_dhan_missing_credentials(self):
        os.environ["DHAN_ACCESS_TOKEN"] = ""
        adapter = DhanBrokerAdapter()
        self.assertEqual(adapter.get_connection_state(), BrokerConnectionState.DISCONNECTED)

    @patch("backend.adapters.dhan_adapter.urllib.request.urlopen")
    def test_account_funds(self, mock_urlopen):
        mock_response_profile = MagicMock()
        mock_response_profile.read.return_value = b'{"clientId": "test_client"}'
        mock_urlopen.return_value.__enter__.return_value = mock_response_profile
        adapter = DhanBrokerAdapter()

        mock_response_funds = MagicMock()
        mock_response_funds.read.return_value = b'{"availabelBalance": 50000.0}'
        mock_urlopen.return_value.__enter__.return_value = mock_response_funds

        state = adapter.get_account_state()
        self.assertEqual(state.cash, 50000.0)
        self.assertEqual(state.buying_power, 50000.0)

    @patch("backend.adapters.dhan_adapter.urllib.request.urlopen")
    def test_positions(self, mock_urlopen):
        mock_response_profile = MagicMock()
        mock_response_profile.read.return_value = b'{}'
        mock_urlopen.return_value.__enter__.return_value = mock_response_profile
        adapter = DhanBrokerAdapter()

        mock_response_pos = MagicMock()
        mock_response_pos.read.return_value = b'{"data": [{"tradingSymbol": "TCS", "netQty": 10, "costPrice": 3500.0}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_response_pos

        pos = adapter.get_positions()
        self.assertIn("TCS", pos)
        self.assertEqual(pos["TCS"].quantity, 10)
        self.assertEqual(pos["TCS"].average_entry_price, 3500.0)

    @patch("backend.adapters.dhan_adapter.urllib.request.urlopen")
    def test_order_book(self, mock_urlopen):
        mock_response_profile = MagicMock()
        mock_response_profile.read.return_value = b'{}'
        mock_urlopen.return_value.__enter__.return_value = mock_response_profile
        adapter = DhanBrokerAdapter()

        mock_response_orders = MagicMock()
        mock_response_orders.read.return_value = b'{"data": [{"orderId": "123"}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_response_orders

        orders = adapter.get_order_book()
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["orderId"], "123")

    def test_fail_closed_on_live_execution(self):
        adapter = DhanBrokerAdapter()
        auth = ExecutionAuthorizationSnapshot(
            authorization_id="test",
            decision_id="test",
            symbol="TCS.NS",
            decision_state="APPROVE",
            rejection_reasons=[],
            authorized_at=datetime.now(timezone.utc),
            order_id="test",
            side="BUY",
            approved_quantity=10,
            validation_timestamp=datetime.now(timezone.utc),
            idempotency_token="token"
        )
        
        with self.assertRaises(LiveBrokerDisabledError):
            adapter.submit_order(authorization=auth)

if __name__ == "__main__":
    unittest.main()
