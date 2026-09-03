"""
Phase 18 — Distributed Paper Simulation Worker Architecture

Provides:
- Independent symbol workers processing market streams concurrently.
- Resilient failure isolation: individual worker errors never cascade across assets.
- Strict authoritative execution routing: all paper orders pass through ExecutionGuard,
  Risk Engine, Pre-Flight gatekeeper, and PaperBrokerAdapter.
- Live real-money trading is permanently blocked and fail-closed.
"""

from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Dict, List, Optional
import uuid

from backend.domain.streaming_schemas import (
    BackpressureStrategy,
    DistributedWorkerPoolStatus,
    StreamEvent,
    StreamEventType,
    StreamSubscription,
    WorkerHealthStatus,
)
from backend.domain.forward_simulation_schemas import MarketDataTick
from backend.application.stream_manager import StreamConsumer, StreamManager, global_stream_manager
from backend.application.forward_simulation_engine import ForwardSimulationEngine, global_forward_engine
from backend.application.execution_guard import ExecutionGuard

logger = logging.getLogger(__name__)


class SymbolPaperWorker:
    """
    Dedicated worker thread responsible for consuming streaming ticks for a single symbol
    and driving the paper simulation pipeline through the authoritative risk gates.
    """

    def __init__(
        self,
        symbol: str,
        stream_manager: Optional[StreamManager] = None,
        forward_engine: Optional[ForwardSimulationEngine] = None,
        queue_capacity: int = 200,
    ):
        self.symbol = symbol.upper()
        self.worker_id = f"worker-{self.symbol}"
        self.stream_manager = stream_manager or global_stream_manager
        self.forward_engine = forward_engine or global_forward_engine

        self._thread: Optional[threading.Thread] = None
        self._stop_signal = threading.Event()
        self._pause_signal = threading.Event()
        self._lock = threading.RLock()

        self._status = WorkerHealthStatus(
            worker_id=self.worker_id,
            symbol=self.symbol,
            is_alive=False,
            state="STOPPED",
        )
        self._consumer: Optional[StreamConsumer] = None
        self.queue_capacity = queue_capacity

    def start(self) -> WorkerHealthStatus:
        """Start the background consumer thread for this symbol."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.get_status()

            # Register dedicated subscription for this symbol
            sub = StreamSubscription(
                consumer_id=self.worker_id,
                symbols=[self.symbol],
                event_types=[StreamEventType.MARKET_TICK],
                queue_capacity=self.queue_capacity,
                backpressure_strategy=BackpressureStrategy.DROP_OLDEST,
            )
            self._consumer = self.stream_manager.register_consumer(sub)

            self._stop_signal.clear()
            self._pause_signal.clear()
            self._status.is_alive = True
            self._status.state = "RUNNING"
            self._status.error_message = None

            self._thread = threading.Thread(
                target=self._run_loop,
                daemon=True,
                name=f"SymbolWorker-{self.symbol}",
            )
            self._thread.start()
            logger.info(f"[SymbolPaperWorker] Started worker thread for {self.symbol}")
            return self.get_status()

    def stop(self, timeout: float = 3.0) -> WorkerHealthStatus:
        """Stop worker thread and unregister stream consumer."""
        with self._lock:
            self._stop_signal.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=timeout)

            if self._consumer:
                self.stream_manager.unregister_consumer(self._consumer.consumer_id)
                self._consumer = None

            self._status.is_alive = False
            self._status.state = "STOPPED"
            logger.info(f"[SymbolPaperWorker] Stopped worker thread for {self.symbol}")
            return self.get_status()

    def pause(self) -> WorkerHealthStatus:
        with self._lock:
            self._pause_signal.set()
            self._status.state = "PAUSED"
            return self.get_status()

    def resume(self) -> WorkerHealthStatus:
        with self._lock:
            self._pause_signal.clear()
            self._status.state = "RUNNING"
            return self.get_status()

    def get_status(self) -> WorkerHealthStatus:
        with self._lock:
            if self._thread:
                self._status.is_alive = self._thread.is_alive()
            return self._status.model_copy()

    def _run_loop(self) -> None:
        """Continuous execution loop processing streaming ticks for this symbol."""
        while not self._stop_signal.is_set():
            if self._pause_signal.is_set():
                time.sleep(0.1)
                continue

            if not self._consumer:
                time.sleep(0.1)
                continue

            event = self._consumer.pop()
            if not event:
                time.sleep(0.02)
                continue

            try:
                self._process_stream_tick(event)
            except Exception as ex:
                logger.error(f"[SymbolPaperWorker] Error processing tick for {self.symbol}: {ex}", exc_info=True)
                with self._lock:
                    self._status.failure_count += 1
                    self._status.error_message = str(ex)

    def _process_stream_tick(self, event: StreamEvent) -> None:
        """Convert StreamEvent to MarketDataTick and execute paper simulation."""
        price = event.data.get("price", 0.0)
        volume = event.data.get("volume", 1000.0)
        if price <= 0.0:
            return

        tick = MarketDataTick(
            tick_id=f"st-{event.event_id}",
            symbol=self.symbol,
            timestamp=event.timestamp,
            price=price,
            volume=volume,
            source=event.source,
        )

        # Ingest into authoritative forward simulation engine
        success, msg, ctx = self.forward_engine.ingest_tick(tick)
        with self._lock:
            self._status.ticks_processed += 1
            self._status.last_processed_time = datetime.now(timezone.utc)

        # If candidate was synthesized and forward session is actively running, execute candidate analysis
        sess = getattr(self.forward_engine, "_session", None)
        if success and ctx and sess and getattr(sess, "state", None) and sess.state.value == "RUNNING":
            cand = type("Candidate", (), {"symbol": self.symbol, "direction": "BUY", "current_price": price})()
            cycle_time = event.timestamp if event.timestamp.tzinfo else event.timestamp.replace(tzinfo=timezone.utc)
            cand_res = self.forward_engine._process_forward_candidate(cand, cycle_time)
            with self._lock:
                if cand_res.get("decision"):
                    self._status.decisions_generated += 1
                if cand_res.get("status") == "FILLED":
                    self._status.paper_orders_submitted += 1


class DistributedPaperWorkerPool:
    """
    Manager coordinating multi-asset distributed paper simulation workers.
    """

    DEFAULT_UNIVERSE = ["TCS.NS", "INFY.NS", "RELIANCE.NS", "HDFCBANK.NS"]

    def __init__(
        self,
        stream_manager: Optional[StreamManager] = None,
        forward_engine: Optional[ForwardSimulationEngine] = None,
    ):
        self.stream_manager = stream_manager or global_stream_manager
        self.forward_engine = forward_engine or global_forward_engine
        self._workers: Dict[str, SymbolPaperWorker] = {}
        self._lock = threading.RLock()

    def start(self, symbols: Optional[List[str]] = None) -> DistributedWorkerPoolStatus:
        """Start workers for the specified symbols (defaults to DEFAULT_UNIVERSE)."""
        target_symbols = symbols or self.DEFAULT_UNIVERSE
        with self._lock:
            for sym in target_symbols:
                sym_clean = sym.upper()
                if sym_clean not in self._workers:
                    worker = SymbolPaperWorker(
                        symbol=sym_clean,
                        stream_manager=self.stream_manager,
                        forward_engine=self.forward_engine,
                    )
                    self._workers[sym_clean] = worker
                self._workers[sym_clean].start()
            return self.get_status()

    def stop(self) -> DistributedWorkerPoolStatus:
        """Stop all workers in the pool."""
        with self._lock:
            for worker in self._workers.values():
                worker.stop()
            return self.get_status()

    def pause(self) -> DistributedWorkerPoolStatus:
        """Pause all workers."""
        with self._lock:
            for worker in self._workers.values():
                worker.pause()
            return self.get_status()

    def resume(self) -> DistributedWorkerPoolStatus:
        """Resume all workers."""
        with self._lock:
            for worker in self._workers.values():
                worker.resume()
            return self.get_status()

    def get_status(self) -> DistributedWorkerPoolStatus:
        """Return aggregate health status of all workers."""
        with self._lock:
            workers_map = {sym: w.get_status() for sym, w in self._workers.items()}
            total = len(workers_map)
            healthy = sum(1 for w in workers_map.values() if w.is_alive and w.state in ("RUNNING", "PAUSED"))
            failed = sum(1 for w in workers_map.values() if w.state == "ERROR" or w.failure_count > 0)
            total_ticks = sum(w.ticks_processed for w in workers_map.values())
            total_orders = sum(w.paper_orders_submitted for w in workers_map.values())

            return DistributedWorkerPoolStatus(
                total_workers=total,
                healthy_workers=healthy,
                failed_workers=failed,
                workers=workers_map,
                total_ticks_processed=total_ticks,
                total_paper_orders=total_orders,
            )

    def clear(self) -> None:
        """Stop and clear workers for testing."""
        with self._lock:
            for w in self._workers.values():
                w.stop()
            self._workers.clear()


# Global singleton worker pool
global_worker_pool = DistributedPaperWorkerPool()
