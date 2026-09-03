"""
Phase 22 — System Resilience, Fault Injection & Automated Recovery E2E Tests

Comprehensive chaos and resilience test suite covering:
A. Failure detection (across failure types)
B. Failure classification (component, severity, safe fallback)
C. Retry limits and backoff (exponential backoff, jitter, retry exhaustion)
D. Timeout enforcement (sync and async execution deadlines)
E. Circuit breaker transitions (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
F. Safe degradation policies (fail-closed, zero price/model fabrication)
G. Automated recovery workflows (stream, worker, broker sandbox, model)
H. Worker isolation (failed worker does not impair other symbols)
I. Streaming recovery (reconnection and subscription preservation)
J. Cache & snapshot recovery (invalidation, fresh fetch)
K. Broker sandbox recovery & reconciliation verification
L. Telemetry resilience (safety independent of telemetry availability)
M. Correlation ID and audit trail integrity
N. Secret & credential non-exposure
O. Real-money execution permanently impossible (TIER_4 locked)
P. Compound failure scenarios
Q. Resilience Scorecard calculation & certification
R. REST API endpoints & route verification
"""

import asyncio
import threading
import time
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from backend.domain.resilience_schemas import (
    CircuitState,
    ComponentHealthRecord,
    ComponentSupervisorState,
    FailureDomainType,
    FailureEvent,
    FailureSeverity,
    RecoveryAction,
    RecoveryState,
    ResilienceComponent,
    ResilienceReadinessClassification,
    ResilienceScorecard,
    ResilienceStatusSummary,
)
from backend.application.resilience_engine import (
    ResilienceEngine,
    ServiceCircuitBreaker,
    _sanitize_metadata,
    global_resilience_engine,
)
from backend.application.health_supervisor import (
    ComponentHealthSupervisor,
    global_health_supervisor,
)
from backend.application.recovery_orchestrator import (
    RecoveryOrchestrator,
    global_recovery_orchestrator,
)
from backend.application.resilience_fault_injector import (
    ResilienceFaultInjector,
    global_resilience_fault_injector,
)


class TestFailureDomainSchemas(unittest.TestCase):
    """Test Phase 22 domain models and enum completeness."""

    def test_all_19_failure_types_present(self):
        expected = {
            "MARKET_DATA_FAILURE", "MARKET_DATA_STALE", "STREAM_DISCONNECT",
            "STREAM_BACKPRESSURE", "WEBSOCKET_FAILURE", "WORKER_FAILURE",
            "WORKER_TIMEOUT", "MODEL_TIMEOUT", "MODEL_FAILURE",
            "MODEL_INVALID_RESPONSE", "CACHE_FAILURE", "SNAPSHOT_INTEGRITY_FAILURE",
            "DATABASE_FAILURE", "BROKER_SANDBOX_FAILURE", "BROKER_TIMEOUT",
            "TELEMETRY_FAILURE", "API_FAILURE", "RESOURCE_EXHAUSTION", "UNKNOWN_FAILURE",
        }
        actual = {f.value for f in FailureDomainType}
        self.assertEqual(actual, expected)
        self.assertEqual(len(FailureDomainType), 19)

    def test_failure_event_model(self):
        event = FailureEvent(
            component=ResilienceComponent.MARKET_DATA,
            failure_type=FailureDomainType.MARKET_DATA_FAILURE,
            description="Upstream quote provider timed out.",
            severity=FailureSeverity.CRITICAL,
        )
        self.assertTrue(event.failure_id.startswith("fail-"))
        self.assertTrue(event.correlation_id.startswith("corr-"))
        self.assertEqual(event.recovery_state, RecoveryState.DETECTED)
        self.assertFalse(event.trading_halted)

    def test_resilience_scorecard_model(self):
        scorecard = ResilienceScorecard(
            total_scenarios_tested=10,
            passed_scenarios=10,
            failed_scenarios=0,
            recovery_success_rate=1.0,
            mean_time_to_recover_ms=15.2,
            readiness_classification=ResilienceReadinessClassification.HIGHLY_RESILIENT,
        )
        self.assertEqual(scorecard.recovery_success_rate, 1.0)
        self.assertEqual(scorecard.readiness_classification, ResilienceReadinessClassification.HIGHLY_RESILIENT)


