"""
Phase 18 — Central Stream Manager & Event Distribution Service

High-throughput, thread-safe asynchronous stream routing engine responsible for:
- Event ingestion and validation (NaN, Inf, negative prices).
- Data quality assurance: deduplication, staleness checks, out-of-order sequence tracking.
- Dynamic subscription fan-out to registered consumers.
- Bounded queue capacity with deterministic backpressure handling (DROP_OLDEST, REJECT_NEWEST).
- Real-time metrics calculation (throughput, latency percentiles p50/p95/p99, queue depth).
- Observational-only: strictly downstream, zero authority to execute live trades.
"""

from collections import deque
from datetime import datetime, timezone
import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

import numpy as np

from backend.domain.streaming_schemas import (
    BackpressureStrategy,
    StreamEvent,
    StreamEventType,
    StreamHealthMetrics,
    StreamSubscription,
)
from backend.domain.telemetry_schemas import ExecutionEvent

logger = logging.getLogger(__name__)


class StreamConsumer:
    """Internal consumer representation holding a bounded queue and subscription rules."""

    def __init__(self, subscription: StreamSubscription):
        self.subscription = subscription
        self.consumer_id = subscription.consumer_id
        self.queue: deque = deque(maxlen=subscription.queue_capacity)
        self.dropped_count: int = 0
        self.delivered_count: int = 0
        self._lock = threading.Lock()

    def matches(self, event: StreamEvent) -> bool:
        """Evaluate whether this consumer's filter matches the event."""
        # Event type check
        if event.event_type not in self.subscription.event_types:
            return False
        # Symbol check (* matches all)
        if "*" in self.subscription.symbols:
            return True
        return event.symbol in self.subscription.symbols

    def push(self, event: StreamEvent) -> bool:
        """Push an event respecting bounded capacity and backpressure strategy."""
        with self._lock:
            if len(self.queue) >= self.subscription.queue_capacity:
                if self.subscription.backpressure_strategy == BackpressureStrategy.DROP_OLDEST:
                    if self.queue:
                        self.queue.popleft()
                        self.dropped_count += 1
                elif self.subscription.backpressure_strategy == BackpressureStrategy.REJECT_NEWEST:
                    self.dropped_count += 1
                    return False
                elif self.subscription.backpressure_strategy == BackpressureStrategy.BLOCK_WITH_TIMEOUT:
                    # Non-blocking fallback for thread-safe deque
                    self.queue.popleft()
                    self.dropped_count += 1

            self.queue.append(event)
            self.delivered_count += 1
            return True

    def pop(self) -> Optional[StreamEvent]:
        """Pop an event from the consumer queue."""
        with self._lock:
            if self.queue:
                return self.queue.popleft()
            return None

    def get_queue_depth(self) -> int:
        with self._lock:
            return len(self.queue)


