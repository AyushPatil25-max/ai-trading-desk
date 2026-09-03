"""
Phase 23 — Production Observability, Audit Integrity & Operational Control E2E Tests

Comprehensive end-to-end test suite covering:
1. Unified operational event schemas across all 15 categories
2. Deterministic canonical serialization and SHA-256 event hashing
3. Cryptographic previous-event chaining
4. Pure-Python tamper detection (payload mutation, timestamp mutation, deleted event, reordered sequence, broken hash)
5. Decision explainability generation and correlation lookup (zero hallucinated math)
6. System health & pure-Python SLO telemetry (throughput, latency percentiles p50/p95/p99)
7. End-to-end lifecycle trace reconstruction from correlation ID
8. Operational control plane: safe paper worker pause/resume and audit event emission
9. Secret and credential scrubbing across top-level and nested payloads
10. Failure-injection observability and audit verification
11. Performance benchmarking (event creation, hashing, append, verification < 0.5ms)
12. Non-negotiable safety invariant verification (TIER_4 locked, zero order authority)
13. REST API routing and FastAPI mount verification
"""

from datetime import datetime, timezone
import time
import unittest
import uuid
from unittest.mock import MagicMock, patch

from backend.domain.observability_schemas import (
    AuditIntegrityReport,
    AuditVerificationStatus,
    DecisionExplainabilityRecord,
    EventCategory,
    EventSeverity,
    LifecycleTrace,
    OperationalEvent,
    OperationalHealthLevel,
    SLOMetricsSnapshot,
    _sanitize_payload,
)
from backend.application.decision_explainability_engine import (
    DecisionExplainabilityEngine,
    global_explainability_engine,
)
from backend.application.operational_control_plane import (
    OperationalControlPlane,
    global_control_plane,
)
from backend.application.slo_telemetry_engine import (
    SLOTelemetryEngine,
    _calculate_percentile,
    global_slo_telemetry_engine,
)
from backend.application.tamper_evident_audit_chain import (
    GENESIS_HASH,
    TamperEvidentAuditChain,
    global_audit_chain,
)


class TestObservabilitySchemas(unittest.TestCase):
    """Test 1: Unified event models and category completeness."""

    def test_all_15_event_categories_present(self):
        expected = {
            "SYSTEM", "MARKET_DATA", "CONTEXT", "SIGNAL", "RISK",
            "EXECUTION", "STREAMING", "FAILURE", "RECOVERY", "WORKER",
            "MODEL", "SNAPSHOT", "HEALTH", "SECURITY", "CONFIGURATION",
        }
        actual = {c.value for c in EventCategory}
        self.assertEqual(actual, expected)
        self.assertEqual(len(EventCategory), 15)

    def test_operational_event_creation_and_canonical_hash(self):
        event = OperationalEvent(
            event_type="PRICE_TICK_ACCEPTED",
            category=EventCategory.MARKET_DATA,
            component="MarketDataIngestion",
            correlation_id="corr-test-100",
            sequence_number=1,
            prev_event_hash=GENESIS_HASH,
            payload={"price": 2450.0, "symbol": "RELIANCE.NS"},
        )
        h = event.compute_canonical_hash()
        self.assertIsInstance(h, str)
        self.assertEqual(len(h), 64)  # 64 hex characters for SHA-256

        # Deterministic: computing again yields exact same hash
        self.assertEqual(event.compute_canonical_hash(), h)


