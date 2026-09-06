import asyncio
import json
import logging
from typing import AsyncGenerator
from fastapi import APIRouter
from fastapi.responses import EventSourceResponse

from backend.application.market_data_gateway import get_market_data_gateway

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/stream", tags=["streaming"])

@router.get("/market-data")
async def stream_market_data():
    """
    Server-Sent Events (SSE) endpoint to stream unified live market data to the frontend UI.
    """
    gateway = get_market_data_gateway()
    queue = asyncio.Queue(maxsize=100)
    
    # Register the queue with the gateway
    gateway.add_listener(queue)
    
    # Auto-subscribe to major indices for dashboard
    gateway.subscribe(["NIFTY 50", "SENSEX"])

    async def event_generator() -> AsyncGenerator[dict, None]:
        try:
            while True:
                # Wait for normalized tick from gateway
                tick = await queue.get()
                
                # Format datetime to iso string for JSON serialization
                if "source_timestamp" in tick:
                    tick["source_timestamp"] = tick["source_timestamp"].isoformat()
                    
                yield {
                    "event": "tick",
                    "data": json.dumps(tick)
                }
        except asyncio.CancelledError:
            logger.info("Client disconnected from market-data stream.")
        finally:
            gateway.remove_listener(queue)

    return EventSourceResponse(event_generator())

@router.get("/health")
async def market_data_health():
    from datetime import datetime, timezone
    gateway = get_market_data_gateway()
    client = gateway.upstox_client
    
    # Calculate age
    age_ms = None
    if gateway.last_tick_time:
        age_ms = int((datetime.now(timezone.utc) - gateway.last_tick_time).total_seconds() * 1000)
    
    raw_status = client.status if client else "NOT_CONFIGURED"
    
    # Truthful connection state machine per Phase 2:
    # DISCONNECTED, CONNECTING, CONNECTED_NO_SUBSCRIPTIONS, SUBSCRIBED_NO_TICKS, LIVE, STALE, ERROR, NOT_CONFIGURED
    if not client or not gateway.config.upstox_enabled or not gateway.config.upstox_access_token:
        state = "NOT_CONFIGURED"
    elif raw_status in ("NOT_CONNECTED", "DISCONNECTED"):
        state = "DISCONNECTED"
    elif raw_status == "CONNECTING":
        state = "CONNECTING"
    elif raw_status == "ERROR":
        state = "ERROR"
    elif raw_status in ("CONNECTED", "RECONNECTING"):
        if not gateway.subscribed_tokens:
            state = "CONNECTED_NO_SUBSCRIPTIONS"
        elif gateway.ticks_received == 0:
            state = "SUBSCRIBED_NO_TICKS"
        elif age_ms is not None and age_ms < 10000:
            state = "LIVE"
        else:
            state = "STALE"
    else:
        state = raw_status

    ws_connected = bool(client and client.status == "CONNECTED")
    auth_success = bool(client and client.status in ("CONNECTED", "RECONNECTING"))
    reconnect_cnt = client.reconnect_count if client else 0
            
    health = {
        "provider": "upstox",
        "connection_state": state,
        "websocket_connected": ws_connected,
        "authentication_success": auth_success,
        "subscriptions_requested": gateway.subscriptions_requested,
        "subscriptions_confirmed": gateway.subscriptions_confirmed,
        "subscribed_instruments": list(gateway.instrument_to_symbol.values()),
        "subscription_count": len(gateway.subscribed_tokens),
        "ticks_received": gateway.ticks_received,
        "last_tick_time": gateway.last_tick_time.isoformat() if gateway.last_tick_time else None,
        "last_tick_timestamp": gateway.last_tick_time.isoformat() if gateway.last_tick_time else None,
        "last_tick_symbol": gateway.last_tick_symbol,
        "last_tick_price": gateway.last_tick_price,
        "last_tick_age_ms": age_ms,
        "decode_errors": gateway.decode_errors,
        "reconnect_count": reconnect_cnt,
        "stale_symbols": []
    }
    
    return health
