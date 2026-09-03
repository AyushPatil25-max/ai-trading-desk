"""
Phase 24 — Deterministic Historical Replay, Backtesting & Walk-Forward Validation E2E Tests

Comprehensive end-to-end test suite covering:
1. Historical data contract: Event time vs processing time separation.
2. Chronological event ordering.
3. Anti-look-ahead bias protection (LookAheadBiasError on future bar, indicator, or context access).
4. Deterministic reproducibility (identical runs produce identical trades, equity curve, and SHA-256 fingerprint).
5. Fingerprint divergence on configuration changes.
6. Simulated execution assumptions (brokerage, slippage, STT, and exchange charges).
7. Pure-Python portfolio accounting (Sharpe, Sortino, drawdown, win rate, profit factor, turnover, zero division guards).
8. Multi-symbol replay with symbol isolation.
9. Walk-forward cross validation (chronological partitions, IN_SAMPLE vs OUT_OF_SAMPLE).
10. Phase 23 Observability integration (OperationalEvent emission to global_audit_chain, audit verification, lifecycle trace).
11. Performance throughput benchmarks.
12. Non-negotiable safety boundaries (TIER_4 locked, zero live broker authority).
13. REST API routing and FastAPI mount verification.
"""

from datetime import datetime, timezone, timedelta
import math
import time
import unittest
import uuid
from unittest.mock import MagicMock, patch

from backend.domain.observability_schemas import AuditVerificationStatus, EventCategory
from backend.domain.replay_schemas import (
    REPLAY_SCHEMA_VERSION,
    DeterministicBacktestResult,
    ExecutionAssumptions,
    HistoricalDataPoint,
    PartitionType,
    ReplayConfig,
    ReplayExitReason,
    ReplayMode,
    ReplayPerformanceSummary,
    TradeSide,
    compute_run_fingerprint,
)
from backend.application.deterministic_replay_engine import (
    DeterministicReplayEngine,
    LookAheadBiasError,
    PointInTimeGuard,
    global_replay_engine,
)
from backend.application.operational_control_plane import global_control_plane
from backend.application.tamper_evident_audit_chain import global_audit_chain


class TestHistoricalDataContract(unittest.TestCase):
    """Test 1 & 2: Historical data contract and event time separation."""

    def test_event_time_vs_processing_time_separation(self):
        event_ts = datetime(2024, 6, 1, 9, 15, tzinfo=timezone.utc)
        processing_ts = datetime.now(timezone.utc)

        data_point = HistoricalDataPoint(
            symbol="TCS.NS",
            event_timestamp=event_ts,
            processing_timestamp=processing_ts,
            open=3500.0,
            high=3550.0,
            low=3480.0,
            close=3520.0,
            volume=50000.0,
        )

        self.assertEqual(data_point.event_timestamp, event_ts)
        self.assertEqual(data_point.processing_timestamp, processing_ts)
        self.assertNotEqual(data_point.event_timestamp, data_point.processing_timestamp)

    def test_ohlcv_bounds_validation(self):
        # High must be >= max(open, close), low <= min(open, close)
        point = HistoricalDataPoint(
            symbol="INFY.NS",
            event_timestamp=datetime(2024, 6, 1, 9, 15, tzinfo=timezone.utc),
            open=1500.0,
            high=1490.0,  # Invalid: lower than open
            low=1510.0,   # Invalid: higher than open
            close=1505.0,
            volume=10000.0,
        )
        self.assertGreaterEqual(point.high, 1505.0)
        self.assertLessEqual(point.low, 1500.0)


class TestAntiLookAheadBiasSafeguards(unittest.TestCase):
    """Test 3: Anti-look-ahead bias protection and rejection of future data access."""

    def setUp(self):
        self.sim_time = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
        self.guard = PointInTimeGuard(current_time=self.sim_time, strict=True)

    def test_past_and_present_data_access_allowed(self):
        past_time = datetime(2024, 6, 10, 9, 15, tzinfo=timezone.utc)
        # Should not raise
        self.guard.validate_access(past_time, context_label="Past Bar")
        self.guard.validate_access(self.sim_time, context_label="Current Bar")

    def test_future_data_access_rejected_with_look_ahead_error(self):
        future_time = datetime(2024, 6, 16, 9, 15, tzinfo=timezone.utc)
        with self.assertRaises(LookAheadBiasError):
            self.guard.validate_access(future_time, context_label="Future Bar")

    def test_future_bar_filtering(self):
        b1 = HistoricalDataPoint(
            symbol="TCS.NS",
            event_timestamp=datetime(2024, 6, 10, tzinfo=timezone.utc),
            open=100, high=105, low=95, close=102, volume=1000,
        )
        b2 = HistoricalDataPoint(
            symbol="TCS.NS",
            event_timestamp=datetime(2024, 6, 15, tzinfo=timezone.utc),
            open=102, high=108, low=100, close=106, volume=1200,
        )
        b3_future = HistoricalDataPoint(
            symbol="TCS.NS",
            event_timestamp=datetime(2024, 6, 20, tzinfo=timezone.utc),
            open=106, high=112, low=104, close=110, volume=1500,
        )

        filtered = self.guard.filter_bars([b1, b2, b3_future])
        self.assertEqual(len(filtered), 2)
        self.assertNotIn(b3_future, filtered)


