import logging
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime
import time
import threading

from backend.config.app_config import get_app_config
from backend.adapters.upstox_ws_client import UpstoxWebSocketClient
from backend.application.market_data_normalizer import MarketDataNormalizer
from backend.infrastructure.security_master import get_security_master
from backend.execution.live_execution_gate import global_live_execution_gate

logger = logging.getLogger(__name__)

class MarketDataGateway:
    def __init__(self):
        self.config = get_app_config()
        self.upstox_client: Optional[UpstoxWebSocketClient] = None
        self.security_master = get_security_master()
        
        # Phase 38 Market Data Integrity Engine (Critical Path)
        self.integrity_engine = global_live_execution_gate.market_data_engine
        
        self.instrument_to_symbol: Dict[str, str] = {}
        self.subscribed_tokens: set = set()
        self._listeners: List[Any] = []
        
        self.ticks_received = 0
        self.last_tick_time: Optional[datetime] = None
        self.last_tick_symbol: Optional[str] = None
        self.last_tick_price: Optional[float] = None
        self.decode_errors = 0
        self.subscriptions_requested = 0
        self.subscriptions_confirmed = 0
        self.latest_quotes: Dict[str, Dict[str, Any]] = {}

    def start(self):
        if self.config.upstox_enabled and self.config.upstox_access_token:
            self.upstox_client = UpstoxWebSocketClient(self.config.upstox_access_token)
            self.upstox_client.register_callback(self._on_upstox_message)
            self.upstox_client.start()
            
            # Start a background task to subscribe to liquid universe when connected
            threading.Thread(target=self._subscribe_liquid_universe_loop, daemon=True).start()
        else:
            logger.warning("Upstox Market Data Gateway is disabled due to missing config or token.")

    def _subscribe_liquid_universe_loop(self):
        liquid_universe = [
            "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", 
            "SBIN.NS", "ITC.NS", "LT.NS", "BHARTIARTL.NS", "AXISBANK.NS",
            "NIFTY 50", "SENSEX"
        ]
        subscribed = False
        while not subscribed and self.upstox_client and self.upstox_client._running:
            if self.upstox_client.status == "CONNECTED":
                self.subscribe(liquid_universe)
                subscribed = True
            time.sleep(1)

    def stop(self):
        if self.upstox_client:
            self.upstox_client.stop()

    def subscribe(self, symbols: List[str]):
        tokens_to_subscribe = []
        for sym in symbols:
            sec = self.security_master.resolve_symbol(sym)
            if sec and sec.upstox_instrument_token:
                token = sec.upstox_instrument_token
                if token not in self.subscribed_tokens:
                    self.subscribed_tokens.add(token)
                    self.instrument_to_symbol[token] = sec.canonical_symbol
                    tokens_to_subscribe.append(token)
        
        if tokens_to_subscribe:
            self.subscriptions_requested += len(tokens_to_subscribe)
            if self.upstox_client and self.upstox_client.status == "CONNECTED":
                self.upstox_client.subscribe(tokens_to_subscribe)
                self.subscriptions_confirmed = len(self.subscribed_tokens)

    def unsubscribe(self, symbols: List[str]):
        tokens_to_unsubscribe = []
        for sym in symbols:
            sec = self.security_master.resolve_symbol(sym)
            if sec and sec.upstox_instrument_token:
                token = sec.upstox_instrument_token
                if token in self.subscribed_tokens:
                    self.subscribed_tokens.remove(token)
                    self.instrument_to_symbol.pop(token, None)
                    tokens_to_unsubscribe.append(token)
        
        if self.upstox_client and tokens_to_unsubscribe:
            self.upstox_client.unsubscribe(tokens_to_unsubscribe)
            self.subscriptions_confirmed = len(self.subscribed_tokens)

    def add_listener(self, queue: asyncio.Queue):
        loop = asyncio.get_running_loop()
        self._listeners.append((queue, loop))

    def remove_listener(self, queue: asyncio.Queue):
        self._listeners = [(q, l) for q, l in self._listeners if q != queue]

    def get_latest_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self.latest_quotes.get(symbol)

    def _on_upstox_message(self, message: Dict[str, Any]):
        try:
            received_ts = int(time.time() * 1000)
            
            if isinstance(message, dict):
                # Upstox V3 FeedResponse has 'feeds' mapping instrument_key -> feed data
                feeds = message.get("feeds")
                if not isinstance(feeds, dict):
                    feeds = message
                    
                for token, data in feeds.items():
                    if token in self.instrument_to_symbol:
                        symbol = self.instrument_to_symbol[token]
                        normalized = MarketDataNormalizer.normalize_upstox_tick(token, symbol, data)
                        if normalized:
                            self.ticks_received += 1
                            self.last_tick_time = normalized["source_timestamp"]
                            self.last_tick_symbol = symbol
                            self.last_tick_price = normalized.get("last_traded_price")
                            
                            # Cache latest quote for instant lookup
                            self.latest_quotes[symbol] = normalized
                            
                            # Forward tick to Phase 38 Integrity Engine for live safety
                            self.integrity_engine.process_tick(normalized)
                            
                            exchange_ts = int(normalized["source_timestamp"].timestamp() * 1000)
                            normalized["feed_latency_ms"] = max(0, received_ts - exchange_ts)
                            
                            for q, loop in self._listeners:
                                try:
                                    # Safe cross-thread queue put
                                    loop.call_soon_threadsafe(q.put_nowait, normalized)
                                except Exception:
                                    pass
        except Exception as e:
            self.decode_errors += 1
            logger.error(f"Gateway error processing Upstox message: {e}")

_global_gateway = MarketDataGateway()

def get_market_data_gateway() -> MarketDataGateway:
    return _global_gateway
