"""
Phase 38 - Market Data Integrity Engine

Deterministic engine for real-time market data integrity validation,
protecting against stale, duplicate, out-of-order, and malformed data.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
from pydantic import ValidationError

from backend.domain.market_data_schemas import (
    MarketTick, MarketQuote, OHLCCandle, MarketDataFreshness,
    MarketDataIntegrityState, MarketDataSourceHealth, MarketDataSnapshot
)
from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.application.tamper_evident_audit_chain import global_audit_chain

class MarketDataIntegrityEngine:
    def __init__(self, stale_threshold_seconds: float = 5.0):
        self.stale_threshold = timedelta(seconds=stale_threshold_seconds)
        self.snapshots: Dict[str, MarketDataSnapshot] = {}
        # Stores (symbol, provider) -> health
        self.health_tracker: Dict[tuple[str, str], MarketDataSourceHealth] = {}
        
    def _get_health(self, symbol: str, provider_id: str) -> MarketDataSourceHealth:
        key = (symbol, provider_id)
        if key not in self.health_tracker:
            self.health_tracker[key] = MarketDataSourceHealth(provider_id=provider_id)
        return self.health_tracker[key]
        
    def _emit_audit(self, event_type: str, component: str, symbol: str, reason: str, severity: EventSeverity = EventSeverity.WARNING):
        global_audit_chain.append_event(
            event_type=event_type,
            category=EventCategory.MARKET_DATA,
            component=component,
            correlation_id=f"{symbol}-{datetime.now(timezone.utc).timestamp()}",
            severity=severity,
            symbol=symbol,
            reason=reason
        )

    def process_tick(self, raw_tick_dict: dict) -> MarketDataIntegrityState:
        symbol = raw_tick_dict.get("symbol", "UNKNOWN")
        provider_id = raw_tick_dict.get("provider_id", "UNKNOWN")
        health = self._get_health(symbol, provider_id)
        
        try:
            tick = MarketTick(**raw_tick_dict)
        except ValidationError as e:
            health.consecutive_failures += 1
            health.last_invalid_update = datetime.now(timezone.utc)
            self._update_health_status(health)
            reason = str(e)
            if "Future dated" in reason:
                self._emit_audit("MARKET_DATA_FUTURE_DATE", "MarketDataIntegrityEngine", symbol, reason)
                return MarketDataIntegrityState.REJECTED_FUTURE_DATE
            self._emit_audit("MARKET_DATA_MALFORMED", "MarketDataIntegrityEngine", symbol, reason)
            return MarketDataIntegrityState.REJECTED_MALFORMED

        # Ensure snapshot exists
        if symbol not in self.snapshots:
            self.snapshots[symbol] = MarketDataSnapshot(symbol=symbol, provider_health=health)
            
        snapshot = self.snapshots[symbol]
        last_tick = snapshot.latest_tick
        
        # Validation rules
        if last_tick:
            # 1. Out of order (Source Timestamp)
            if tick.source_timestamp < last_tick.source_timestamp:
                health.consecutive_failures += 1
                self._emit_audit("MARKET_DATA_OUT_OF_ORDER", "MarketDataIntegrityEngine", symbol, "Timestamp regression")
                return MarketDataIntegrityState.REJECTED_OUT_OF_ORDER
                
            # 2. Duplicate Check
            if tick.source_timestamp == last_tick.source_timestamp and tick.sequence_number == last_tick.sequence_number:
                health.consecutive_failures += 1
                self._emit_audit("MARKET_DATA_DUPLICATE", "MarketDataIntegrityEngine", symbol, "Duplicate tick received")
                return MarketDataIntegrityState.REJECTED_DUPLICATE
                
            # 3. Sequence Gaps
            if tick.sequence_number is not None and last_tick.sequence_number is not None:
                if tick.sequence_number <= last_tick.sequence_number:
                    health.consecutive_failures += 1
                    self._emit_audit("MARKET_DATA_OUT_OF_ORDER", "MarketDataIntegrityEngine", symbol, "Sequence regression")
                    return MarketDataIntegrityState.REJECTED_OUT_OF_ORDER
                if tick.sequence_number > last_tick.sequence_number + 1:
                    health.sequence_gaps += 1
                    self._emit_audit("MARKET_DATA_SEQUENCE_GAP", "MarketDataIntegrityEngine", symbol, "Sequence gap detected", severity=EventSeverity.INFO)
                    # We accept it, but note the gap.

        # 4. Freshness check
        now = datetime.now(timezone.utc)
        age = now - tick.source_timestamp
        if age > self.stale_threshold:
            health.consecutive_failures += 1
            health.last_invalid_update = now
            self._update_health_status(health)
            self._emit_audit("MARKET_DATA_STALE", "MarketDataIntegrityEngine", symbol, f"Age {age.total_seconds()}s exceeds threshold")
            return MarketDataIntegrityState.REJECTED_STALE

        # Accept
        snapshot.latest_tick = tick
        snapshot.integrity_state = MarketDataIntegrityState.VALID
        snapshot.freshness = MarketDataFreshness.FRESH
        snapshot.provider_health = health
        
        health.last_successful_update = now
        health.last_valid_update = tick.source_timestamp
        health.consecutive_failures = 0
        health.data_age_seconds = age.total_seconds()
        self._update_health_status(health)
        
        self._emit_audit("MARKET_DATA_ACCEPTED", "MarketDataIntegrityEngine", symbol, "Tick accepted", severity=EventSeverity.INFO)
        return MarketDataIntegrityState.VALID

    def process_quote(self, raw_quote_dict: dict) -> MarketDataIntegrityState:
        symbol = raw_quote_dict.get("symbol", "UNKNOWN")
        provider_id = raw_quote_dict.get("provider_id", "UNKNOWN")
        health = self._get_health(symbol, provider_id)
        
        try:
            quote = MarketQuote(**raw_quote_dict)
        except ValidationError as e:
            health.consecutive_failures += 1
            self._update_health_status(health)
            reason = str(e)
            if "Crossed quote" in reason:
                self._emit_audit("MARKET_DATA_CROSSED_QUOTE", "MarketDataIntegrityEngine", symbol, reason)
                return MarketDataIntegrityState.REJECTED_CROSSED_QUOTE
            if "Future dated" in reason:
                self._emit_audit("MARKET_DATA_FUTURE_DATE", "MarketDataIntegrityEngine", symbol, reason)
                return MarketDataIntegrityState.REJECTED_FUTURE_DATE
            self._emit_audit("MARKET_DATA_MALFORMED", "MarketDataIntegrityEngine", symbol, reason)
            return MarketDataIntegrityState.REJECTED_MALFORMED

        if symbol not in self.snapshots:
            self.snapshots[symbol] = MarketDataSnapshot(symbol=symbol, provider_health=health)
            
        snapshot = self.snapshots[symbol]
        last_quote = snapshot.latest_quote
        
        # Out of order / Duplicate
        if last_quote:
            if quote.source_timestamp < last_quote.source_timestamp:
                health.consecutive_failures += 1
                return MarketDataIntegrityState.REJECTED_OUT_OF_ORDER
            if quote.source_timestamp == last_quote.source_timestamp and quote.sequence_number == last_quote.sequence_number:
                health.consecutive_failures += 1
                return MarketDataIntegrityState.REJECTED_DUPLICATE
            if quote.sequence_number is not None and last_quote.sequence_number is not None:
                if quote.sequence_number <= last_quote.sequence_number:
                    health.consecutive_failures += 1
                    return MarketDataIntegrityState.REJECTED_OUT_OF_ORDER

        now = datetime.now(timezone.utc)
        age = now - quote.source_timestamp
        if age > self.stale_threshold:
            health.consecutive_failures += 1
            self._update_health_status(health)
            return MarketDataIntegrityState.REJECTED_STALE

        # Accept
        snapshot.latest_quote = quote
        snapshot.integrity_state = MarketDataIntegrityState.VALID
        snapshot.freshness = MarketDataFreshness.FRESH
        snapshot.provider_health = health
        health.last_successful_update = now
        health.consecutive_failures = 0
        health.data_age_seconds = age.total_seconds()
        self._update_health_status(health)
        return MarketDataIntegrityState.VALID

    def _update_health_status(self, health: MarketDataSourceHealth):
        if health.consecutive_failures == 0:
            if health.status != "HEALTHY":
                self._emit_audit("MARKET_DATA_PROVIDER_RECOVERED", "MarketDataIntegrityEngine", health.provider_id, "Provider recovered")
            health.status = "HEALTHY"
        elif health.consecutive_failures > 5:
            if health.status != "UNAVAILABLE":
                self._emit_audit("MARKET_DATA_PROVIDER_UNAVAILABLE", "MarketDataIntegrityEngine", health.provider_id, "Provider unavailable")
            health.status = "UNAVAILABLE"
        elif health.consecutive_failures > 2:
            if health.status != "DEGRADED":
                self._emit_audit("MARKET_DATA_PROVIDER_DEGRADED", "MarketDataIntegrityEngine", health.provider_id, "Provider degraded")
            health.status = "DEGRADED"

    def update_freshness(self):
        """Called periodically to downgrade freshness of stale snapshots."""
        now = datetime.now(timezone.utc)
        for symbol, snapshot in self.snapshots.items():
            if snapshot.freshness == MarketDataFreshness.FRESH:
                # Check tick
                if snapshot.latest_tick:
                    age = now - snapshot.latest_tick.source_timestamp
                    if age > self.stale_threshold:
                        snapshot.freshness = MarketDataFreshness.STALE
                        self._emit_audit("MARKET_DATA_STALE", "MarketDataIntegrityEngine", symbol, "Data became stale")
                # Check quote
                if snapshot.latest_quote:
                    age = now - snapshot.latest_quote.source_timestamp
                    if age > self.stale_threshold:
                        snapshot.freshness = MarketDataFreshness.STALE

    def get_snapshot(self, symbol: str) -> Optional[MarketDataSnapshot]:
        return self.snapshots.get(symbol)
        
    def fail_closed_check(self, symbol: str) -> bool:
        """
        Integration endpoint for downstream Execution Preflight.
        Returns True ONLY if data is FRESH and VALID.
        """
        # Run freshness sweep before returning
        self.update_freshness()
        snapshot = self.get_snapshot(symbol)
        if not snapshot:
            return False
        return snapshot.freshness == MarketDataFreshness.FRESH and snapshot.integrity_state == MarketDataIntegrityState.VALID