class StreamManager:
    """
    Central event ingestion, normalization, routing, and metrics service.
    """

    def __init__(
        self,
        max_staleness_seconds: float = 60.0,
        dedup_window_size: int = 2000,
        latency_window_size: int = 1000,
    ):
        self.max_staleness_seconds = max_staleness_seconds
        self.dedup_window_size = dedup_window_size
        self.latency_window_size = latency_window_size

        self._lock = threading.RLock()
        self._consumers: Dict[str, StreamConsumer] = {}
        self._started_at = datetime.now(timezone.utc)
        self._reconnect_count: int = 0

        # Quality tracking caches
        self._dedup_cache: deque = deque(maxlen=dedup_window_size)
        self._dedup_set: Set[str] = set()
        self._last_sequences: Dict[str, int] = {}

        # Performance & metrics tracking
        self._metrics = StreamHealthMetrics(uptime_seconds=0.0)
        self._recent_latencies: deque = deque(maxlen=latency_window_size)
        self._recent_event_timestamps: deque = deque(maxlen=1000)
        self._symbol_event_counts: Dict[str, int] = {}
        self._symbol_last_rates: Dict[str, float] = {}

    # ── Consumer Management ───────────────────────────────────────────────────

    def register_consumer(self, subscription: StreamSubscription) -> StreamConsumer:
        """Register a new consumer for filtered event delivery."""
        with self._lock:
            consumer = StreamConsumer(subscription)
            self._consumers[subscription.consumer_id] = consumer
            self._metrics.active_consumers_count = len(self._consumers)
            logger.info(
                f"[StreamManager] Registered consumer {consumer.consumer_id} for "
                f"symbols={subscription.symbols}, types={[t.value for t in subscription.event_types]}"
            )
            return consumer

    def unregister_consumer(self, consumer_id: str) -> None:
        """Unregister an existing consumer and free its queue."""
        with self._lock:
            if consumer_id in self._consumers:
                del self._consumers[consumer_id]
                self._metrics.active_consumers_count = len(self._consumers)
                logger.info(f"[StreamManager] Unregistered consumer {consumer_id}")

    def get_consumer(self, consumer_id: str) -> Optional[StreamConsumer]:
        with self._lock:
            return self._consumers.get(consumer_id)

    # ── Ingestion & Normalization ─────────────────────────────────────────────

    def ingest_event(self, event: StreamEvent) -> StreamEvent:
        """
        Normalize, validate, inspect data quality, and distribute an event to consumers.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            event.received_at = now
            self._metrics.events_received += 1
            self._recent_event_timestamps.append(now.timestamp())

            # 1. Validation check
            if not event.is_valid:
                self._metrics.events_rejected += 1
                return event

            # 2. Staleness check
            ts = event.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_s = max(0.0, (now - ts).total_seconds())
            if age_s > self.max_staleness_seconds:
                event.is_stale = True
                self._metrics.events_stale += 1

            # 3. Deduplication check
            price_val = event.data.get("price", 0.0)
            dedup_key = f"{event.symbol}:{event.event_type.value}:{event.timestamp.isoformat()}:{price_val}"
            if event.sequence_num is not None:
                dedup_key = f"{event.symbol}:{event.sequence_num}"

            if dedup_key in self._dedup_set:
                event.is_duplicate = True
                self._metrics.events_duplicated += 1
            else:
                if len(self._dedup_cache) >= self.dedup_window_size:
                    old_key = self._dedup_cache.popleft()
                    self._dedup_set.discard(old_key)
                self._dedup_cache.append(dedup_key)
                self._dedup_set.add(dedup_key)

            # 4. Out-of-order check
            if event.sequence_num is not None:
                last_seq = self._last_sequences.get(event.symbol)
                if last_seq is not None and event.sequence_num < last_seq and not event.is_duplicate:
                    event.is_out_of_order = True
                    self._metrics.events_out_of_order += 1
                elif not event.is_duplicate:
                    self._last_sequences[event.symbol] = event.sequence_num

            # 5. Latency tracking
            latency_ms = max(0.0, age_s * 1000.0)
            self._recent_latencies.append(latency_ms)

            # 6. Accepted update
            self._metrics.events_accepted += 1
            self._metrics.last_event_timestamp = now
            self._symbol_event_counts[event.symbol] = self._symbol_event_counts.get(event.symbol, 0) + 1

            # 7. Fan-out to consumers
            dropped_this_event = 0
            for consumer in self._consumers.values():
                if consumer.matches(event):
                    pushed = consumer.push(event)
                    if not pushed:
                        dropped_this_event += 1

            self._metrics.events_dropped += dropped_this_event

            # Recalculate metrics snapshot
            self._recalculate_metrics_locked()
            return event

    def ingest_raw_tick(
        self,
        symbol: str,
        price: float,
        volume: Optional[float] = None,
        timestamp: Optional[datetime] = None,
        source: str = "TICK_FEED",
        sequence_num: Optional[int] = None,
    ) -> StreamEvent:
        """Construct, validate, and ingest a raw market tick."""
        ts = timestamp or datetime.now(timezone.utc)
        error_msg = None
        is_valid = True

        # Numerical validation
        if price is None or math.isnan(price) or math.isinf(price) or price <= 0.0:
            is_valid = False
            error_msg = f"Invalid price {price}: must be a finite positive number."
        if volume is not None and (math.isnan(volume) or math.isinf(volume) or volume < 0.0):
            is_valid = False
            error_msg = f"Invalid volume {volume}: must be a finite non-negative number."

        payload = {"price": price if (price is not None and not math.isnan(price) and not math.isinf(price)) else 0.0}
        if volume is not None and not (math.isnan(volume) or math.isinf(volume)):
            payload["volume"] = volume

        event = StreamEvent(
            event_id=f"tick-{uuid.uuid4().hex[:8]}",
            event_type=StreamEventType.MARKET_TICK,
            symbol=symbol,
            source=source,
            timestamp=ts,
            sequence_num=sequence_num,
            data=payload,
            is_valid=is_valid,
            validation_error=error_msg,
        )
        return self.ingest_event(event)

    def ingest_telemetry_event(self, te: ExecutionEvent) -> StreamEvent:
        """Bridge an ExecutionEvent from the ExecutionTelemetryEngine into the StreamManager."""
        # Sanitize metadata to guarantee zero credentials or secrets leak
        sanitized_meta = dict(te.metadata)
        for key in list(sanitized_meta.keys()):
            if any(s in key.lower() for s in ("secret", "key", "token", "password")):
                sanitized_meta[key] = "***REDACTED***"

        event = StreamEvent(
            event_id=f"stream-{te.event_id}",
            event_type=StreamEventType.EXECUTION_EVENT,
            symbol=te.symbol or "SYSTEM",
            source="EXECUTION_TELEMETRY",
            timestamp=te.timestamp,
            data={
                "execution_id": te.execution_id,
                "order_id": te.order_id,
                "event_type": te.event_type.value,
                "severity": te.severity.value,
                "reason": te.reason,
                "quantity": te.quantity,
                "price": te.price,
                "metadata": sanitized_meta,
            },
            is_valid=True,
        )
        return self.ingest_event(event)

    # ── Metrics Calculation ───────────────────────────────────────────────────

    def _recalculate_metrics_locked(self) -> None:
        """Update throughput, latency percentiles, and queue statistics."""
        now = datetime.now(timezone.utc)
        self._metrics.uptime_seconds = max(0.1, (now - self._started_at).total_seconds())

        # Rolling Events Per Second calculation (last 5 seconds)
        cutoff = now.timestamp() - 5.0
        recent_count = sum(1 for t in self._recent_event_timestamps if t >= cutoff)
        self._metrics.events_per_second = round(recent_count / 5.0, 2)

        # Latency statistics
        if self._recent_latencies:
            lat_arr = np.array(self._recent_latencies)
            self._metrics.processing_latency_avg_ms = round(float(np.mean(lat_arr)), 2)
            self._metrics.processing_latency_p50_ms = round(float(np.percentile(lat_arr, 50)), 2)
            self._metrics.processing_latency_p95_ms = round(float(np.percentile(lat_arr, 95)), 2)
            self._metrics.processing_latency_p99_ms = round(float(np.percentile(lat_arr, 99)), 2)

        # Queue depth across active consumers
        total_depth = sum(c.get_queue_depth() for c in self._consumers.values())
        total_cap = sum(c.subscription.queue_capacity for c in self._consumers.values())
        self._metrics.queue_depth = total_depth
        self._metrics.queue_capacity = total_cap if total_cap > 0 else 1000
        self._metrics.queue_utilization_pct = (
            round((total_depth / self._metrics.queue_capacity) * 100.0, 1)
            if self._metrics.queue_capacity > 0
            else 0.0
        )

        # Per-symbol rate approximations
        for sym, cnt in self._symbol_event_counts.items():
            self._symbol_last_rates[sym] = round(cnt / self._metrics.uptime_seconds, 2)
        self._metrics.per_symbol_event_rate = dict(self._symbol_last_rates)
        self._metrics.reconnect_count = self._reconnect_count

    def get_metrics(self) -> StreamHealthMetrics:
        """Return a copy of the current calculated metrics."""
        with self._lock:
            self._recalculate_metrics_locked()
            return self._metrics.model_copy()

    def record_reconnect(self) -> None:
        """Increment client reconnect telemetry counter."""
        with self._lock:
            self._reconnect_count += 1
            self._metrics.reconnect_count = self._reconnect_count

    def clear(self) -> None:
        """Reset state for tests."""
        with self._lock:
            self._consumers.clear()
            self._dedup_cache.clear()
            self._dedup_set.clear()
            self._last_sequences.clear()
            self._recent_latencies.clear()
            self._recent_event_timestamps.clear()
            self._symbol_event_counts.clear()
            self._symbol_last_rates.clear()
            self._reconnect_count = 0
            self._started_at = datetime.now(timezone.utc)
            self._metrics = StreamHealthMetrics(uptime_seconds=0.0)


# Global singleton instance
global_stream_manager = StreamManager()