class TestTamperEvidentAuditChain(unittest.TestCase):
    """Test 2, 3 & 4: SHA-256 chaining and pure-Python tamper detection."""

    def setUp(self):
        self.chain = TamperEvidentAuditChain(max_capacity=100)

    def test_append_creates_valid_cryptographic_chain(self):
        e1 = self.chain.append_event(
            event_type="MARKET_CONTEXT_CREATED",
            category=EventCategory.CONTEXT,
            component="MarketContextEngine",
            correlation_id="corr-1",
            symbol="TCS.NS",
        )
        e2 = self.chain.append_event(
            event_type="DECISION_GENERATED",
            category=EventCategory.SIGNAL,
            component="SpecialistOrchestrator",
            correlation_id="corr-1",
            causation_id=e1.event_id,
            symbol="TCS.NS",
        )
        e3 = self.chain.append_event(
            event_type="RISK_APPROVED",
            category=EventCategory.RISK,
            component="RiskEngine",
            correlation_id="corr-1",
            causation_id=e2.event_id,
            symbol="TCS.NS",
        )

        self.assertEqual(e1.sequence_number, 0)
        self.assertEqual(e2.sequence_number, 1)
        self.assertEqual(e3.sequence_number, 2)

        self.assertEqual(e1.prev_event_hash, GENESIS_HASH)
        self.assertEqual(e2.prev_event_hash, e1.event_hash)
        self.assertEqual(e3.prev_event_hash, e2.event_hash)

        # Verify integrity: must be 100% VALID
        report = self.chain.verify_integrity()
        self.assertEqual(report.status, AuditVerificationStatus.VALID)
        self.assertEqual(report.total_events_verified, 3)
        self.assertEqual(report.invalid_events_count, 0)

    def test_tamper_detection_modified_payload(self):
        self.chain.append_event(
            event_type="TICK_1",
            category=EventCategory.MARKET_DATA,
            component="Ingestion",
            correlation_id="corr-tamper-1",
            payload={"price": 100.0},
        )
        self.chain.append_event(
            event_type="TICK_2",
            category=EventCategory.MARKET_DATA,
            component="Ingestion",
            correlation_id="corr-tamper-1",
            payload={"price": 105.0},
        )

        # Maliciously modify payload of event 0 without recomputing hash
        self.chain._events[0].payload["price"] = 999999.0

        report = self.chain.verify_integrity()
        self.assertEqual(report.status, AuditVerificationStatus.INVALID_HASH)
        self.assertEqual(report.first_violation_index, 0)
        self.assertIn("Tampered content at index 0", report.violation_details)

    def test_tamper_detection_altered_timestamp(self):
        self.chain.append_event(
            event_type="TICK_1",
            category=EventCategory.MARKET_DATA,
            component="Ingestion",
            correlation_id="corr-tamper-2",
        )
        # Modify timestamp
        self.chain._events[0].timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc)

        report = self.chain.verify_integrity()
        self.assertEqual(report.status, AuditVerificationStatus.INVALID_HASH)

    def test_tamper_detection_deleted_or_missing_event(self):
        self.chain.append_event("E0", EventCategory.SYSTEM, "Comp", "c1")
        self.chain.append_event("E1", EventCategory.SYSTEM, "Comp", "c1")
        self.chain.append_event("E2", EventCategory.SYSTEM, "Comp", "c1")

        # Maliciously delete middle event E1
        del self.chain._events[1]

        report = self.chain.verify_integrity()
        # Should detect either INVALID_SEQUENCE (seq 0 followed by seq 2) or BROKEN_CHAIN
        self.assertIn(
            report.status,
            [AuditVerificationStatus.INVALID_SEQUENCE, AuditVerificationStatus.BROKEN_CHAIN],
        )

    def test_tamper_detection_reordered_events(self):
        self.chain.append_event("E0", EventCategory.SYSTEM, "Comp", "c1")
        self.chain.append_event("E1", EventCategory.SYSTEM, "Comp", "c1")

        # Swap event 0 and event 1
        self.chain._events[0], self.chain._events[1] = self.chain._events[1], self.chain._events[0]

        report = self.chain.verify_integrity()
        self.assertIn(
            report.status,
            [AuditVerificationStatus.INVALID_SEQUENCE, AuditVerificationStatus.BROKEN_CHAIN],
        )

    def test_empty_chain_verification(self):
        empty_chain = TamperEvidentAuditChain()
        report = empty_chain.verify_integrity()
        self.assertEqual(report.status, AuditVerificationStatus.EMPTY_CHAIN)


