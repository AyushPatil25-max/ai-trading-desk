import json
import logging
import asyncio
import threading
from typing import Callable, Optional, Dict, Any
from urllib.parse import urlparse
import websockets

from backend.config.app_config import get_app_config
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.execution.order_tracker import global_order_tracker

logger = logging.getLogger(__name__)

class DhanWebSocketClient:
    def __init__(self, client_id: str, access_token: str):
        self.client_id = client_id
        self.access_token = access_token
        self.ws_url = "wss://api-order-update.dhan.co"
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._task = None
        self._loop = None
        self._thread = None
        self._processed_events = set()
        self.status = "NOT_CONNECTED"

    def start(self):
        if self._running:
            return
        self._running = True
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect_and_listen())

    def stop(self):
        self._running = False
        if self._ws:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
        if self._thread:
            self._thread.join(timeout=2.0)

    async def _connect_and_listen(self):
        while self._running:
            try:
                self.status = "CONNECTING"
                headers = {
                    "access-token": self.access_token,
                    "client-id": self.client_id
                }
                async with websockets.connect(self.ws_url, extra_headers=headers) as ws:
                    self._ws = ws
                    self.status = "CONNECTED"
                    logger.info("Dhan Order WebSocket connected.")
                    
                    auth_msg = {
                        "type": "AUTH",
                        "client_id": self.client_id,
                        "token": self.access_token
                    }
                    await ws.send(json.dumps(auth_msg))
                    
                    while self._running:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                            await self._handle_message(msg)
                        except asyncio.TimeoutError:
                            await ws.send(json.dumps({"type": "PING"}))
            except Exception as e:
                self.status = "DISCONNECTED"
                logger.error(f"Dhan Order WebSocket error: {e}")
                if self._running:
                    await asyncio.sleep(5.0) 

    async def _handle_message(self, raw_msg: str):
        try:
            data = json.loads(raw_msg)
            if data.get("type") in ("PONG", "AUTH_SUCCESS"):
                return
                
            event_id = data.get("orderId") or data.get("correlationId")
            status = data.get("orderStatus")
            
            if not event_id or not status:
                return
                
            unique_key = f"{event_id}_{status}_{data.get('updateTime', '')}"
            if unique_key in self._processed_events:
                return
            self._processed_events.add(unique_key)
            if len(self._processed_events) > 10000:
                self._processed_events.clear()

            global_audit_chain.append_event(
                event_type="DHAN_WS_ORDER_UPDATE",
                category=EventCategory.EXECUTION,
                component="DhanWebSocketClient",
                correlation_id=data.get("correlationId", "UNKNOWN"),
                severity=EventSeverity.INFO,
                payload={
                    "dhan_order_id": data.get("orderId"),
                    "status": status,
                    "traded_qty": data.get("tradedQuantity"),
                    "avg_price": data.get("averageTradedPrice"),
                    "reason": data.get("legName", data.get("rejectionReason", ""))
                }
            )
        except json.JSONDecodeError:
            pass

_global_dhan_ws: Optional[DhanWebSocketClient] = None

def get_dhan_ws() -> Optional[DhanWebSocketClient]:
    global _global_dhan_ws
    if _global_dhan_ws is None:
        cfg = get_app_config()
        if cfg.dhan_enabled and cfg.dhan_client_id and cfg.dhan_access_token:
            _global_dhan_ws = DhanWebSocketClient(cfg.dhan_client_id, cfg.dhan_access_token)
    return _global_dhan_ws