class TestDeterministicReproducibility(unittest.TestCase):
    """Test 4 & 5: Deterministic replay and run fingerprinting."""

    def _create_sample_dataset(self) -> dict:
        base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
        dataset = {}
        for sym in ["TCS.NS", "INFY.NS"]:
            bars = []
            for i in range(25):
                t = base_ts + timedelta(days=i)
                drift = 5.0 * (1 if (i % 4) < 2 else -1)
                p = 1000.0 + (i * 2.0) + drift
                bars.append({
                    "symbol": sym,
                    "event_timestamp": t.isoformat(),
                    "open": p - 2.0,
                    "high": p + 5.0,
                    "low": p - 4.0,
                    "close": p + 1.0,
                    "volume": 20000.0 + (i * 100.0),
                })
            dataset[sym] = bars
        return dataset

    def test_replaying_twice_produces_identical_outputs_and_fingerprint(self):
        engine = DeterministicReplayEngine()
        ds = self._create_sample_dataset()

        cfg1 = ReplayConfig(run_id="run-det-01", seed=42, initial_capital=100000.0)
        res1 = engine.run_replay(ds, cfg1)

        cfg2 = ReplayConfig(run_id="run-det-02", seed=42, initial_capital=100000.0)
        res2 = engine.run_replay(ds, cfg2)

        # Exact same fingerprint
        self.assertEqual(res1.fingerprint, res2.fingerprint)

        # Exact same financial results
        self.assertEqual(res1.final_equity, res2.final_equity)
        self.assertEqual(res1.performance.total_return_pct, res2.performance.total_return_pct)
        self.assertEqual(res1.performance.total_trades, res2.performance.total_trades)
        self.assertEqual(len(res1.trade_ledger), len(res2.trade_ledger))

        for t1, t2 in zip(res1.trade_ledger, res2.trade_ledger):
            self.assertEqual(t1.symbol, t2.symbol)
            self.assertEqual(t1.entry_price, t2.entry_price)
            self.assertEqual(t1.exit_price, t2.exit_price)
            self.assertEqual(t1.net_pnl, t2.net_pnl)

    def test_different_configurations_produce_distinct_fingerprints(self):
        ds = self._create_sample_dataset()
        engine = DeterministicReplayEngine()

        cfg_base = ReplayConfig(seed=42, initial_capital=100000.0)
        cfg_seed = ReplayConfig(seed=999, initial_capital=100000.0)
        cfg_capital = ReplayConfig(seed=42, initial_capital=250000.0)

        res_base = engine.run_replay(ds, cfg_base)
        res_seed = engine.run_replay(ds, cfg_seed)
        res_capital = engine.run_replay(ds, cfg_capital)

        self.assertNotEqual(res_base.fingerprint, res_seed.fingerprint)
        self.assertNotEqual(res_base.fingerprint, res_capital.fingerprint)


class TestSimulatedExecutionAssumptions(unittest.TestCase):
    """Test 6 & 7: Transaction friction, slippage, and performance accounting."""

    def test_trade_cost_deductions(self):
        engine = DeterministicReplayEngine()
        assumptions = ExecutionAssumptions(
            brokerage_pct=0.0005,
            slippage_pct=0.0010,
            stt_tax_pct=0.0010,
            exchange_charges_pct=0.0001,
            enable_costs=True,
        )
        trade_notional = 100000.0
        costs = engine._calculate_trade_costs(trade_notional, assumptions)
        # Expected: 100000 * (0.0005 + 0.0010 + 0.0001) = 160.0
        self.assertAlmostEqual(costs, 160.0, places=2)

    def test_pure_python_performance_metrics_no_zero_division(self):
        engine = DeterministicReplayEngine()
        # Empty trade scenario: verify zero-division safety
        summary = engine._calculate_performance_summary(
            initial_capital=100000.0,
            final_equity=100000.0,
            trades=[],
            equity_curve=[],
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc),
        )
        self.assertEqual(summary.total_return_pct, 0.0)
        self.assertEqual(summary.win_rate_pct, 0.0)
        self.assertIsNone(summary.profit_factor)
        self.assertIsNone(summary.sharpe_ratio)
        self.assertTrue(summary.insufficient_data)