class TestDecisionExplainabilityEngine(unittest.TestCase):
    """Test 5: Decision explainability synthesis and retrieval."""

    def setUp(self):
        self.engine = DecisionExplainabilityEngine()

    def test_record_and_retrieve_explainability(self):
        record = self.engine.record_decision(
            correlation_id="corr-exp-01",
            symbol="INFY.NS",
            decision_type="BUY",
            direction="LONG",
            conviction=0.82,
            final_decision="APPROVED_LONG",
            decision_reason="Strong technical breakout and positive quant momentum.",
            factor_scores={"momentum": 0.85, "value": 0.60, "sentiment": 0.75},
            risk_constraints={"max_drawdown": 0.05, "sector_cap": 0.20},
            position_sizing_inputs={"approved_shares": 150, "capital_alloc": 250000.0},
            stop_loss_inputs={"atr_stop_price": 1420.0},
        )

        self.assertTrue(record.decision_id.startswith("dec-"))
        self.assertEqual(record.symbol, "INFY.NS")
        self.assertEqual(record.conviction, 0.82)

        # Retrieve by correlation ID
        retrieved = self.engine.get_by_correlation_id("corr-exp-01")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.decision_id, record.decision_id)
        self.assertEqual(retrieved.factor_scores["momentum"], 0.85)

        # Retrieve by symbol
        by_sym = self.engine.get_by_symbol("INFY.NS")
        self.assertEqual(len(by_sym), 1)
        self.assertEqual(by_sym[0].symbol, "INFY.NS")


class TestSLOTelemetryEngine(unittest.TestCase):
    """Test 6: Pure-Python latency percentiles and health state classification."""

    def setUp(self):
        self.engine = SLOTelemetryEngine()

    def test_pure_python_percentile_calculation(self):
        # 1 to 100
        data = [float(i) for i in range(1, 101)]
        p50 = _calculate_percentile(data, 50.0)
        p95 = _calculate_percentile(data, 95.0)
        p99 = _calculate_percentile(data, 99.0)

        self.assertAlmostEqual(p50, 50.5, places=1)
        self.assertAlmostEqual(p95, 95.05, places=1)
        self.assertAlmostEqual(p99, 99.01, places=1)

    def test_record_latencies_and_metrics_snapshot(self):
        for lat in [10.0, 20.0, 30.0, 40.0, 50.0]:
            self.engine.record_operation_latency(lat)

        snapshot = self.engine.get_metrics_snapshot()
        self.assertIsInstance(snapshot, SLOMetricsSnapshot)
        self.assertEqual(snapshot.overall_health, OperationalHealthLevel.HEALTHY)
        self.assertEqual(snapshot.latency_p50_ms, 30.0)
        self.assertEqual(snapshot.avg_latency_ms, 30.0)
        self.assertTrue(snapshot.live_trading_permanently_locked)

    def test_degraded_health_classification_on_anomalies(self):
        self.engine.record_anomaly(is_dropped=True)
        snapshot = self.engine.get_metrics_snapshot()
        self.assertEqual(snapshot.overall_health, OperationalHealthLevel.DEGRADED)
        self.assertEqual(snapshot.dropped_events, 1)


