import logging
import asyncio
import json
import threading
from typing import Callable, Optional, Dict, Any, List
import upstox_client
from upstox_client.feeder.market_data_streamer_v3 import MarketDataStreamerV3
from backend.config.app_config import get_app_config
from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.application.tamper_evident_audit_chain import global_audit_chain

logger = logging.getLogger(__name__)

class UpstoxWebSocketClient:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self._streamer: Optional[MarketDataStreamerV3] = None
        self._running = False
        self.status = "NOT_CONNECTED"
        self._callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self._thread: Optional[threading.Thread] = None
        self.reconnect_count = 0

    def _setup_streamer(self):
        configuration = upstox_client.Configuration()
        configuration.access_token = self.access_token
        api_client = upstox_client.ApiClient(configuration)
        
        self._streamer = MarketDataStreamerV3(api_client, instrumentKeys=[], mode='full')
        self._streamer.on(MarketDataStreamerV3.Event['OPEN'], self._on_open)
        self._streamer.on(MarketDataStreamerV3.Event['MESSAGE'], self._on_message)
        self._streamer.on(MarketDataStreamerV3.Event['ERROR'], self._on_error)
        self._streamer.on(MarketDataStreamerV3.Event['CLOSE'], self._on_close)
        self._streamer.on(MarketDataStreamerV3.Event['RECONNECTING'], self._on_reconnecting)
        self._streamer.auto_reconnect(True, 10, 5)

    def start(self):
        if self._running:
            return
        self._running = True
        self.status = "CONNECTING"
        self._setup_streamer()
        
        def _run_streamer():
            try:
                self._streamer.connect()
            except Exception as e:
                logger.error(f"Upstox WS failed to start: {e}")
                self.status = "DISCONNECTED"

        self._thread = threading.Thread(target=_run_streamer, daemon=True)
        self._thread.start()
        
    def stop(self):
        self._running = False
        if self._streamer:
            try:
                self._streamer.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting Upstox WS: {e}")
        self.status = "DISCONNECTED"

    def subscribe(self, instrument_tokens: List[str]):
        if self._streamer and self.status == "CONNECTED" and instrument_tokens:
            self._streamer.subscribe(instrument_tokens, "full")

    def unsubscribe(self, instrument_tokens: List[str]):
        if self._streamer and self.status == "CONNECTED" and instrument_tokens:
            self._streamer.unsubscribe(instrument_tokens)

    def register_callback(self, callback: Callable[[Dict[str, Any]], None]):
        self._callbacks.append(callback)

    def _on_open(self):
        logger.info("UPSTOX_CONNECTED: Upstox Market Data WS Connected")
        self.status = "CONNECTED"
        import uuid
        global_audit_chain.append_event(
            event_type="UPSTOX_CONNECTED",
            category=EventCategory.SYSTEM,
            component="UpstoxWebSocketClient",
            correlation_id=uuid.uuid4().hex,
            severity=EventSeverity.INFO,
            reason="Market Data WebSocket established"
        )

    def _on_message(self, message):
        # Broadcast the raw decoded message to callbacks
        for cb in self._callbacks:
            try:
                cb(message)
            except Exception as e:
                logger.error(f"Error in Upstox message callback: {e}")

    def _on_error(self, error):
        logger.error(f"Upstox WS Error: {error}")
        self.status = "ERROR"

    def _on_close(self, close_status_code, close_msg):
        logger.warning(f"UPSTOX_DISCONNECTED: Upstox WS Closed with code {close_status_code}, msg: {close_msg}")
        self.status = "DISCONNECTED"

    def _on_reconnecting(self, message):
        logger.warning(f"UPSTOX_RECONNECT: Upstox WS Reconnecting: {message}")
        self.reconnect_count += 1
        self.status = "RECONNECTING"