class TestWalkForwardValidation(unittest.TestCase):
    """Test 8 & 9: Walk-forward cross validation and chronological partitions."""

    def test_walk_forward_partitions_and_out_of_sample_evaluation(self):
        engine = DeterministicReplayEngine()
        base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
        dataset = {"TCS.NS": []}

        # Generate 45 bars
        for i in range(45):
            t = base_ts + timedelta(days=i)
            p = 3000.0 + (i * 5.0)
            dataset["TCS.NS"].append({
                "symbol": "TCS.NS",
                "event_timestamp": t.isoformat(),
                "open": p - 5.0,
                "high": p + 10.0,
                "low": p - 8.0,
                "close": p + 2.0,
                "volume": 20000.0,
            })

        cfg = ReplayConfig(
            walk_forward_enabled=True,
            train_window_bars=15,
            test_window_bars=10,
            step_bars=5,
            symbols=["TCS.NS"],
        )

        res = engine.run_walk_forward(dataset, cfg)
        self.assertIsInstance(res, DeterministicBacktestResult)
        self.assertGreater(len(res.walk_forward_partitions), 0)

        for partition in res.walk_forward_partitions:
            self.assertEqual(partition.partition_type, PartitionType.OUT_OF_SAMPLE)
            self.assertLess(partition.train_start, partition.train_end)
            self.assertLess(partition.test_start, partition.test_end)
            # Guarantee chronological ordering: train_end <= test_start
            self.assertLessEqual(partition.train_end, partition.test_start)


class TestObservabilityIntegration(unittest.TestCase):
    """Test 10: Phase 23 tamper-evident audit integration and lifecycle trace."""

    def test_replay_emits_audited_events_and_preserves_chain_validity(self):
        engine = DeterministicReplayEngine()
        base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
        dataset = {
            "RELIANCE.NS": [
                {
                    "symbol": "RELIANCE.NS",
                    "event_timestamp": (base_ts + timedelta(days=i)).isoformat(),
                    "open": 2500.0 + i,
                    "high": 2510.0 + i,
                    "low": 2490.0 + i,
                    "close": 2505.0 + i,
                    "volume": 15000.0,
                }
                for i in range(10)
            ]
        }

        res = engine.run_replay(dataset, ReplayConfig(symbols=["RELIANCE.NS"]))
        self.assertEqual(res.audit_status, "VALID")
        self.assertGreater(res.audit_events_emitted, 0)

        # Verify tamper-evident audit chain remains 100% valid
        report = global_audit_chain.verify_integrity()
        self.assertEqual(report.status, AuditVerificationStatus.VALID)

    def test_lifecycle_trace_reconstruction_for_replay_decision(self):
        engine = DeterministicReplayEngine()
        base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
        dataset = {
            "INFY.NS": [
                {
                    "symbol": "INFY.NS",
                    "event_timestamp": (base_ts + timedelta(days=i)).isoformat(),
                    "open": 1400.0 + (i * 10.0),
                    "high": 1420.0 + (i * 10.0),
                    "low": 1395.0 + (i * 10.0),
                    "close": 1415.0 + (i * 10.0),
                    "volume": 30000.0,
                }
                for i in range(12)
            ]
        }

        res = engine.run_replay(dataset, ReplayConfig(symbols=["INFY.NS"]))
        if res.trade_ledger:
            corr_id = res.trade_ledger[0].correlation_id
            trace = global_control_plane.reconstruct_lifecycle(corr_id)
            self.assertEqual(trace.correlation_id, corr_id)


class TestReplayPerformanceBenchmark(unittest.TestCase):
    """Test 11: Replay throughput benchmark (>500 events/sec)."""

    def test_replay_throughput(self):
        engine = DeterministicReplayEngine()
        base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
        bars_count = 200
        dataset = {
            "TCS.NS": [
                {
                    "symbol": "TCS.NS",
                    "event_timestamp": (base_ts + timedelta(hours=i)).isoformat(),
                    "open": 3000.0 + i,
                    "high": 3010.0 + i,
                    "low": 2990.0 + i,
                    "close": 3005.0 + i,
                    "volume": 25000.0,
                }
                for i in range(bars_count)
            ]
        }

        start = time.perf_counter()
        res = engine.run_replay(dataset, ReplayConfig(symbols=["TCS.NS"]))
        elapsed = time.perf_counter() - start

        throughput = bars_count / (elapsed or 0.0001)
        # Should process over 500 events per second
        self.assertGreater(throughput, 500.0)