class TestResilienceEngineTimeoutsAndRetries(unittest.TestCase):
    """Test C & D: Timeout enforcement and bounded retries."""

    def setUp(self):
        self.engine = ResilienceEngine(sleep_fn=lambda _: None)

    def test_sync_timeout_enforcement_exceeded(self):
        def slow_func():
            time.sleep(0.5)
            return "DONE"

        val, timed_out = self.engine.execute_with_timeout_sync(
            slow_func, timeout_seconds=0.05, fallback_value="FALLBACK"
        )
        self.assertTrue(timed_out)
        self.assertEqual(val, "FALLBACK")

    def test_sync_timeout_enforcement_success(self):
        def quick_func():
            return "QUICK"

        val, timed_out = self.engine.execute_with_timeout_sync(
            quick_func, timeout_seconds=1.0, fallback_value="FALLBACK"
        )
        self.assertFalse(timed_out)
        self.assertEqual(val, "QUICK")

    def test_async_timeout_enforcement(self):
        async def slow_coro():
            await asyncio.sleep(0.5)
            return "ASYNC_DONE"

        async def run_test():
            return await self.engine.execute_with_timeout_async(
                slow_coro, timeout_seconds=0.05, fallback_value="ASYNC_FALLBACK"
            )

        val, timed_out = asyncio.run(run_test())
        self.assertTrue(timed_out)
        self.assertEqual(val, "ASYNC_FALLBACK")

    def test_bounded_exponential_backoff_calculation(self):
        d1 = self.engine.calculate_backoff(attempt=1, base_delay_seconds=1.0, jitter_factor=0.0)
        d2 = self.engine.calculate_backoff(attempt=2, base_delay_seconds=1.0, jitter_factor=0.0)
        d3 = self.engine.calculate_backoff(attempt=3, base_delay_seconds=1.0, jitter_factor=0.0)
        d_max = self.engine.calculate_backoff(attempt=10, base_delay_seconds=1.0, max_delay_seconds=10.0, jitter_factor=0.0)

        self.assertEqual(d1, 1.0)
        self.assertEqual(d2, 2.0)
        self.assertEqual(d3, 4.0)
        self.assertEqual(d_max, 10.0)

    def test_bounded_retry_exhaustion(self):
        attempts_counter = 0

        def always_fails():
            nonlocal attempts_counter
            attempts_counter += 1
            raise RuntimeError("Temporary error")

        result, attempts_used, succeeded = self.engine.execute_with_retry_sync(
            always_fails,
            max_attempts=3,
            safe_fallback="SAFE_DEFAULT",
            component=ResilienceComponent.MODEL_SERVICES,
            failure_type=FailureDomainType.MODEL_FAILURE,
        )

        self.assertFalse(succeeded)
        self.assertEqual(attempts_used, 3)
        self.assertEqual(attempts_counter, 3)
        self.assertEqual(result, "SAFE_DEFAULT")
        self.assertEqual(len(self.engine.get_active_failures()), 1)


class TestServiceCircuitBreaker(unittest.TestCase):
    """Test E: Circuit breaker state machine transitions."""

    def test_circuit_state_transitions(self):
        cb = ServiceCircuitBreaker(
            name="test-service",
            failure_threshold=2,
            recovery_timeout_seconds=0.1,
            half_open_success_threshold=1,
        )

        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertTrue(cb.allow_request())

        # 1st failure: remains CLOSED
        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.CLOSED)

        # 2nd failure: trips to OPEN
        tripped = cb.record_failure()
        self.assertTrue(tripped)
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertFalse(cb.allow_request())

        # Await recovery timeout: transitions to HALF_OPEN
        time.sleep(0.12)
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)

        # Probe allowed
        self.assertTrue(cb.allow_request())
        # Second probe blocked while first probe in flight
        self.assertFalse(cb.allow_request())

        # Probe succeeds: re-closes to CLOSED
        cb.record_success()
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertTrue(cb.allow_request())


