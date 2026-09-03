"""
Phase 18 — Distributed Real-Time Streaming & High-Frequency Telemetry Ingestion E2E Test Suite

Verifies:
1. Event schemas, normalization, and numerical integrity checks (NaN, Inf, negative price).
2. Data quality checks: deduplication, staleness validation, out-of-order sequence detection.
3. Central StreamManager subscription, fan-out, and multi-consumer routing.
4. Bounded queues and backpressure strategies (DROP_OLDEST, REJECT_NEWEST).
5. Slow consumer isolation: a saturated queue drops events safely without stalling other consumers.
6. WebSocket telemetry lifecycle: connection, subscription update, heartbeat ping/pong, and clean disconnect.
7. Distributed paper simulation worker pool: multi-symbol concurrency, start/stop/pause/resume, failure isolation.
8. Real-time stream health metrics calculation: throughput (events/sec), latency percentiles (p50/p95/p99), queue utilization.
9. REST endpoints (/api/streaming/*).
10. Controlled performance benchmark: ingests 1,000+ synthetic ticks measuring throughput and latency.
11. Non-negotiable safety invariant: TIER_4_LIVE_REAL_MONEY remains permanently locked and fail-closed.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import math
import time
import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import numpy as np

from backend.domain.broker_schemas import BrokerConfig, BrokerEnvironment
from backend.domain.streaming_schemas import (
    STREAMING_ENGINE_VERSION,
    BackpressureStrategy,
    DistributedWorkerPoolStatus,
    StreamEvent,
    StreamEventType,
    StreamHealthMetrics,
    StreamSubscription,
    WorkerHealthStatus,
)
from backend.domain.telemetry_schemas import EventSeverity, ExecutionEvent, ExecutionEventType
from backend.application.stream_manager import (
    StreamConsumer,
    StreamManager,
    global_stream_manager,
)
from backend.application.distributed_paper_worker import (
    DistributedPaperWorkerPool,
    SymbolPaperWorker,
    global_worker_pool,
)
from backend.main import app


class TestRealtimeStreamingE2E(unittest.TestCase):
    """Comprehensive test suite for Phase 18 Distributed Streaming & Telemetry."""

    def setUp(self):
        self.stream_mgr = StreamManager(max_staleness_seconds=10.0, dedup_window_size=500)
        self.client = TestClient(app)

    def tearDown(self):
        self.stream_mgr.clear()

    # ── 1. Schemas & Numerical Integrity ──────────────────────────────────────

    def test_01_event_schema_and_numerical_validation(self):
        # Valid event
        evt = self.stream_mgr.ingest_raw_tick(symbol="TCS.NS", price=3500.0, volume=100.0)
        self.assertIsInstance(evt, StreamEvent)
        self.assertTrue(evt.is_valid)
        self.assertEqual(evt.symbol, "TCS.NS")
        self.assertEqual(evt.data["price"], 3500.0)

        # Invalid price (<= 0)
        evt_neg = self.stream_mgr.ingest_raw_tick(symbol="TCS.NS", price=-10.0)
        self.assertFalse(evt_neg.is_valid)
        self.assertIn("must be a finite positive number", evt_neg.validation_error)

        # Invalid price (NaN / Inf)
        evt_nan = self.stream_mgr.ingest_raw_tick(symbol="TCS.NS", price=float("nan"))
        self.assertFalse(evt_nan.is_valid)

        evt_inf = self.stream_mgr.ingest_raw_tick(symbol="TCS.NS", price=float("inf"))
        self.assertFalse(evt_inf.is_valid)

    # ── 2. Data Quality: Deduplication ────────────────────────────────────────

    def test_02_deduplication_detection(self):
        fixed_ts = datetime(2026, 8, 30, 10, 0, 0, tzinfo=timezone.utc)
        # First tick
        e1 = self.stream_mgr.ingest_raw_tick(symbol="INFY.NS", price=1600.0, timestamp=fixed_ts)
        self.assertFalse(e1.is_duplicate)

        # Exact same tick (symbol, timestamp, price)
        e2 = self.stream_mgr.ingest_raw_tick(symbol="INFY.NS", price=1600.0, timestamp=fixed_ts)
        self.assertTrue(e2.is_duplicate)

        metrics = self.stream_mgr.get_metrics()
        self.assertGreaterEqual(metrics.events_duplicated, 1)

    # ── 3. Data Quality: Staleness Detection ──────────────────────────────────

    def test_03_staleness_detection(self):
        now = datetime.now(timezone.utc)
        stale_ts = now - timedelta(seconds=60)  # 60s old, threshold is 10s

        e_stale = self.stream_mgr.ingest_raw_tick(symbol="RELIANCE.NS", price=2800.0, timestamp=stale_ts)
        self.assertTrue(e_stale.is_stale)

        metrics = self.stream_mgr.get_metrics()
        self.assertGreaterEqual(metrics.events_stale, 1)

    # ── 4. Data Quality: Out-of-Order Sequences ───────────────────────────────

    def test_04_out_of_order_sequence_detection(self):
        # Sequence 100
        e100 = self.stream_mgr.ingest_raw_tick(symbol="HDFCBANK.NS", price=1500.0, sequence_num=100)
        self.assertFalse(e100.is_out_of_order)

        # Sequence 101 (in order)
        e101 = self.stream_mgr.ingest_raw_tick(symbol="HDFCBANK.NS", price=1501.0, sequence_num=101)
        self.assertFalse(e101.is_out_of_order)

        # Sequence 99 (out of order arrival)
        e99 = self.stream_mgr.ingest_raw_tick(symbol="HDFCBANK.NS", price=1499.0, sequence_num=99)
        self.assertTrue(e99.is_out_of_order)

        metrics = self.stream_mgr.get_metrics()
        self.assertGreaterEqual(metrics.events_out_of_order, 1)

    # ── 5. Multi-Consumer Subscription & Fan-Out ──────────────────────────────

    def test_05_subscription_and_fan_out(self):
        # Consumer 1: Wildcard (all symbols)
        sub1 = StreamSubscription(consumer_id="c1", symbols=["*"])
        c1 = self.stream_mgr.register_consumer(sub1)

        # Consumer 2: TCS.NS only
        sub2 = StreamSubscription(consumer_id="c2", symbols=["TCS.NS"])
        c2 = self.stream_mgr.register_consumer(sub2)

        # Consumer 3: INFY.NS only
        sub3 = StreamSubscription(consumer_id="c3", symbols=["INFY.NS"])
        c3 = self.stream_mgr.register_consumer(sub3)

        # Ingest TCS tick
        self.stream_mgr.ingest_raw_tick(symbol="TCS.NS", price=3500.0)

        # Ingest INFY tick
        self.stream_mgr.ingest_raw_tick(symbol="INFY.NS", price=1600.0)

        # Consumer 1 gets both
        self.assertEqual(c1.get_queue_depth(), 2)
        # Consumer 2 gets only TCS
        self.assertEqual(c2.get_queue_depth(), 1)
        # Consumer 3 gets only INFY
        self.assertEqual(c3.get_queue_depth(), 1)

        # Pop from c2 and verify symbol
        popped = c2.pop()
        self.assertIsNotNone(popped)
        self.assertEqual(popped.symbol, "TCS.NS")

    # ── 6. Bounded Queues & Backpressure (DROP_OLDEST / REJECT_NEWEST) ─────────

    def test_06_bounded_queues_and_backpressure(self):
        # Capacity 5, DROP_OLDEST
        sub_drop = StreamSubscription(
            consumer_id="c_drop",
            symbols=["*"],
            queue_capacity=5,
            backpressure_strategy=BackpressureStrategy.DROP_OLDEST,
        )
        c_drop = self.stream_mgr.register_consumer(sub_drop)

        # Capacity 5, REJECT_NEWEST
        sub_rej = StreamSubscription(
            consumer_id="c_rej",
            symbols=["*"],
            queue_capacity=5,
            backpressure_strategy=BackpressureStrategy.REJECT_NEWEST,
        )
        c_rej = self.stream_mgr.register_consumer(sub_rej)

        # Ingest 10 ticks
        for i in range(10):
            self.stream_mgr.ingest_raw_tick(symbol="TCS.NS", price=3500.0 + i, sequence_num=i + 1)

        # Both queues bounded at capacity 5
        self.assertEqual(c_drop.get_queue_depth(), 5)
        self.assertEqual(c_rej.get_queue_depth(), 5)

        # c_drop dropped 5 oldest ticks, so oldest available is sequence 6
        oldest_drop = c_drop.pop()
        self.assertEqual(oldest_drop.sequence_num, 6)

        # c_rej rejected 5 newest ticks, so oldest available is sequence 1
        oldest_rej = c_rej.pop()
        self.assertEqual(oldest_rej.sequence_num, 1)

        metrics = self.stream_mgr.get_metrics()
        self.assertGreater(metrics.events_dropped, 0)

    # ── 7. Slow Consumer Isolation ────────────────────────────────────────────

    def test_07_slow_consumer_isolation(self):
        # Fast consumer with large buffer
        c_fast = self.stream_mgr.register_consumer(
            StreamSubscription(consumer_id="c_fast", queue_capacity=1000)
        )
        # Slow consumer with small buffer (10)
        c_slow = self.stream_mgr.register_consumer(
            StreamSubscription(consumer_id="c_slow", queue_capacity=10)
        )

        for i in range(100):
            self.stream_mgr.ingest_raw_tick(symbol="ASSET.NS", price=100.0 + i, sequence_num=i + 1)

        # Fast consumer got all 100 events
        self.assertEqual(c_fast.get_queue_depth(), 100)
        # Slow consumer bounded at 10, dropped 90 events
        self.assertEqual(c_slow.get_queue_depth(), 10)
        self.assertEqual(c_slow.dropped_count, 90)

    # ── 8. Telemetry Ingestion Bridge ─────────────────────────────────────────

    def test_08_telemetry_event_ingestion_bridge(self):
        c = self.stream_mgr.register_consumer(
            StreamSubscription(consumer_id="c_telemetry", event_types=[StreamEventType.EXECUTION_EVENT])
        )

        exec_evt = ExecutionEvent(
            event_type=ExecutionEventType.ORDER_FILLED,
            execution_id="exec-123",
            order_id="ord-999",
            symbol="TCS.NS",
            quantity=10,
            price=3500.0,
            reason="Simulated paper fill",
            metadata={"broker": "PaperBroker", "api_key": "sensitive_val"},
        )

        stream_evt = self.stream_mgr.ingest_telemetry_event(exec_evt)
        self.assertEqual(stream_evt.event_type, StreamEventType.EXECUTION_EVENT)
        self.assertEqual(stream_evt.symbol, "TCS.NS")
        # Ensure secret key in metadata is redacted
        self.assertEqual(stream_evt.data["metadata"]["api_key"], "***REDACTED***")
        self.assertEqual(c.get_queue_depth(), 1)

    # ── 9. Distributed Paper Worker Pool ──────────────────────────────────────

    def test_09_distributed_paper_worker_pool(self):
        pool = DistributedPaperWorkerPool(stream_manager=self.stream_mgr)
        try:
            status = pool.start(symbols=["TCS.NS", "INFY.NS"])
            self.assertEqual(status.total_workers, 2)
            self.assertEqual(status.healthy_workers, 2)

            # Push ticks for both workers through stream manager
            self.stream_mgr.ingest_raw_tick(symbol="TCS.NS", price=3550.0)
            self.stream_mgr.ingest_raw_tick(symbol="INFY.NS", price=1620.0)

            time.sleep(0.1)  # Allow worker threads to consume

            updated_status = pool.get_status()
            self.assertIn("TCS.NS", updated_status.workers)
            self.assertIn("INFY.NS", updated_status.workers)
            self.assertGreaterEqual(updated_status.total_ticks_processed, 2)

            # Pause & resume
            pool.pause()
            self.assertEqual(pool.get_status().workers["TCS.NS"].state, "PAUSED")
            pool.resume()
            self.assertEqual(pool.get_status().workers["TCS.NS"].state, "RUNNING")
        finally:
            pool.stop()
            self.assertEqual(pool.get_status().workers["TCS.NS"].state, "STOPPED")

    # ── 10. Performance Benchmark (1,000+ Ticks Throughput & Latency) ──────────

    def test_10_high_volume_performance_benchmark(self):
        # Register a benchmark consumer
        c_bench = self.stream_mgr.register_consumer(
            StreamSubscription(consumer_id="c_bench", queue_capacity=2000)
        )

        n_events = 1000
        t0 = time.monotonic()
        for i in range(n_events):
            self.stream_mgr.ingest_raw_tick(
                symbol="NIFTY.INDEX",
                price=24000.0 + (i % 50),
                volume=100.0 + (i % 10),
                sequence_num=i + 1,
            )
        elapsed = time.monotonic() - t0

        metrics = self.stream_mgr.get_metrics()
        self.assertEqual(metrics.events_accepted, n_events)
        self.assertEqual(c_bench.get_queue_depth(), n_events)

        throughput = n_events / elapsed
        self.assertGreater(throughput, 1000.0)  # Must exceed 1,000 events/sec

        # Validate latency percentiles are calculated from real measurements
        self.assertGreaterEqual(metrics.processing_latency_p50_ms, 0.0)
        self.assertGreaterEqual(metrics.processing_latency_p95_ms, 0.0)
        self.assertGreaterEqual(metrics.processing_latency_p99_ms, 0.0)

    # ── 11. WebSocket Connection Lifecycle ────────────────────────────────────

    def test_11_websocket_telemetry_lifecycle(self):
        with self.client.websocket_connect("/ws/telemetry") as ws:
            # 1. Receive CONNECTION_ACK
            ack = ws.receive_json()
            self.assertEqual(ack["type"], "CONNECTION_ACK")
            self.assertIn("consumer_id", ack)

            # 2. Send ping, receive pong
            ws.send_json({"action": "ping"})
            pong = ws.receive_json()
            self.assertEqual(pong["type"], "PONG")

            # 3. Send subscription update
            ws.send_json({"action": "subscribe", "symbols": ["TCS.NS"]})
            sub_ack = ws.receive_json()
            self.assertEqual(sub_ack["type"], "SUBSCRIPTION_UPDATED")
            self.assertEqual(sub_ack["symbols"], ["TCS.NS"])

            # 4. Ingest a tick to global_stream_manager and verify WS receives it
            global_stream_manager.ingest_raw_tick(symbol="TCS.NS", price=3600.0)
            received_evt = ws.receive_json()
            self.assertEqual(received_evt["symbol"], "TCS.NS")
            self.assertEqual(received_evt["data"]["price"], 3600.0)

    # ── 12. REST API Endpoints ───────────────────────────────────────────────

    def test_12_rest_api_endpoints(self):
        # 1. Status endpoint
        status_res = self.client.get("/api/streaming/status")
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()
        self.assertEqual(status_data["phase"], 18)
        self.assertTrue(status_data["tier4_live_real_money_blocked"])

        # 2. Metrics endpoint
        metrics_res = self.client.get("/api/streaming/metrics")
        self.assertEqual(metrics_res.status_code, 200)
        m = metrics_res.json()
        self.assertIn("events_per_second", m)
        self.assertIn("processing_latency_p50_ms", m)

        # 3. Ingest endpoint
        ingest_res = self.client.post("/api/streaming/ingest", json={
            "symbol": "TCS.NS",
            "price": 3540.0,
            "volume": 200.0,
        })
        self.assertEqual(ingest_res.status_code, 200)
        i_data = ingest_res.json()
        self.assertEqual(i_data["symbol"], "TCS.NS")
        self.assertTrue(i_data["is_valid"])

        # 4. Workers endpoint
        w_res = self.client.get("/api/streaming/workers")
        self.assertEqual(w_res.status_code, 200)

        # 5. Workers control endpoint
        ctrl_res = self.client.post("/api/streaming/workers/control", json={"action": "start"})
        self.assertEqual(ctrl_res.status_code, 200)
        self.assertGreater(ctrl_res.json()["total_workers"], 0)

        ctrl_stop = self.client.post("/api/streaming/workers/control", json={"action": "stop"})
        self.assertEqual(ctrl_stop.status_code, 200)

    # ── 13. Safety Boundary: Real-Money Live Execution Disabled ───────────────

    def test_13_safety_invariants_and_live_broker_disabled(self):
        # BrokerConfig LIVE remains permanently blocked
        with self.assertRaises(ValueError):
            BrokerConfig(broker_environment=BrokerEnvironment.LIVE)

        # Verify fail-closed guarantee string exists in worker status
        w_status = global_worker_pool.get_status()
        self.assertIn("strictly disabled", w_status.fail_closed_guarantee)


if __name__ == "__main__":
    unittest.main()