class TestSafetyInvariants(unittest.TestCase):
    """Test 12: TIER_4 live trading permanently locked and zero order authority."""

    def test_tier4_live_real_money_permanently_locked(self):
        from backend.application.broker_interface import BrokerFactory, ConfigurationSafetyError
        with self.assertRaises(ConfigurationSafetyError):
            BrokerFactory.get_adapter("live")

    def test_replay_engine_has_zero_live_order_authority(self):
        engine = DeterministicReplayEngine()
        self.assertFalse(hasattr(engine, "place_live_order"))
        self.assertFalse(hasattr(engine, "submit_live_order"))
        self.assertFalse(hasattr(engine, "execute_live_order"))


class TestReplayRESTEndpoints(unittest.TestCase):
    """Test 13: REST API endpoint availability and FastAPI integration."""

    def test_routes_registered_in_replay_router(self):
        from backend.application.replay_routes import replay_router
        paths = [r.path for r in replay_router.routes]
        self.assertIn("/api/replay/run", paths)
        self.assertIn("/api/replay/walk-forward", paths)
        self.assertIn("/api/replay/runs", paths)
        self.assertIn("/api/replay/runs/{run_id}", paths)
        self.assertIn("/api/replay/fingerprint/{run_id}", paths)
        self.assertIn("/api/replay/config", paths)

    def test_main_fastapi_app_includes_replay_router(self):
        from backend.main import app
        all_paths = []
        for r in app.routes:
            if hasattr(r, "path"):
                all_paths.append(r.path)
            if hasattr(r, "original_router") and hasattr(r.original_router, "routes"):
                all_paths.extend([sub.path for sub in r.original_router.routes if hasattr(sub, "path")])

        self.assertIn("/api/replay/run", all_paths)
        self.assertIn("/api/replay/runs", all_paths)


class TestGranularReplayAndAccounting(unittest.TestCase):
    """Test additional granular accounting, multi-symbol isolation, and route methods."""

    def test_multi_symbol_isolation_with_corrupted_symbol(self):
        engine = DeterministicReplayEngine()
        base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
        dataset = {
            "TCS.NS": [
                {
                    "symbol": "TCS.NS",
                    "event_timestamp": (base_ts + timedelta(days=i)).isoformat(),
                    "open": 3000.0 + (i * 2.0),
                    "high": 3010.0 + (i * 2.0),
                    "low": 2990.0 + (i * 2.0),
                    "close": 3005.0 + (i * 2.0),
                    "volume": 20000.0,
                }
                for i in range(15)
            ],
            # Second symbol with empty/sparse bars
            "CORRUPT.NS": [],
        }

        # Should complete gracefully without raising or corrupting the TCS simulation
        res = engine.run_replay(dataset, ReplayConfig(symbols=["TCS.NS", "CORRUPT.NS"]))
        self.assertEqual(res.status, "COMPLETED" if hasattr(res, "status") else res.audit_status)
        self.assertGreater(len(res.equity_curve), 0)

    def test_empty_dataset_handling(self):
        engine = DeterministicReplayEngine()
        res = engine.run_replay({}, ReplayConfig(symbols=["TCS.NS"]))
        self.assertEqual(res.final_equity, res.initial_capital)
        self.assertEqual(len(res.trade_ledger), 0)
        self.assertTrue(res.performance.insufficient_data)

    def test_rest_route_functions_directly(self):
        from backend.application.replay_routes import (
            trigger_historical_replay,
            get_default_replay_configuration,
            list_replay_runs,
            get_run_fingerprint,
        )

        res = trigger_historical_replay()
        self.assertIsInstance(res, DeterministicBacktestResult)
        self.assertGreater(len(res.fingerprint), 10)

        cfg_res = get_default_replay_configuration()
        self.assertEqual(cfg_res["live_money_execution"], "LOCKED")
        self.assertEqual(cfg_res["mode"], "HISTORICAL_SIMULATION_ONLY")

        runs_res = list_replay_runs()
        self.assertGreaterEqual(runs_res["count"], 1)

        fp_res = get_run_fingerprint(res.run_id)
        self.assertEqual(fp_res["run_id"], res.run_id)
        self.assertEqual(fp_res["fingerprint"], res.fingerprint)


if __name__ == "__main__":
    unittest.main()