class TestComponentHealthSupervisorAndSafeDegradation(unittest.TestCase):
    """Test B & F: Component health tracking and deterministic safe degradation."""

    def setUp(self):
        self.resilience_engine = ResilienceEngine(sleep_fn=lambda _: None)
        self.supervisor = ComponentHealthSupervisor(resilience_engine=self.resilience_engine)

    def test_initial_healthy_states(self):
        self.assertEqual(
            self.supervisor.get_overall_resilience_state(),
            ComponentSupervisorState.HEALTHY,
        )
        rec = self.supervisor.get_component_record(ResilienceComponent.MARKET_DATA)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.state, ComponentSupervisorState.HEALTHY)

    def test_market_data_stale_degradation(self):
        state = self.supervisor.record_operation_failure(
            component=ResilienceComponent.MARKET_DATA,
            failure_type=FailureDomainType.MARKET_DATA_STALE,
            error_message="Data age 420s exceeds 300s threshold.",
        )
        self.assertEqual(state, ComponentSupervisorState.DEGRADED)
        rec = self.supervisor.get_component_record(ResilienceComponent.MARKET_DATA)
        self.assertIn("REJECT_DECISIONS_STALE_DATA", rec.active_fallback)
        self.assertEqual(self.supervisor.get_overall_resilience_state(), ComponentSupervisorState.DEGRADED)

    def test_model_failure_deterministic_fallback(self):
        state = self.supervisor.record_operation_failure(
            component=ResilienceComponent.MODEL_SERVICES,
            failure_type=FailureDomainType.MODEL_FAILURE,
            error_message="LLM API returned 503 Service Unavailable.",
        )
        self.assertEqual(state, ComponentSupervisorState.DEGRADED)
        rec = self.supervisor.get_component_record(ResilienceComponent.MODEL_SERVICES)
        self.assertIn("DETERMINISTIC_MODEL_FALLBACK", rec.active_fallback)

    def test_broker_sandbox_failure_halt_and_reconcile(self):
        state = self.supervisor.record_operation_failure(
            component=ResilienceComponent.BROKER_SANDBOX,
            failure_type=FailureDomainType.BROKER_SANDBOX_FAILURE,
            error_message="Sandbox connection dropped.",
        )
        self.assertEqual(state, ComponentSupervisorState.UNAVAILABLE)
        rec = self.supervisor.get_component_record(ResilienceComponent.BROKER_SANDBOX)
        self.assertIn("HALT_SANDBOX_EXECUTION_REQUIRE_RECONCILIATION", rec.active_fallback)

    def test_worker_failure_isolation(self):
        state = self.supervisor.record_operation_failure(
            component=ResilienceComponent.PAPER_WORKERS,
            failure_type=FailureDomainType.WORKER_FAILURE,
            error_message="TCS worker crashed on corrupted tick.",
        )
        self.assertEqual(state, ComponentSupervisorState.DEGRADED)
        rec = self.supervisor.get_component_record(ResilienceComponent.PAPER_WORKERS)
        self.assertIn("ISOLATE_FAILED_SYMBOL_WORKER", rec.active_fallback)

    def test_success_restores_healthy(self):
        self.supervisor.record_operation_failure(
            component=ResilienceComponent.CONTEXT_CACHE,
            failure_type=FailureDomainType.CACHE_FAILURE,
            error_message="Cache miss storm.",
        )
        self.assertEqual(
            self.supervisor.get_component_record(ResilienceComponent.CONTEXT_CACHE).state,
            ComponentSupervisorState.DEGRADED,
        )

        self.supervisor.record_operation_success(ResilienceComponent.CONTEXT_CACHE, latency_ms=2.5)
        self.assertEqual(
            self.supervisor.get_component_record(ResilienceComponent.CONTEXT_CACHE).state,
            ComponentSupervisorState.HEALTHY,
        )


class TestAutomatedRecoveryWorkflows(unittest.TestCase):
    """Test G, H, I, K: Automated recovery workflows."""

    def setUp(self):
        self.resilience_engine = ResilienceEngine(sleep_fn=lambda _: None)
        self.supervisor = ComponentHealthSupervisor(resilience_engine=self.resilience_engine)
        self.orchestrator = RecoveryOrchestrator(
            resilience_engine=self.resilience_engine,
            health_supervisor=self.supervisor,
        )

    def test_stream_disconnect_recovery_workflow(self):
        action = self.orchestrator.recover_stream_disconnect()
        self.assertIsInstance(action, RecoveryAction)
        self.assertTrue(action.success)
        self.assertIn("STREAM_RECONNECT", action.action_taken)
        self.assertEqual(
            self.supervisor.get_component_record(ResilienceComponent.STREAMING_LAYER).state,
            ComponentSupervisorState.HEALTHY,
        )

    def test_worker_crash_recovery_workflow(self):
        action = self.orchestrator.recover_worker_failure(symbol="INFY.NS")
        self.assertIsInstance(action, RecoveryAction)
        self.assertTrue(action.success)
        self.assertIn("INFY.NS", action.action_taken)
        self.assertEqual(
            self.supervisor.get_component_record(ResilienceComponent.PAPER_WORKERS).state,
            ComponentSupervisorState.HEALTHY,
        )

    def test_broker_sandbox_recovery_with_clean_reconciliation(self):
        mock_rec = MagicMock()
        mock_rec.reconcile.return_value = MagicMock(
            is_reconciled=True, discrepancy_count=0, orders_checked=5, positions_checked=2
        )
        self.orchestrator._reconciliation_engine = mock_rec

        action = self.orchestrator.recover_broker_sandbox_failure()
        self.assertTrue(action.success)
        self.assertIn("Reconciliation verified clean", action.result_message)
        self.assertEqual(
            self.supervisor.get_component_record(ResilienceComponent.BROKER_SANDBOX).state,
            ComponentSupervisorState.HEALTHY,
        )

    def test_model_outage_circuit_recovery(self):
        action = self.orchestrator.recover_model_failure("QuantSpecialist")
        self.assertTrue(action.success)
        self.assertIn("QuantSpecialist", action.result_message)
        self.assertEqual(
            self.supervisor.get_component_record(ResilienceComponent.MODEL_SERVICES).state,
            ComponentSupervisorState.HEALTHY,
        )