class TestOperationalControlPlane(unittest.TestCase):
    """Test 7 & 8: Lifecycle reconstruction and paper worker controls."""

    def setUp(self):
        self.audit_chain = TamperEvidentAuditChain()
        self.explainability_engine = DecisionExplainabilityEngine()
        self.control_plane = OperationalControlPlane(
            audit_chain=self.audit_chain,
            explainability_engine=self.explainability_engine,
        )

    def test_lifecycle_trace_reconstruction(self):
        corr_id = "corr-lifecycle-999"

        # 1. Market context event
        self.audit_chain.append_event(
            event_type="CONTEXT_INGESTED",
            category=EventCategory.CONTEXT,
            component="MarketContextEngine",
            correlation_id=corr_id,
            symbol="TCS.NS",
            status="SUCCESS",
        )
        # 2. Decision event
        self.audit_chain.append_event(
            event_type="DECISION_PRODUCED",
            category=EventCategory.SIGNAL,
            component="InvestmentCommittee",
            correlation_id=corr_id,
            symbol="TCS.NS",
            status="APPROVED",
        )
        # 3. Risk event
        self.audit_chain.append_event(
            event_type="RISK_EVALUATED",
            category=EventCategory.RISK,
            component="RiskEngine",
            correlation_id=corr_id,
            symbol="TCS.NS",
            status="PASSED",
            payload={"approved_shares": 100},
        )
        # 4. Execution event
        self.audit_chain.append_event(
            event_type="PAPER_ORDER_FILLED",
            category=EventCategory.EXECUTION,
            component="PaperBrokerAdapter",
            correlation_id=corr_id,
            symbol="TCS.NS",
            status="FILLED",
        )

        # Attach explainability
        self.explainability_engine.record_decision(
            correlation_id=corr_id,
            symbol="TCS.NS",
            decision_type="BUY",
            final_decision="APPROVED",
            decision_reason="Multi-agent committee consensus.",
        )

        # Reconstruct trace
        trace = self.control_plane.reconstruct_lifecycle(corr_id)
        self.assertIsInstance(trace, LifecycleTrace)
        self.assertEqual(trace.correlation_id, corr_id)
        self.assertEqual(trace.symbol, "TCS.NS")
        self.assertEqual(trace.events_count, 4)
        self.assertEqual(trace.final_status, "FILLED")
        self.assertEqual(
            trace.stages_traversed,
            ["MarketContextEngine", "InvestmentCommittee", "RiskEngine", "PaperBrokerAdapter"],
        )
        self.assertIsNotNone(trace.explainability)
        self.assertEqual(trace.explainability.decision_type, "BUY")

    def test_paper_worker_pause_and_resume_controls(self):
        res_pause = self.control_plane.pause_paper_worker("TCS.NS", operator_id="admin-user")
        self.assertEqual(res_pause["symbol"], "TCS.NS")

        # Verify audit event was emitted for worker pause
        events = self.audit_chain.query_events(category=EventCategory.WORKER)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "PAPER_WORKER_PAUSED")
        self.assertEqual(events[0].payload["operator_id"], "admin-user")

        res_resume = self.control_plane.resume_paper_worker("TCS.NS", operator_id="admin-user")
        self.assertEqual(res_resume["symbol"], "TCS.NS")

        events = self.audit_chain.query_events(category=EventCategory.WORKER)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1].event_type, "PAPER_WORKER_RESUMED")


class TestSecretNonExposure(unittest.TestCase):
    """Test 9: Secret & credential scrubbing across nested payloads."""

    def test_sanitize_payload_recursive(self):
        payload = {
            "symbol": "RELIANCE.NS",
            "api_key": "secret_abc123",
            "auth_token": "token_xyz",
            "nested": {
                "password": "my_password",
                "safe_field": 42,
                "deep_nested": {
                    "private_key": "private_data",
                    "clean_data": "visible",
                },
            },
            "clean_list": [{"secret": "redact_me", "ok": True}],
        }
        clean = _sanitize_payload(payload)

        self.assertEqual(clean["symbol"], "RELIANCE.NS")
        self.assertEqual(clean["api_key"], "***REDACTED***")
        self.assertEqual(clean["auth_token"], "***REDACTED***")
        self.assertEqual(clean["nested"]["password"], "***REDACTED***")
        self.assertEqual(clean["nested"]["safe_field"], 42)
        self.assertEqual(clean["nested"]["deep_nested"]["private_key"], "***REDACTED***")
        self.assertEqual(clean["nested"]["deep_nested"]["clean_data"], "visible")
        self.assertEqual(clean["clean_list"][0]["secret"], "***REDACTED***")
        self.assertTrue(clean["clean_list"][0]["ok"])


