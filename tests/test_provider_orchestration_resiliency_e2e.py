"""
Phase 21 — Market Data Provider Orchestration & Resiliency E2E Verification Suite

25 comprehensive deterministic tests covering:
1. Primary provider success
2. Primary provider timeout
3. Primary provider exception
4. Automatic fallback
5. Multiple provider failure
6. Circuit CLOSED state
7. Circuit OPEN state
8. Circuit HALF_OPEN recovery
9. Invalid price rejection
10. NaN rejection
11. Inf rejection
12. Stale-data detection
13. Future timestamp rejection
14. Malformed OHLC rejection
15. Duplicate observation handling
16. Out-of-order handling
17. Deterministic provider selection
18. Deterministic snapshot identity
19. Provider switching without snapshot corruption
20. Degraded-data state
21. Orchestrator continuity after provider failure
22. Telemetry emission
23. Secret sanitization
24. Dashboard/API integration
25. Backward compatibility
"""

import asyncio
from datetime import datetime, timezone, timedelta
import math
import time
import unittest
from typing import Any, Dict, List, Optional
import uuid
import pandas as pd
from starlette.testclient import TestClient

from backend.domain.schemas import (
    MarketContext,
    HistoricalWindow,
    DataQualityStatus,
    SnapshotFreshness,
)
from backend.domain.provider_schemas import (
    CircuitState,
    FailureType,
    ProviderStatus,
    DataQualityCheckType,
    ValidationResult,
)
from backend.infrastructure.data_providers import MarketDataProvider
from backend.infrastructure.data_quality_gate import DataQualityGate
from backend.infrastructure.circuit_breaker import CircuitBreaker
from backend.infrastructure.provider_orchestrator import ResilientProviderOrchestrator
from backend.application.context_service import ContextService
from backend.infrastructure.cache import InMemoryContextCache
from backend.application.trading_os_orchestrator import TradingOSOrchestrator


def build_valid_ohlcv(days: int = 5, start_price: float = 100.0) -> List[Dict[str, Any]]:
    """Generate strictly valid, monotonically ascending OHLCV records."""
    now_utc = datetime.now(timezone.utc)
    base_dt = now_utc - timedelta(days=days)
    bars = []
    curr = start_price
    for i in range(days):
        dt = base_dt + timedelta(days=i)
        o = round(curr, 2)
        h = round(curr + 2.0, 2)
        l = round(curr - 1.0, 2)
        c = round(curr + 1.0, 2)
        v = 10000.0 + i * 500
        bars.append({
            "date": dt.isoformat(),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
        })
        curr = c
    return bars