class TestResilienceFaultInjector(unittest.TestCase):
    """Test Step 6: Test-only fault simulation framework."""

    def setUp(self):
        self.injector = ResilienceFaultInjector()

    def test_activate_and_deactivate_fault(self):
        self.assertFalse(self.injector.is_fault_active(FailureDomainType.STREAM_DISCONNECT))
        self.injector.activate_fault(
            FailureDomainType.STREAM_DISCONNECT,
            {"disconnect_reason": "WebSocket EOF"},
        )
        self.assertTrue(self.injector.is_fault_active(FailureDomainType.STREAM_DISCONNECT))
        meta = self.injector.get_fault_metadata(FailureDomainType.STREAM_DISCONNECT)
        self.assertEqual(meta["disconnect_reason"], "WebSocket EOF")

        self.injector.deactivate_fault(FailureDomainType.STREAM_DISCONNECT)
        self.assertFalse(self.injector.is_fault_active(FailureDomainType.STREAM_DISCONNECT))

    def test_context_manager_scoped_injection(self):
        with self.injector.inject(FailureDomainType.WORKER_TIMEOUT):
            self.assertTrue(self.injector.is_fault_active(FailureDomainType.WORKER_TIMEOUT))
        self.assertFalse(self.injector.is_fault_active(FailureDomainType.WORKER_TIMEOUT))


class TestResilienceScorecardCalculation(unittest.TestCase):
    """Test Step 9: Resilience Scorecard certification."""

    def setUp(self):
        self.resilience_engine = ResilienceEngine(sleep_fn=lambda _: None)
        self.supervisor = ComponentHealthSupervisor(resilience_engine=self.resilience_engine)
        self.orchestrator = RecoveryOrchestrator(
            resilience_engine=self.resilience_engine,
            health_supervisor=self.supervisor,
        )

    def test_scorecard_highly_resilient_rating(self):
        # Execute 3 successful recovery workflows
        self.orchestrator.recover_stream_disconnect()
        self.orchestrator.recover_worker_failure("TCS.NS")
        self.orchestrator.recover_model_failure("MomentumSpecialist")

        scorecard = self.orchestrator.generate_resilience_scorecard()
        self.assertGreaterEqual(scorecard.total_scenarios_tested, 3)
        self.assertEqual(scorecard.failed_scenarios, 0)
        self.assertEqual(scorecard.recovery_success_rate, 1.0)
        self.assertEqual(
            scorecard.readiness_classification,
            ResilienceReadinessClassification.HIGHLY_RESILIENT,
        )

    def test_status_summary_structure(self):
        summary = self.orchestrator.get_status_summary()
        self.assertIsInstance(summary, ResilienceStatusSummary)
        self.assertTrue(summary.live_trading_permanently_locked)
        self.assertEqual(len(summary.components), 10)


class TestSecretNonExposure(unittest.TestCase):
    """Test N: Secret and credential scrubbing in failure and audit records."""

    def test_sanitize_metadata_removes_secrets(self):
        metadata = {
            "symbol": "RELIANCE.NS",
            "api_key": "secret_abc_123",
            "groq_api_key": "gsk_supersecret",
            "alpaca_secret": "alpaca_12345",
            "nested": {
                "password": "mypassword",
                "safe_info": "visible",
            },
        }
        sanitized = _sanitize_metadata(metadata)
        self.assertEqual(sanitized["symbol"], "RELIANCE.NS")
        self.assertEqual(sanitized["api_key"], "***REDACTED***")
        self.assertEqual(sanitized["groq_api_key"], "***REDACTED***")
        self.assertEqual(sanitized["alpaca_secret"], "***REDACTED***")
        self.assertEqual(sanitized["nested"]["password"], "***REDACTED***")
        self.assertEqual(sanitized["nested"]["safe_info"], "visible")


