import pytest
import asyncio
import threading
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from backend.adapters.upstox_ws_client import UpstoxWebSocketClient
from backend.application.market_data_gateway import MarketDataGateway
from backend.application.market_data_integrity_engine import MarketDataIntegrityEngine
from backend.domain.market_data_schemas import MarketDataIntegrityState
from backend.application.realtime_stream_server import market_data_health
from backend.config.app_config import AppConfig

@pytest.mark.asyncio
async def test_thread_safe_queue_delivery():
    gateway = MarketDataGateway()
    q = asyncio.Queue()
    gateway.add_listener(q)
    
    def background_task():
        gateway.instrument_to_symbol["NSE_EQ|INE123"] = "TCS"
        msg = {
            "feeds": {
                "NSE_EQ|INE123": {
                    "fullFeed": {
                        "marketFF": {
                            "ltpc": {
                                "ltp": 3500.0,
                                "ltt": str(int(time.time() * 1000))
                            }
                        }
                    }
                }
            }
        }
        gateway._on_upstox_message(msg)

    thread = threading.Thread(target=background_task)
    thread.start()
    thread.join()

    item = await asyncio.wait_for(q.get(), timeout=1.0)
    assert item is not None
    assert item["symbol"] == "TCS"
    assert item["last_traded_price"] == 3500.0

def test_fresh_data_detection():
    engine = MarketDataIntegrityEngine(stale_threshold_seconds=5.0)
    fresh_tick = {
        "symbol": "TCS",
        "exchange": "NSE",
        "provider_id": "upstox",
        "last_traded_price": 3500.0,
        "last_traded_quantity": 10,
        "total_volume": 1000,
        "source_timestamp": datetime.now(timezone.utc) - timedelta(seconds=1)
    }
    state = engine.process_tick(fresh_tick)
    assert state == MarketDataIntegrityState.VALID

def test_live_quote_store_multiple_instruments():
    gateway = MarketDataGateway()
    gateway.instrument_to_symbol["NSE_EQ|TCS"] = "TCS"
    gateway.instrument_to_symbol["NSE_EQ|REL"] = "RELIANCE"
    
    msg_tcs = {"feeds": {"NSE_EQ|TCS": {"fullFeed": {"marketFF": {"ltpc": {"ltp": 3500.0, "ltt": str(int(time.time() * 1000))}}}}}}
    msg_rel = {"feeds": {"NSE_EQ|REL": {"fullFeed": {"marketFF": {"ltpc": {"ltp": 2500.0, "ltt": str(int(time.time() * 1000))}}}}}}
    
    gateway._on_upstox_message(msg_tcs)
    gateway._on_upstox_message(msg_rel)
    
    tcs_quote = gateway.get_latest_quote("TCS")
    rel_quote = gateway.get_latest_quote("RELIANCE")
    
    assert tcs_quote is not None
    assert tcs_quote["last_traded_price"] == 3500.0
    
    assert rel_quote is not None
    assert rel_quote["last_traded_price"] == 2500.0

def test_reconnect_behavior():
    client = UpstoxWebSocketClient("test_token")
    assert client.reconnect_count == 0
    client._on_reconnecting("Network glitch")
    assert client.status == "RECONNECTING"
    assert client.reconnect_count == 1
    
    client._on_open()
    assert client.status == "CONNECTED"

def test_stale_tick_does_not_override_fresh_in_store():
    gateway = MarketDataGateway()
    gateway.integrity_engine.snapshots.clear()
    gateway.instrument_to_symbol["NSE_EQ|TCS"] = "TCS"
    
    now_ms = int(time.time() * 1000)
    old_ms = now_ms - 10000 
    
    msg_old = {"feeds": {"NSE_EQ|TCS": {"fullFeed": {"marketFF": {"ltpc": {"ltp": 3500.0, "ltt": str(old_ms)}}}}}}
    gateway._on_upstox_message(msg_old)
    
    q = gateway.get_latest_quote("TCS")
    assert q is not None
    # Add volume and quantity for pydantic validation
    q["last_traded_quantity"] = 10
    q["total_volume"] = 100
    assert gateway.integrity_engine.process_tick(q) == MarketDataIntegrityState.REJECTED_STALE

def test_malformed_tick():
    gateway = MarketDataGateway()
    gateway.instrument_to_symbol["NSE_EQ|TCS"] = "TCS"
    gateway.decode_errors = 0
    
    msg = {"feeds": {"NSE_EQ|TCS": {"invalid_format": True}}}
    gateway._on_upstox_message(msg)
    
    assert gateway.get_latest_quote("TCS") is None

@pytest.mark.asyncio
async def test_dashboard_live_stale_logic():
    gateway = MarketDataGateway()
    gateway.config.upstox_enabled = True
    gateway.config.upstox_access_token = "mock"
    with patch("backend.application.realtime_stream_server.get_market_data_gateway", return_value=gateway):
        gateway.upstox_client = UpstoxWebSocketClient("test")
        gateway.upstox_client.status = "CONNECTED"
        
        res = await market_data_health()
        assert res["connection_state"] == "CONNECTED_NO_SUBSCRIPTIONS"
        
        gateway.subscribed_tokens.add("TOKEN")
        res = await market_data_health()
        assert res["connection_state"] == "SUBSCRIBED_NO_TICKS"
        
        gateway.ticks_received = 1
        gateway.last_tick_time = datetime.now(timezone.utc)
        res = await market_data_health()
        assert res["connection_state"] == "LIVE"
        
        gateway.last_tick_time = datetime.now(timezone.utc) - timedelta(seconds=15)
        res = await market_data_health()
        assert res["connection_state"] == "STALE"