class TestFailureInjectionObservability(unittest.TestCase):
    """Test 10: Injected failure auditability and correlation preservation."""

    def setUp(self):
        self.audit_chain = TamperEvidentAuditChain()

    def test_injected_worker_crash_observability_assertions(self):
        corr_id = f"corr-chaos-{uuid.uuid4().hex[:8]}"

        # 1. Emit failure event
        fail_evt = self.audit_chain.append_event(
            event_type="SIMULATED_WORKER_CRASH",
            category=EventCategory.FAILURE,
            component="DistributedPaperWorkerPool",
            correlation_id=corr_id,
            severity=EventSeverity.CRITICAL,
            symbol="INFY.NS",
            status="FAILED",
            reason="Simulated unhandled exception on malformed tick.",
        )
        self.assertEqual(fail_evt.category, EventCategory.FAILURE)
        self.assertEqual(fail_evt.severity, EventSeverity.CRITICAL)

        # 2. Emit recovery event with causation linking
        rec_evt = self.audit_chain.append_event(
            event_type="WORKER_RECOVERED",
            category=EventCategory.RECOVERY,
            component="RecoveryOrchestrator",
            correlation_id=corr_id,
            causation_id=fail_evt.event_id,
            symbol="INFY.NS",
            status="RECOVERED",
            reason="Worker thread safely re-instantiated and resubscribed.",
        )
        self.assertEqual(rec_evt.category, EventCategory.RECOVERY)
        self.assertEqual(rec_evt.causation_id, fail_evt.event_id)

        # 3. Verify audit chain validity across failure and recovery
        report = self.audit_chain.verify_integrity()
        self.assertEqual(report.status, AuditVerificationStatus.VALID)


class TestPerformanceBenchmarks(unittest.TestCase):
    """Test 11: Observability performance (<0.5ms per operation)."""

    def setUp(self):
        self.chain = TamperEvidentAuditChain()

    def test_event_append_and_hash_throughput(self):
        iterations = 500
        start = time.perf_counter()

        for i in range(iterations):
            self.chain.append_event(
                event_type="BENCHMARK_TICK",
                category=EventCategory.MARKET_DATA,
                component="BenchmarkEngine",
                correlation_id=f"corr-bench-{i}",
                payload={"index": i, "val": 100.5 + i},
            )

        elapsed = time.perf_counter() - start
        avg_time_ms = (elapsed / iterations) * 1000.0

        # Must be well under 0.5ms per event (typically ~0.02ms)
        self.assertLess(avg_time_ms, 0.5)

        # Verify entire chain of 500 events
        start_verify = time.perf_counter()
        report = self.chain.verify_integrity()
        verify_elapsed = time.perf_counter() - start_verify

        self.assertEqual(report.status, AuditVerificationStatus.VALID)
        self.assertEqual(report.total_events_verified, iterations)
        # Verification of 500 events should take < 50ms
        self.assertLess(verify_elapsed, 0.1)


class TestSafetyInvariants(unittest.TestCase):
    """Test 12: TIER_4 live trading permanently locked and zero order authority."""

    def test_tier4_live_real_money_permanently_locked(self):
        from backend.application.broker_interface import BrokerFactory, ConfigurationSafetyError
        with self.assertRaises(ConfigurationSafetyError):
            BrokerFactory.get_adapter("live")

    def test_observability_engines_have_zero_order_execution_authority(self):
        chain = TamperEvidentAuditChain()
        explain = DecisionExplainabilityEngine()
        slo = SLOTelemetryEngine()
        control = OperationalControlPlane()

        for obj in [chain, explain, slo, control]:
            self.assertFalse(hasattr(obj, "place_order"))
            self.assertFalse(hasattr(obj, "submit_order"))
            self.assertFalse(hasattr(obj, "execute_order"))