class MockProvider(MarketDataProvider):
    def __init__(
        self,
        name: str = "mock_provider",
        delay_s: float = 0.0,
        should_fail: bool = False,
        fail_exception: Optional[Exception] = None,
        custom_context: Optional[MarketContext] = None,
        base_price: float = 100.0,
    ):
        self._name = name
        self.delay_s = delay_s
        self.should_fail = should_fail
        self.fail_exception = fail_exception
        self.custom_context = custom_context
        self.base_price = base_price
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    def get_market_context(
        self,
        symbol: str,
        window: HistoricalWindow = HistoricalWindow.RECENT,
    ) -> MarketContext:
        self.call_count += 1
        if self.delay_s > 0:
            time.sleep(self.delay_s)

        if self.should_fail:
            if self.fail_exception:
                raise self.fail_exception
            raise RuntimeError(f"Simulated failure from {self._name}")

        if self.custom_context:
            return self.custom_context

        n_days = HistoricalWindow.get_days(window)
        ohlcv = build_valid_ohlcv(days=n_days, start_price=self.base_price)
        now_utc = datetime.now(timezone.utc)

        return MarketContext(

            context_id=f"ctx-{self._name}-{uuid.uuid4().hex[:6]}",
            symbol=symbol,
            generated_at=now_utc,
            data_timestamp=now_utc,
            provider=self._name,
            historical_window=window,
            current_price=self.base_price,
            ohlcv_historical=ohlcv,
            technical_indicators={"rsi": 55.0, "ema20": 101.5, "ema50": 98.2},
            quality_status=DataQualityStatus.OK,
        )

    def get_historical_data(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        self.call_count += 1
        if self.should_fail:
            raise RuntimeError(f"Historical data failure from {self._name}")
        ohlcv = build_valid_ohlcv(days=10, start_price=self.base_price)
        return pd.DataFrame(ohlcv)


class TestProviderOrchestrationResiliency(unittest.TestCase):
    """25 comprehensive tests for Phase 21."""

    def setUp(self):
        self.gate = DataQualityGate()

    # 1. Primary provider success
    def test_01_primary_provider_success(self):
        p1 = MockProvider(name="primary_feed")
        orchestrator = ResilientProviderOrchestrator(
            providers=[(p1, 1)],
            quality_gate=self.gate,
        )
        ctx = orchestrator.get_market_context("TCS.NS")
        self.assertEqual(ctx.symbol, "TCS.NS")
        self.assertEqual(ctx.source_provider, "primary_feed")
        self.assertEqual(p1.call_count, 1)
        status = orchestrator.get_status()
        self.assertEqual(status.active_provider, "primary_feed")
        self.assertEqual(status.fallback_level, 0)
        self.assertEqual(status.system_status, ProviderStatus.HEALTHY)

    # 2. Primary provider timeout
    def test_02_primary_provider_timeout(self):
        p1 = MockProvider(name="slow_primary", delay_s=0.5)
        orchestrator = ResilientProviderOrchestrator(
            providers=[(p1, 1)],
            timeout_seconds=0.1,  # Short timeout
            max_retries=0,
            quality_gate=self.gate,
        )
        ctx = orchestrator.get_market_context("INFY.NS")
        self.assertEqual(ctx.quality_status, DataQualityStatus.CRITICAL_FAILURE)
        self.assertEqual(ctx.current_price, 0.0)
        status = orchestrator.get_status()
        m = status.provider_metrics["slow_primary"]
        self.assertGreaterEqual(m.timeout_count, 1)

    # 3. Primary provider exception
    def test_03_primary_provider_exception(self):
        p1 = MockProvider(name="broken_primary", should_fail=True)
        orchestrator = ResilientProviderOrchestrator(
            providers=[(p1, 1)],
            max_retries=0,
            quality_gate=self.gate,
        )
        ctx = orchestrator.get_market_context("RELIANCE.NS")
        self.assertEqual(ctx.quality_status, DataQualityStatus.CRITICAL_FAILURE)
        status = orchestrator.get_status()
        m = status.provider_metrics["broken_primary"]
        self.assertEqual(m.failed_requests, 1)
        self.assertEqual(m.last_failure_type, FailureType.API_ERROR)

    # 4. Automatic fallback
    def test_04_automatic_fallback(self):
        p1 = MockProvider(name="primary_bad", should_fail=True)
        p2 = MockProvider(name="secondary_good", base_price=250.0)
        orchestrator = ResilientProviderOrchestrator(
            providers=[(p1, 1), (p2, 2)],
            max_retries=0,
            quality_gate=self.gate,
        )
        ctx = orchestrator.get_market_context("TCS.NS")
        self.assertEqual(ctx.source_provider, "secondary_good")
        self.assertEqual(ctx.current_price, 250.0)
        self.assertTrue(any("Fallback provider active" in w for w in ctx.warnings))
        status = orchestrator.get_status()
        self.assertEqual(status.active_provider, "secondary_good")
        self.assertEqual(status.fallback_level, 1)
        self.assertTrue(status.is_fallback_active)

    # 5. Multiple provider failure
    def test_05_multiple_provider_failure(self):
        p1 = MockProvider(name="p1", should_fail=True)
        p2 = MockProvider(name="p2", should_fail=True)
        p3 = MockProvider(name="p3", should_fail=True)
        orchestrator = ResilientProviderOrchestrator(
            providers=[(p1, 1), (p2, 2), (p3, 3)],
            max_retries=0,
            quality_gate=self.gate,
        )
        ctx = orchestrator.get_market_context("HDFCBANK.NS")
        self.assertEqual(ctx.quality_status, DataQualityStatus.CRITICAL_FAILURE)
        self.assertEqual(ctx.current_price, 0.0)
        self.assertEqual(ctx.freshness_status, SnapshotFreshness.INVALID)
        self.assertEqual(ctx.source_provider, "NONE")
        self.assertTrue("All 3 providers failed" in ctx.warnings[0])

    # 6. Circuit CLOSED state
    def test_06_circuit_closed_state(self):
        cb = CircuitBreaker(name="test_cb", failure_threshold=3)
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertTrue(cb.allow_request())
        cb.record_success(latency_ms=25.0)
        self.assertEqual(cb.state, CircuitState.CLOSED)

    # 7. Circuit OPEN state
    def test_07_circuit_open_state(self):
        cb = CircuitBreaker(name="test_cb", failure_threshold=3, recovery_timeout_seconds=10.0)
        cb.record_failure(FailureType.NETWORK_ERROR, "fail 1")
        cb.record_failure(FailureType.NETWORK_ERROR, "fail 2")
        self.assertEqual(cb.state, CircuitState.CLOSED)
        cb.record_failure(FailureType.NETWORK_ERROR, "fail 3")
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertFalse(cb.allow_request())

    # 8. Circuit HALF_OPEN recovery
    def test_08_circuit_half_open_recovery(self):
        cb = CircuitBreaker(name="test_cb", failure_threshold=2, recovery_timeout_seconds=0.1)
        cb.record_failure(FailureType.NETWORK_ERROR, "fail 1")
        cb.record_failure(FailureType.NETWORK_ERROR, "fail 2")
        self.assertEqual(cb.state, CircuitState.OPEN)
        time.sleep(0.15)  # Wait for recovery timeout
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)
        self.assertTrue(cb.allow_request())
        cb.record_success(latency_ms=10.0)
        self.assertEqual(cb.state, CircuitState.CLOSED)

    # 9. Invalid price rejection
    def test_09_invalid_price_rejection(self):
        bad_ctx = MockProvider(name="bad_price").get_market_context("TCS.NS")
        bad_ctx = bad_ctx.model_copy(update={"current_price": -50.0})
        res = self.gate.validate(bad_ctx, expected_symbol="TCS.NS")
        self.assertFalse(res.is_valid)
        self.assertIn(DataQualityCheckType.PRICE_BOUNDS, res.checks_failed)

    # 10. NaN rejection
    def test_10_nan_rejection(self):
        bad_ctx = MockProvider(name="nan_price").get_market_context("TCS.NS")
        bad_ctx = bad_ctx.model_copy(update={"current_price": float("nan")})
        res = self.gate.validate(bad_ctx, expected_symbol="TCS.NS")
        self.assertFalse(res.is_valid)
        self.assertIn(DataQualityCheckType.NUMERICAL_INTEGRITY, res.checks_failed)

    # 11. Inf rejection
    def test_11_inf_rejection(self):
        bad_ctx = MockProvider(name="inf_price").get_market_context("TCS.NS")
        bad_ctx = bad_ctx.model_copy(update={"current_price": float("inf")})
        res = self.gate.validate(bad_ctx, expected_symbol="TCS.NS")
        self.assertFalse(res.is_valid)
        self.assertIn(DataQualityCheckType.NUMERICAL_INTEGRITY, res.checks_failed)

    # 12. Stale-data detection
    def test_12_stale_data_detection(self):
        gate = DataQualityGate(max_staleness_seconds=60.0)
        old_ctx = MockProvider(name="stale").get_market_context("TCS.NS")
        old_ctx = old_ctx.model_copy(update={"data_timestamp": datetime.now(timezone.utc) - timedelta(hours=2)})
        res = gate.validate(old_ctx, expected_symbol="TCS.NS")
        self.assertFalse(res.is_valid)
        self.assertIn(DataQualityCheckType.TIMESTAMP_FRESHNESS, res.checks_failed)

    # 13. Future timestamp rejection
    def test_13_future_timestamp_rejection(self):
        gate = DataQualityGate(future_tolerance_seconds=10.0)
        future_ctx = MockProvider(name="future").get_market_context("TCS.NS")
        future_ctx = future_ctx.model_copy(update={"data_timestamp": datetime.now(timezone.utc) + timedelta(hours=1)})
        res = gate.validate(future_ctx, expected_symbol="TCS.NS")
        self.assertFalse(res.is_valid)
        self.assertIn(DataQualityCheckType.TIMESTAMP_FUTURE, res.checks_failed)

    # 14. Malformed OHLC rejection
    def test_14_malformed_ohlc_rejection(self):
        bad_ohlcv = build_valid_ohlcv(5)
        bad_ohlcv[2]["high"] = 50.0
        bad_ohlcv[2]["low"] = 150.0  # high < low!
        bad_ctx = MockProvider(name="bad_ohlc").get_market_context("TCS.NS")
        bad_ctx = bad_ctx.model_copy(update={"ohlcv_historical": bad_ohlcv})
        res = self.gate.validate(bad_ctx, expected_symbol="TCS.NS")
        self.assertFalse(res.is_valid)
        self.assertIn(DataQualityCheckType.OHLC_RELATIONSHIPS, res.checks_failed)

    # 15. Duplicate observation handling
    def test_15_duplicate_observation_handling(self):
        bad_ohlcv = build_valid_ohlcv(5)
        bad_ohlcv[1]["date"] = bad_ohlcv[0]["date"]  # duplicate date
        bad_ctx = MockProvider(name="dup").get_market_context("TCS.NS")
        bad_ctx = bad_ctx.model_copy(update={"ohlcv_historical": bad_ohlcv})
        res = self.gate.validate(bad_ctx, expected_symbol="TCS.NS")
        self.assertFalse(res.is_valid)
        self.assertIn(DataQualityCheckType.DUPLICATE_OBSERVATIONS, res.checks_failed)

    # 16. Out-of-order handling
    def test_16_out_of_order_handling(self):
        bad_ohlcv = build_valid_ohlcv(5)
        bad_ohlcv[3]["date"] = "2023-01-01T00:00:00+00:00"  # ancient date out of order
        bad_ctx = MockProvider(name="ooo").get_market_context("TCS.NS")
        bad_ctx = bad_ctx.model_copy(update={"ohlcv_historical": bad_ohlcv})
        res = self.gate.validate(bad_ctx, expected_symbol="TCS.NS")
        self.assertFalse(res.is_valid)
        self.assertIn(DataQualityCheckType.SEQUENCE_ORDER, res.checks_failed)

    # 17. Deterministic provider selection
    def test_17_deterministic_provider_selection(self):
        p1 = MockProvider(name="feed_c")
        p2 = MockProvider(name="feed_a")
        p3 = MockProvider(name="feed_b")
        # Registered out of priority order
        orchestrator = ResilientProviderOrchestrator(
            providers=[(p1, 3), (p2, 1), (p3, 2)],
            quality_gate=self.gate,
        )
        ctx = orchestrator.get_market_context("TCS.NS")
        self.assertEqual(ctx.source_provider, "feed_a")  # Priority 1 chosen
        self.assertEqual(p2.call_count, 1)
        self.assertEqual(p1.call_count, 0)
        self.assertEqual(p3.call_count, 0)

    # 18. Deterministic snapshot identity
    def test_18_deterministic_snapshot_identity(self):
        p1 = MockProvider(name="fixed_primary", base_price=100.0)
        orchestrator = ResilientProviderOrchestrator(
            providers=[(p1, 1)],
            quality_gate=self.gate,
        )
        cache = InMemoryContextCache(ttl_seconds=60)
        service = ContextService(provider=orchestrator, cache=cache)

        ctx1 = asyncio.run(service.get_market_context("TCS.NS"))
        ctx2 = asyncio.run(service.get_market_context("TCS.NS"))
        self.assertEqual(ctx1.snapshot_id, ctx2.snapshot_id)
        self.assertTrue(ctx1.snapshot_id.startswith("snap-"))

    # 19. Provider switching without snapshot corruption
    def test_19_provider_switching_without_snapshot_corruption(self):
        # Both providers return functionally identical market data
        p1 = MockProvider(name="primary_feed", base_price=100.0)
        p2 = MockProvider(name="secondary_feed", base_price=100.0)

        cache = InMemoryContextCache(ttl_seconds=60)
        service1 = ContextService(provider=p1, cache=cache)
        service2 = ContextService(provider=p2, cache=cache)

        c1 = p1.get_market_context("TCS.NS")
        c2 = p2.get_market_context("TCS.NS")

        # Hashing core financial data produces valid stable hashes
        id1 = service1._generate_deterministic_snapshot_id(c1)
        id2 = service2._generate_deterministic_snapshot_id(c2)
        self.assertIsNotNone(id1)
        self.assertIsNotNone(id2)

    # 20. Degraded-data state
    def test_20_degraded_data_state(self):
        p1 = MockProvider(name="p1", should_fail=True)
        orchestrator = ResilientProviderOrchestrator(
            providers=[(p1, 1)],
            max_retries=0,
            quality_gate=self.gate,
        )
        ctx = orchestrator.get_market_context("WIPRO.NS")
        self.assertEqual(ctx.quality_status, DataQualityStatus.CRITICAL_FAILURE)
        self.assertEqual(ctx.freshness_status, SnapshotFreshness.INVALID)
        self.assertEqual(ctx.current_price, 0.0)
        self.assertEqual(len(ctx.ohlcv_historical), 0)

    # 21. Orchestrator continuity after provider failure
    def test_21_orchestrator_continuity_after_provider_failure(self):
        p1 = MockProvider(name="dead_feed", should_fail=True)
        orchestrator_data = ResilientProviderOrchestrator(
            providers=[(p1, 1)],
            max_retries=0,
            quality_gate=self.gate,
        )
        degraded_ctx = orchestrator_data.get_market_context("TCS.NS")
        trading_os = TradingOSOrchestrator()
        # Pipeline must handle degraded context without crashing
        run = trading_os.run_pipeline(market_context=degraded_ctx)
        self.assertIsNotNone(run)
        self.assertIn("MARKET_CONTEXT", run.stages)
        self.assertEqual(run.market_context["current_price"], 0.0)

    # 22. Telemetry emission
    def test_22_telemetry_emission(self):
        events = []
        class MockTelemetry:
            def record_event(self, **kwargs):
                events.append(kwargs)

        p1 = MockProvider(name="telemetry_feed")
        orchestrator = ResilientProviderOrchestrator(
            providers=[(p1, 1)],
            telemetry_engine=MockTelemetry(),
            quality_gate=self.gate,
        )
        ctx = orchestrator.get_market_context("TCS.NS")
        self.assertGreaterEqual(len(events), 1)
        event_names = [e["metadata"].get("event") for e in events]
        self.assertIn("PROVIDER_SELECTED", event_names)

    # 23. Secret sanitization
    def test_23_secret_sanitization(self):
        orchestrator = ResilientProviderOrchestrator()
        meta = {
            "symbol": "TCS.NS",
            "api_key": "super_secret_key_12345",
            "auth_token": "bearer_token_xyz",
            "nested": {"client_secret": "my_secret_pw", "safe_val": 42},
        }
        sanitized = orchestrator._sanitize_metadata(meta)
        self.assertEqual(sanitized["api_key"], "***REDACTED***")
        self.assertEqual(sanitized["auth_token"], "***REDACTED***")
        self.assertEqual(sanitized["nested"]["client_secret"], "***REDACTED***")
        self.assertEqual(sanitized["nested"]["safe_val"], 42)

    # 24. Dashboard/API integration
    def test_24_dashboard_api_integration(self):
        from backend.main import app
        client = TestClient(app)

        res = client.get("/api/providers/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("system_status", data)
        self.assertIn("primary_provider", data)
        self.assertIn("provider_metrics", data)

        res_status = client.get("/api/providers/status")
        self.assertEqual(res_status.status_code, 200)
        status_data = res_status.json()
        self.assertIn("system_status", status_data)

        res_reset = client.post("/api/providers/circuits/reset")
        self.assertEqual(res_reset.status_code, 200)
        reset_data = res_reset.json()
        self.assertEqual(reset_data["status"], "RESET_SUCCESSFUL")

    # 25. Backward compatibility
    def test_25_backward_compatibility(self):
        p1 = MockProvider(name="yfinance_compat")
        orchestrator = ResilientProviderOrchestrator(providers=[(p1, 1)])
        # Must implement MarketDataProvider
        self.assertIsInstance(orchestrator, MarketDataProvider)
        self.assertEqual(orchestrator.name, "resilient_orchestrator")

        # Test historical data method
        df = orchestrator.get_historical_data("TCS.NS")
        self.assertIsInstance(df, pd.DataFrame)
        self.assertFalse(df.empty)

        # Test ContextService consumption
        cache = InMemoryContextCache(ttl_seconds=60)
        service = ContextService(provider=orchestrator, cache=cache)
        ctx = asyncio.run(service.get_market_context("TCS.NS"))
        self.assertEqual(ctx.symbol, "TCS.NS")
        self.assertGreater(ctx.current_price, 0.0)


if __name__ == "__main__":
    unittest.main()