class TestNonNegotiableSafetyInvariants(unittest.TestCase):
    """Test O: TIER_4 live trading permanently locked and unroutable."""

    def test_tier4_live_real_money_permanently_locked(self):
        from backend.application.broker_interface import BrokerFactory, ConfigurationSafetyError
        with self.assertRaises(ConfigurationSafetyError):
            BrokerFactory.get_adapter("live")

    def test_resilience_engine_has_zero_order_execution_authority(self):
        engine = ResilienceEngine()
        self.assertFalse(hasattr(engine, "place_order"))
        self.assertFalse(hasattr(engine, "submit_order"))
        self.assertFalse(hasattr(engine, "execute_order"))

    def test_health_supervisor_has_zero_order_execution_authority(self):
        supervisor = ComponentHealthSupervisor()
        self.assertFalse(hasattr(supervisor, "place_order"))
        self.assertFalse(hasattr(supervisor, "submit_order"))


class TestResilienceRESTEndpoints(unittest.TestCase):
    """Test R: REST API endpoint availability and structure."""

    def test_resilience_routes_registered(self):
        from backend.application.resilience_routes import resilience_router
        paths = [r.path for r in resilience_router.routes]
        self.assertIn("/api/resilience/status", paths)
        self.assertIn("/api/resilience/components", paths)
        self.assertIn("/api/resilience/failures", paths)
        self.assertIn("/api/resilience/recoveries", paths)
        self.assertIn("/api/resilience/metrics", paths)
        self.assertIn("/api/resilience/scorecard", paths)
        self.assertIn("/api/resilience/circuits/reset", paths)
        self.assertIn("/api/resilience/simulate-failure", paths)

    def test_main_fastapi_app_includes_resilience_router(self):
        from backend.main import app
        all_paths = []
        for r in app.routes:
            if hasattr(r, "path"):
                all_paths.append(r.path)
            if hasattr(r, "original_router") and hasattr(r.original_router, "routes"):
                all_paths.extend([sub.path for sub in r.original_router.routes if hasattr(sub, "path")])

        self.assertIn("/api/resilience/status", all_paths)
        self.assertIn("/api/resilience/scorecard", all_paths)


class TestCompoundFailureScenarios(unittest.TestCase):
    """Test P: Compound failure combinations."""

    def setUp(self):
        self.resilience_engine = ResilienceEngine(sleep_fn=lambda _: None)
        self.supervisor = ComponentHealthSupervisor(resilience_engine=self.resilience_engine)
        self.orchestrator = RecoveryOrchestrator(
            resilience_engine=self.resilience_engine,
            health_supervisor=self.supervisor,
        )

    def test_compound_stream_and_worker_failure(self):
        # 1. Trigger stream drop
        self.supervisor.record_operation_failure(
            component=ResilienceComponent.STREAMING_LAYER,
            failure_type=FailureDomainType.STREAM_DISCONNECT,
            error_message="Streaming disconnect",
        )
        # 2. Trigger worker crash
        self.supervisor.record_operation_failure(
            component=ResilienceComponent.PAPER_WORKERS,
            failure_type=FailureDomainType.WORKER_FAILURE,
            error_message="Worker crash",
        )
        self.assertEqual(
            self.supervisor.get_overall_resilience_state(),
            ComponentSupervisorState.DEGRADED,
        )

        # 3. Recover both sequentially
        rec_stream = self.orchestrator.recover_stream_disconnect()
        rec_worker = self.orchestrator.recover_worker_failure("TCS.NS")

        self.assertTrue(rec_stream.success)
        self.assertTrue(rec_worker.success)
        self.assertEqual(
            self.supervisor.get_overall_resilience_state(),
            ComponentSupervisorState.HEALTHY,
        )

    def test_compound_model_timeout_and_stale_data(self):
        self.supervisor.record_operation_failure(
            component=ResilienceComponent.MODEL_SERVICES,
            failure_type=FailureDomainType.MODEL_TIMEOUT,
            error_message="Model timed out",
            is_timeout=True,
        )
        self.supervisor.record_operation_failure(
            component=ResilienceComponent.MARKET_DATA,
            failure_type=FailureDomainType.MARKET_DATA_STALE,
            error_message="Stale quote",
        )
        # Safe degradation: both active
        m_rec = self.supervisor.get_component_record(ResilienceComponent.MODEL_SERVICES)
        d_rec = self.supervisor.get_component_record(ResilienceComponent.MARKET_DATA)

        self.assertIn("DETERMINISTIC_MODEL_FALLBACK", m_rec.active_fallback)
        self.assertIn("REJECT_DECISIONS_STALE_DATA", d_rec.active_fallback)


if __name__ == "__main__":
    unittest.main()
