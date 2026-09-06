import pytest
from unittest.mock import patch, MagicMock
from backend.adapters.upstox_ws_client import UpstoxWebSocketClient

def test_upstox_ws_on_close_signature():
    # Verify that the _on_close callback takes 2 parameters after self
    # which matches the Upstox Streamer handle_close signature
    client = UpstoxWebSocketClient("test_token")
    
    # Must not raise an exception
    client._on_close(1000, "Normal Closure")
    assert client.status == "DISCONNECTED"

def test_upstox_ws_on_error():
    client = UpstoxWebSocketClient("test_token")
    client._on_error("Test Error")
    assert client.status == "ERROR"

@patch('backend.adapters.upstox_ws_client.logger')
def test_upstox_ws_no_token_leak(mock_logger):
    # Ensure token is never printed in standard logging flows
    client = UpstoxWebSocketClient("SECRET_TOKEN_DO_NOT_LEAK")
    client._on_close(403, "Forbidden")
    client._on_error("Auth Error")
    
    for call in mock_logger.warning.call_args_list:
        assert "SECRET_TOKEN_DO_NOT_LEAK" not in str(call)
        
    for call in mock_logger.error.call_args_list:
        assert "SECRET_TOKEN_DO_NOT_LEAK" not in str(call)

def test_upstox_setup_streamer_config():
    client = UpstoxWebSocketClient("test_token_123")
    client._setup_streamer()
    
    assert client._streamer is not None
    # Verify token is pushed down to streamer configuration
    assert client._streamer.api_client.configuration.access_token == "test_token_123"
