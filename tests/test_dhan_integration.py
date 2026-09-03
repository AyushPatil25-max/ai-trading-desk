import os
import unittest
from unittest.mock import patch, MagicMock

from backend.application.broker_interface import BrokerFactory, ConfigurationSafetyError, LiveBrokerDisabledError
from backend.adapters.dhan_adapter import DhanBrokerAdapter
from backend.application.paper_broker_adapter import PaperBrokerAdapter
from backend.application.sandbox_broker_adapter import SandboxBrokerAdapter
from backend.domain.broker_schemas import BrokerConnectionState
from backend.config.app_config import AppConfig
from backend.domain.preflight_schemas import ExecutionAuthorizationSnapshot
from backend.domain.schemas import MarketContext
from datetime import datetime, timezone

class TestDhanIntegration(unittest.TestCase):
    @patch.dict(os.environ, {"BROKER_MODE": "paper"}, clear=True)
    def test_broker_mode_paper(self):
        adapter = BrokerFactory.get_adapter()
        self.assertIsInstance(adapter, PaperBrokerAdapter)

    @patch.dict(os.environ, {"BROKER_MODE": "sandbox"}, clear=True)
    def test_broker_mode_sandbox(self):
        adapter = BrokerFactory.get_adapter()
        self.assertIsInstance(adapter, SandboxBrokerAdapter)

    @patch.dict(os.environ, {"BROKER_MODE": "dhan"}, clear=True)
    @patch("backend.adapters.dhan_adapter.get_app_config")
    def test_broker_mode_dhan(self, mock_config):
        mock_config.return_value = AppConfig(
            dhan_enabled=True, dhan_client_id="TEST", dhan_access_token="TESTTOKEN"
        )
        adapter = BrokerFactory.get_adapter()
        self.assertIsInstance(adapter, DhanBrokerAdapter)

    @patch.dict(os.environ, {"BROKER_MODE": "live"}, clear=True)
    def test_broker_mode_live_rejected(self):
        with self.assertRaises(ConfigurationSafetyError):
            BrokerFactory.get_adapter()

    @patch.dict(os.environ, {"BROKER_MODE": "real"}, clear=True)
    def test_broker_mode_real_rejected(self):
        with self.assertRaises(ConfigurationSafetyError):
            BrokerFactory.get_adapter()

    @patch.dict(os.environ, {"BROKER_MODE": "zerodha"}, clear=True)
    def test_broker_mode_zerodha_rejected(self):
        with self.assertRaises(ConfigurationSafetyError):
            BrokerFactory.get_adapter()

    @patch.dict(os.environ, {"BROKER_MODE": "dhan"}, clear=True)
    @patch("backend.adapters.dhan_adapter.get_app_config")
    def test_missing_dhan_credentials(self, mock_config):
        mock_config.return_value = AppConfig(
            dhan_enabled=True, dhan_client_id="", dhan_access_token=""
        )
        adapter = BrokerFactory.get_adapter()
        self.assertEqual(adapter.get_connection_state(), BrokerConnectionState.DISCONNECTED)

    @patch.dict(os.environ, {"BROKER_MODE": "dhan"}, clear=True)
    @patch("backend.adapters.dhan_adapter.urllib.request.urlopen")
    @patch("backend.adapters.dhan_adapter.get_app_config")
    def test_invalid_dhan_token(self, mock_config, mock_urlopen):
        mock_config.return_value = AppConfig(
            dhan_enabled=True, dhan_client_id="CLIENT", dhan_access_token="BADTOKEN"
        )
        from urllib.error import HTTPError
        mock_urlopen.side_effect = HTTPError("url", 401, "Unauthorized", {}, None)
        
        adapter = BrokerFactory.get_adapter()
        self.assertEqual(adapter.get_connection_state(), BrokerConnectionState.DHAN_AUTH_FAILED)

    @patch.dict(os.environ, {"BROKER_MODE": "dhan"}, clear=True)
    @patch("backend.adapters.dhan_adapter.urllib.request.urlopen")
    @patch("backend.adapters.dhan_adapter.get_app_config")
    def test_valid_dhan_profile(self, mock_config, mock_urlopen):
        mock_config.return_value = AppConfig(
            dhan_enabled=True, dhan_client_id="CLIENT", dhan_access_token="GOODTOKEN"
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"clientId": "CLIENT", "name": "Test User"}'
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp
        
        adapter = BrokerFactory.get_adapter()
        self.assertEqual(adapter.get_connection_state(), BrokerConnectionState.DHAN_CONNECTED)

    @patch.dict(os.environ, {"BROKER_MODE": "dhan"}, clear=True)
    @patch("backend.adapters.dhan_adapter.get_app_config")
    def test_live_execution_rejected_when_false(self, mock_config):
        mock_config.return_value = AppConfig(
            dhan_enabled=True, dhan_client_id="CLIENT", dhan_access_token="GOODTOKEN", live_execution_enabled=False
        )
        adapter = BrokerFactory.get_adapter()
        auth = MagicMock(spec=ExecutionAuthorizationSnapshot)
        with self.assertRaises(LiveBrokerDisabledError):
            adapter.submit_order(authorization=auth)