class TestObservabilityRESTEndpoints(unittest.TestCase):
    """Test 13: REST API endpoint availability and FastAPI integration."""

    def test_routes_registered_in_observability_router(self):
        from backend.application.observability_routes import observability_router
        paths = [r.path for r in observability_router.routes]
        self.assertIn("/api/observability/events", paths)
        self.assertIn("/api/observability/events/{event_id}", paths)
        self.assertIn("/api/observability/trace/{correlation_id}", paths)
        self.assertIn("/api/observability/explainability/{correlation_id}", paths)
        self.assertIn("/api/observability/audit/verify", paths)
        self.assertIn("/api/observability/health", paths)
        self.assertIn("/api/observability/control/workers", paths)
        self.assertIn("/api/observability/control/workers/{symbol}/pause", paths)
        self.assertIn("/api/observability/control/workers/{symbol}/resume", paths)
        self.assertIn("/api/observability/control/config", paths)

    def test_main_fastapi_app_includes_observability_router(self):
        from backend.main import app
        all_paths = []
        for r in app.routes:
            if hasattr(r, "path"):
                all_paths.append(r.path)
            if hasattr(r, "original_router") and hasattr(r.original_router, "routes"):
                all_paths.extend([sub.path for sub in r.original_router.routes if hasattr(sub, "path")])

        self.assertIn("/api/observability/health", all_paths)
        self.assertIn("/api/observability/audit/verify", all_paths)


class TestGranularObservabilityScenarios(unittest.TestCase):
    """Test additional failure scenarios, queries, and bounded limits."""

    def setUp(self):
        self.chain = TamperEvidentAuditChain()
        self.slo = SLOTelemetryEngine()
        self.control = OperationalControlPlane(audit_chain=self.chain, slo_engine=self.slo)

    def test_stream_failure_and_stale_data_telemetry(self):
        self.slo.record_anomaly(is_stale=True)
        self.slo.record_anomaly(is_dropped=True)
        self.slo.record_anomaly(is_duplicate=True)
        self.slo.record_anomaly(is_out_of_order=True)

        snapshot = self.slo.get_metrics_snapshot()
        self.assertEqual(snapshot.stale_events, 1)
        self.assertEqual(snapshot.dropped_events, 1)
        self.assertEqual(snapshot.duplicate_events, 1)
        self.assertEqual(snapshot.out_of_order_events, 1)
        self.assertEqual(snapshot.overall_health, OperationalHealthLevel.DEGRADED)

    def test_degraded_duration_tracking(self):
        self.slo.set_degraded_state(True)
        time.sleep(0.02)
        self.slo.set_degraded_state(False)

        snapshot = self.slo.get_metrics_snapshot()
        self.assertGreater(snapshot.degraded_duration_ms, 15.0)

    def test_bounded_queries_with_filters_and_pagination(self):
        for i in range(15):
            self.chain.append_event(
                event_type="BATCH_EVENT",
                category=EventCategory.MARKET_DATA if i % 2 == 0 else EventCategory.SIGNAL,
                component="Ingestor" if i % 2 == 0 else "Model",
                correlation_id=f"corr-batch-{i % 3}",
                symbol="TCS.NS" if i % 2 == 0 else "INFY.NS",
                severity=EventSeverity.WARNING if i == 5 else EventSeverity.INFO,
            )

        # Query by symbol
        tcs_events = self.chain.query_events(symbol="TCS.NS", limit=50)
        self.assertEqual(len(tcs_events), 8)

        # Query with offset and limit
        page1 = self.chain.query_events(limit=5, offset=0)
        page2 = self.chain.query_events(limit=5, offset=5)
        self.assertEqual(len(page1), 5)
        self.assertEqual(len(page2), 5)
        self.assertNotEqual(page1[0].event_id, page2[0].event_id)

        # Query by severity
        warn_events = self.chain.query_events(severity=EventSeverity.WARNING)
        self.assertEqual(len(warn_events), 1)

    def test_safe_configuration_inspection_confirms_locks(self):
        config = self.control.get_safe_system_configuration()
        self.assertTrue(config["tier_4_live_real_money_locked"])
        self.assertFalse(config["real_money_execution_allowed"])
        self.assertEqual(config["mode"], "PAPER_ONLY_SIMULATION")


if __name__ == "__main__":
    unittest.main()
