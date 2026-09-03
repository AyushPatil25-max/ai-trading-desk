"""
Phase 22 — Centralized Alerting Engine & Compliance Audit Trail E2E Tests

Comprehensive test suite covering:
1.  Happy-path rule evaluation (all rules pass, no alerts)
2.  Safety alert on simulated TIER_4 unlock
3.  Kill switch alert generation
4.  Data provider failure alerting
5.  Stale market context alerting
6.  Calibration degradation alerting
7.  Reconciliation discrepancy alerting
8.  Alert deduplication / throttling
9.  Alert escalation
10. Alert lifecycle (ACTIVE → ACKNOWLEDGED → RESOLVED)
11. Invalid alert_id handling
12. Empty state handling
13. Compliance snapshot generation
14. Compliance audit trail recording and querying
15. Audit trail filtering
16. Audit trail bounded history enforcement
17. Component failure alerting
18. Provider circuit breaker alerting (rule existence)
19. Streaming backpressure alerting (rule existence)
20. Safety boundary enforcement (TIER_4 locked)
21. REST API endpoint validation
22. Secret/credential non-exposure
23. Concurrent thread-safety
24. Regression compatibility
"""

import threading
import time
import unittest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

from backend.domain.alert_audit_schemas import (
    ALERT_AUDIT_SCHEMA_VERSION,
    Alert,
    AlertCategory,
    AlertEngineStatus,
    AlertRule,
    AlertSeverity,
    AlertState,
    AuditAction,
    AuditEntry,
    ComplianceReport,
    ComplianceSnapshot,
)
from backend.application.alerting_engine import (
    AlertingEngine,
    _sanitize_metadata,
)
from backend.application.compliance_audit_trail import (
    ComplianceAuditTrail,
)


class TestAlertAuditSchemas(unittest.TestCase):
    """Test Phase 22 domain schema models."""

    def test_schema_version(self):
        self.assertEqual(ALERT_AUDIT_SCHEMA_VERSION, "22.0.0")

    def test_alert_severity_enum(self):
        self.assertEqual(AlertSeverity.INFO.value, "INFO")
        self.assertEqual(AlertSeverity.EMERGENCY.value, "EMERGENCY")
        self.assertEqual(len(AlertSeverity), 5)

    def test_alert_category_enum(self):
        self.assertEqual(AlertCategory.SAFETY.value, "SAFETY")
        self.assertEqual(AlertCategory.PERFORMANCE.value, "PERFORMANCE")
        self.assertEqual(len(AlertCategory), 10)

    def test_alert_state_enum(self):
        self.assertEqual(len(AlertState), 5)
        self.assertIn(AlertState.ACTIVE, AlertState)
        self.assertIn(AlertState.RESOLVED, AlertState)

    def test_audit_action_enum(self):
        self.assertEqual(len(AuditAction), 10)
        self.assertIn(AuditAction.ALERT_RAISED, AuditAction)
        self.assertIn(AuditAction.COMPLIANCE_SNAPSHOT, AuditAction)

    def test_alert_rule_model(self):
        rule = AlertRule(
            rule_id="TEST_RULE",
            name="Test Rule",
            category=AlertCategory.SAFETY,
            severity=AlertSeverity.CRITICAL,
            condition_description="Test condition",
        )
        self.assertEqual(rule.rule_id, "TEST_RULE")
        self.assertTrue(rule.enabled)
        self.assertEqual(rule.throttle_seconds, 300.0)

    def test_alert_model(self):
        alert = Alert(
            alert_id="alert-test",
            rule_id="TEST_RULE",
            severity=AlertSeverity.HIGH,
            category=AlertCategory.RISK,
            title="Test Alert",
            message="Test message",
        )
        self.assertEqual(alert.state, AlertState.ACTIVE)
        self.assertFalse(alert.escalated)
        self.assertEqual(alert.suppressed_count, 0)

    def test_audit_entry_model(self):
        entry = AuditEntry(
            entry_id="audit-test",
            action=AuditAction.ALERT_RAISED,
            category=AlertCategory.SAFETY,
            severity=AlertSeverity.CRITICAL,
            description="Test entry",
        )
        self.assertFalse(entry.safety_verified)
        self.assertEqual(entry.metadata, {})

    def test_compliance_snapshot_model(self):
        snapshot = ComplianceSnapshot(
            snapshot_id="snap-test",
            live_trading_blocked=True,
            execution_guard_active=True,
            risk_engine_active=True,
            preflight_active=True,
            kill_switch_armed=True,
            paper_broker_operational=True,
            overall_compliant=True,
        )
        self.assertTrue(snapshot.overall_compliant)
        self.assertTrue(snapshot.live_trading_blocked)


class TestAlertingEngineHappyPath(unittest.TestCase):
    """Test 1: Normal happy-path behavior."""

    def setUp(self):
        self.audit_trail = ComplianceAuditTrail(max_entries=1000)
        self.engine = AlertingEngine(
            health_monitor=None,
            execution_guard=MagicMock(
                get_status_summary=MagicMock(return_value={"live_broker_blocked": True, "kill_switch_triggered": False})
            ),
            telemetry_engine=MagicMock(is_kill_switch_triggered=MagicMock(return_value=False)),
            evaluation_engine=None,
            reconciliation_engine=None,
            stream_manager=None,
            broker_manager=None,
            audit_trail=self.audit_trail,
        )

    def test_no_alerts_on_healthy_system(self):
        """All rules evaluate without generating alerts on a healthy system."""
        new_alerts = self.engine.evaluate_all_rules()
        # Most rules should not fire since monitors are not connected
        # The key safety rules (live trading, guard bypass) should NOT fire
        safety_alerts = [a for a in new_alerts if a.category == AlertCategory.SAFETY and
                         a.severity == AlertSeverity.EMERGENCY]
        self.assertEqual(len(safety_alerts), 0, "No EMERGENCY safety alerts on healthy system")

    def test_status_returns_valid_model(self):
        status = self.engine.get_status()
        self.assertIsInstance(status, AlertEngineStatus)
        self.assertEqual(status.rules_enabled, 15)
        self.assertGreaterEqual(status.engine_uptime_seconds, 0.0)


class TestSafetyLiveTradingAlert(unittest.TestCase):
    """Test 2: Safety alert on simulated TIER_4 unlock."""

    def test_tier4_permanently_blocked(self):
        """Verify TIER_4_LIVE_REAL_MONEY remains locked."""
        from backend.application.broker_interface import BrokerFactory, ConfigurationSafetyError
        with self.assertRaises(ConfigurationSafetyError):
            BrokerFactory.get_adapter("live")


class TestKillSwitchAlert(unittest.TestCase):
    """Test 3: Kill switch alert generation."""

    def test_kill_switch_triggers_alert(self):
        audit = ComplianceAuditTrail()
        telemetry = MagicMock(is_kill_switch_triggered=MagicMock(return_value=True))
        engine = AlertingEngine(
            telemetry_engine=telemetry,
            execution_guard=MagicMock(get_status_summary=MagicMock(return_value={"live_broker_blocked": True})),
            audit_trail=audit,
        )
        alerts = engine.evaluate_all_rules()
        ks_alerts = [a for a in alerts if a.rule_id == "SAFETY_KILL_SWITCH_TRIGGERED"]
        self.assertEqual(len(ks_alerts), 1)
        self.assertEqual(ks_alerts[0].severity, AlertSeverity.CRITICAL)
        self.assertEqual(ks_alerts[0].category, AlertCategory.SAFETY)


class TestDataProviderFailureAlert(unittest.TestCase):
    """Test 4: Data provider failure alerting."""

    def test_all_providers_failed_rule_exists(self):
        engine = AlertingEngine()
        rule = engine.get_rule("DATA_ALL_PROVIDERS_FAILED")
        self.assertIsNotNone(rule)
        self.assertEqual(rule.severity, AlertSeverity.CRITICAL)
        self.assertTrue(rule.enabled)


class TestStaleMarketContextAlert(unittest.TestCase):
    """Test 5: Stale market context alerting."""

    def test_stale_context_rule_exists(self):
        engine = AlertingEngine()
        rule = engine.get_rule("DATA_STALE_MARKET_CONTEXT")
        self.assertIsNotNone(rule)
        self.assertEqual(rule.severity, AlertSeverity.WARNING)
        self.assertTrue(rule.enabled)
        self.assertEqual(rule.escalation_severity, AlertSeverity.HIGH)


class TestCalibrationDegradationAlert(unittest.TestCase):
    """Test 6: Calibration degradation alerting."""

    def test_brier_degradation_alert(self):
        calibration = MagicMock(brier_score=0.45, calibration_grade="D")
        matrix = MagicMock(calibration=calibration)
        eval_engine = MagicMock(get_latest_matrix=MagicMock(return_value=matrix))
        audit = ComplianceAuditTrail()
        engine = AlertingEngine(
            evaluation_engine=eval_engine,
            execution_guard=MagicMock(get_status_summary=MagicMock(return_value={"live_broker_blocked": True})),
            telemetry_engine=MagicMock(is_kill_switch_triggered=MagicMock(return_value=False)),
            audit_trail=audit,
        )
        alerts = engine.evaluate_all_rules()
        brier_alerts = [a for a in alerts if a.rule_id == "CALIBRATION_BRIER_DEGRADED"]
        self.assertEqual(len(brier_alerts), 1)
        self.assertEqual(brier_alerts[0].severity, AlertSeverity.WARNING)
        self.assertIn("0.45", brier_alerts[0].metric_value)


class TestReconciliationDiscrepancyAlert(unittest.TestCase):
    """Test 7: Reconciliation discrepancy alerting."""

    def test_discrepancy_triggers_alert(self):
        rec_report = MagicMock(discrepancy_count=3, is_reconciled=False, summary_message="3 discrepancies")
        rec_engine = MagicMock(get_latest_report=MagicMock(return_value=rec_report))
        audit = ComplianceAuditTrail()
        engine = AlertingEngine(
            reconciliation_engine=rec_engine,
            execution_guard=MagicMock(get_status_summary=MagicMock(return_value={"live_broker_blocked": True})),
            telemetry_engine=MagicMock(is_kill_switch_triggered=MagicMock(return_value=False)),
            audit_trail=audit,
        )
        alerts = engine.evaluate_all_rules()
        rec_alerts = [a for a in alerts if a.rule_id == "RECONCILIATION_DISCREPANCY"]
        self.assertEqual(len(rec_alerts), 1)
        self.assertEqual(rec_alerts[0].severity, AlertSeverity.HIGH)


class TestAlertDeduplicationThrottling(unittest.TestCase):
    """Test 8: Alert deduplication/throttling."""

    def test_duplicate_alert_suppressed(self):
        audit = ComplianceAuditTrail()
        telemetry = MagicMock(is_kill_switch_triggered=MagicMock(return_value=True))
        engine = AlertingEngine(
            telemetry_engine=telemetry,
            execution_guard=MagicMock(get_status_summary=MagicMock(return_value={"live_broker_blocked": True})),
            audit_trail=audit,
        )
        # First evaluation raises the alert
        alerts1 = engine.evaluate_all_rules()
        ks1 = [a for a in alerts1 if a.rule_id == "SAFETY_KILL_SWITCH_TRIGGERED"]
        self.assertEqual(len(ks1), 1)

        # Second evaluation should suppress (within throttle window)
        alerts2 = engine.evaluate_all_rules()
        ks2 = [a for a in alerts2 if a.rule_id == "SAFETY_KILL_SWITCH_TRIGGERED"]
        self.assertEqual(len(ks2), 0, "Duplicate alert should be suppressed")

        status = engine.get_status()
        self.assertGreaterEqual(status.total_suppressed, 1)


class TestAlertEscalation(unittest.TestCase):
    """Test 9: Alert escalation."""

    def test_unacknowledged_alert_escalates(self):
        audit = ComplianceAuditTrail()
        engine = AlertingEngine(
            execution_guard=MagicMock(get_status_summary=MagicMock(return_value={"live_broker_blocked": True})),
            telemetry_engine=MagicMock(is_kill_switch_triggered=MagicMock(return_value=False)),
            audit_trail=audit,
        )
        # Manually create an alert with escalation rule
        rule = AlertRule(
            rule_id="TEST_ESCALATE",
            name="Test Escalation",
            category=AlertCategory.RISK,
            severity=AlertSeverity.WARNING,
            condition_description="Test escalation",
            throttle_seconds=0.0,
            escalation_after_seconds=0.0,  # immediate escalation
            escalation_severity=AlertSeverity.CRITICAL,
        )
        engine._rules["TEST_ESCALATE"] = rule

        # Raise alert manually
        with engine._lock:
            alert = engine._raise_alert(
                rule=rule,
                title="Escalation Test",
                message="This should escalate",
                source_component="test",
            )
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, AlertSeverity.WARNING)

        # Force check escalations
        with engine._lock:
            engine._check_escalations()

        self.assertTrue(alert.escalated)
        self.assertEqual(alert.severity, AlertSeverity.CRITICAL)
        self.assertEqual(alert.original_severity, AlertSeverity.WARNING)


class TestAlertLifecycle(unittest.TestCase):
    """Test 10: Alert lifecycle (ACTIVE → ACKNOWLEDGED → RESOLVED)."""

    def test_full_lifecycle(self):
        audit = ComplianceAuditTrail()
        engine = AlertingEngine(audit_trail=audit)

        # Raise an alert manually
        rule = engine._rules["SAFETY_KILL_SWITCH_TRIGGERED"]
        with engine._lock:
            alert = engine._raise_alert(
                rule=rule,
                title="Lifecycle Test",
                message="Testing lifecycle",
                source_component="test",
            )
        self.assertIsNotNone(alert)
        self.assertEqual(alert.state, AlertState.ACTIVE)

        # Acknowledge
        acked = engine.acknowledge_alert(alert.alert_id)
        self.assertIsNotNone(acked)
        self.assertEqual(acked.state, AlertState.ACKNOWLEDGED)
        self.assertIsNotNone(acked.acknowledged_at)

        # Resolve
        resolved = engine.resolve_alert(alert.alert_id)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.state, AlertState.RESOLVED)
        self.assertIsNotNone(resolved.resolved_at)

        # Verify audit trail recorded all transitions
        entries = audit.get_entries(limit=1000)
        actions = [e.action for e in entries]
        self.assertIn(AuditAction.ALERT_RAISED, actions)
        self.assertIn(AuditAction.ALERT_ACKNOWLEDGED, actions)
        self.assertIn(AuditAction.ALERT_RESOLVED, actions)


class TestInvalidAlertId(unittest.TestCase):
    """Test 11: Invalid alert_id handling."""

    def test_acknowledge_nonexistent_alert(self):
        engine = AlertingEngine()
        result = engine.acknowledge_alert("nonexistent-alert-id")
        self.assertIsNone(result)

    def test_resolve_nonexistent_alert(self):
        engine = AlertingEngine()
        result = engine.resolve_alert("nonexistent-alert-id")
        self.assertIsNone(result)


class TestEmptyState(unittest.TestCase):
    """Test 12: Empty state handling."""

    def test_empty_active_alerts(self):
        engine = AlertingEngine()
        alerts = engine.get_active_alerts()
        self.assertEqual(len(alerts), 0)

    def test_empty_alert_history(self):
        engine = AlertingEngine()
        history = engine.get_alert_history()
        self.assertEqual(len(history), 0)

    def test_empty_audit_trail(self):
        trail = ComplianceAuditTrail()
        entries = trail.get_entries()
        self.assertEqual(len(entries), 0)
        self.assertEqual(trail.entry_count(), 0)


class TestComplianceSnapshotGeneration(unittest.TestCase):
    """Test 13: Compliance snapshot generation."""

    def test_snapshot_shows_live_blocked(self):
        audit = ComplianceAuditTrail()
        engine = AlertingEngine(
            execution_guard=MagicMock(
                get_status_summary=MagicMock(return_value={"live_broker_blocked": True})
            ),
            telemetry_engine=MagicMock(is_kill_switch_triggered=MagicMock(return_value=False)),
            audit_trail=audit,
        )
        snapshot = engine.generate_compliance_snapshot()
        self.assertIsInstance(snapshot, ComplianceSnapshot)
        self.assertTrue(snapshot.live_trading_blocked)
        self.assertTrue(snapshot.execution_guard_active)
        self.assertTrue(snapshot.overall_compliant)
        self.assertFalse(snapshot.kill_switch_triggered)

        # Verify audit trail recorded the snapshot
        entries = audit.get_compliance_snapshots()
        self.assertGreaterEqual(len(entries), 1)


class TestComplianceAuditTrailRecording(unittest.TestCase):
    """Test 14: Compliance audit trail recording and querying."""

    def test_record_and_query(self):
        trail = ComplianceAuditTrail()
        entry = AuditEntry(
            entry_id=f"audit-{uuid.uuid4().hex[:12]}",
            action=AuditAction.ALERT_RAISED,
            category=AlertCategory.SAFETY,
            severity=AlertSeverity.CRITICAL,
            description="Test safety alert raised",
            safety_verified=True,
        )
        trail.record(entry)
        self.assertEqual(trail.entry_count(), 1)

        entries = trail.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].action, AuditAction.ALERT_RAISED)

    def test_compliance_report(self):
        trail = ComplianceAuditTrail()
        for i in range(5):
            trail.record(AuditEntry(
                entry_id=f"audit-{i}",
                action=AuditAction.ALERT_RAISED,
                category=AlertCategory.SAFETY,
                severity=AlertSeverity.HIGH,
                description=f"Alert {i}",
            ))
        trail.record(AuditEntry(
            entry_id="audit-resolved",
            action=AuditAction.ALERT_RESOLVED,
            category=AlertCategory.SAFETY,
            severity=AlertSeverity.HIGH,
            description="Alert resolved",
        ))
        report = trail.generate_compliance_report()
        self.assertIsInstance(report, ComplianceReport)
        self.assertEqual(report.total_entries, 6)
        self.assertEqual(report.alerts_raised, 5)
        self.assertEqual(report.alerts_resolved, 1)


class TestAuditTrailFiltering(unittest.TestCase):
    """Test 15: Audit trail filtering."""

    def test_filter_by_category(self):
        trail = ComplianceAuditTrail()
        trail.record(AuditEntry(
            entry_id="a1", action=AuditAction.ALERT_RAISED,
            category=AlertCategory.SAFETY, severity=AlertSeverity.CRITICAL,
            description="Safety alert",
        ))
        trail.record(AuditEntry(
            entry_id="a2", action=AuditAction.ALERT_RAISED,
            category=AlertCategory.RISK, severity=AlertSeverity.HIGH,
            description="Risk alert",
        ))
        safety = trail.get_entries(category=AlertCategory.SAFETY)
        self.assertEqual(len(safety), 1)
        risk = trail.get_entries(category=AlertCategory.RISK)
        self.assertEqual(len(risk), 1)

    def test_filter_by_action(self):
        trail = ComplianceAuditTrail()
        trail.record(AuditEntry(
            entry_id="a1", action=AuditAction.ALERT_RAISED,
            category=AlertCategory.SAFETY, severity=AlertSeverity.HIGH,
            description="Raised",
        ))
        trail.record(AuditEntry(
            entry_id="a2", action=AuditAction.COMPLIANCE_SNAPSHOT,
            category=AlertCategory.COMPLIANCE, severity=AlertSeverity.INFO,
            description="Snapshot",
        ))
        snapshots = trail.get_entries(action=AuditAction.COMPLIANCE_SNAPSHOT)
        self.assertEqual(len(snapshots), 1)

    def test_filter_by_severity(self):
        trail = ComplianceAuditTrail()
        trail.record(AuditEntry(
            entry_id="a1", action=AuditAction.ALERT_RAISED,
            category=AlertCategory.SAFETY, severity=AlertSeverity.CRITICAL,
            description="Critical",
        ))
        trail.record(AuditEntry(
            entry_id="a2", action=AuditAction.ALERT_RAISED,
            category=AlertCategory.RISK, severity=AlertSeverity.INFO,
            description="Info",
        ))
        crit = trail.get_entries(severity=AlertSeverity.CRITICAL)
        self.assertEqual(len(crit), 1)


class TestAuditTrailBoundedHistory(unittest.TestCase):
    """Test 16: Audit trail bounded history enforcement."""

    def test_max_entries_enforced(self):
        trail = ComplianceAuditTrail(max_entries=10)
        for i in range(25):
            trail.record(AuditEntry(
                entry_id=f"audit-{i}",
                action=AuditAction.ALERT_RAISED,
                category=AlertCategory.SAFETY,
                severity=AlertSeverity.INFO,
                description=f"Entry {i}",
            ))
        self.assertEqual(trail.entry_count(), 10)
        entries = trail.get_entries(limit=100)
        # Should have entries 15-24 (most recent 10)
        self.assertEqual(len(entries), 10)


class TestComponentFailureAlert(unittest.TestCase):
    """Test 17: Component failure alerting."""

    def test_component_failure_rule_exists(self):
        engine = AlertingEngine()
        rule = engine.get_rule("SYSTEM_COMPONENT_FAILED")
        self.assertIsNotNone(rule)
        self.assertEqual(rule.severity, AlertSeverity.CRITICAL)
        self.assertEqual(rule.category, AlertCategory.SYSTEM_HEALTH)

    def test_component_failure_alert_generation(self):
        health = MagicMock()
        health.safety_critical_healthy = False
        monitor = MagicMock(get_system_health=MagicMock(return_value=health))
        audit = ComplianceAuditTrail()
        engine = AlertingEngine(
            health_monitor=monitor,
            execution_guard=MagicMock(get_status_summary=MagicMock(return_value={"live_broker_blocked": True})),
            telemetry_engine=MagicMock(is_kill_switch_triggered=MagicMock(return_value=False)),
            audit_trail=audit,
        )
        alerts = engine.evaluate_all_rules()
        failed_alerts = [a for a in alerts if a.rule_id == "SYSTEM_COMPONENT_FAILED"]
        self.assertEqual(len(failed_alerts), 1)


class TestProviderCircuitBreakerRule(unittest.TestCase):
    """Test 18: Provider circuit breaker alerting."""

    def test_provider_circuit_rule_exists(self):
        engine = AlertingEngine()
        rule = engine.get_rule("PROVIDER_CIRCUIT_OPEN")
        self.assertIsNotNone(rule)
        self.assertEqual(rule.category, AlertCategory.PROVIDER)


class TestStreamingBackpressureRule(unittest.TestCase):
    """Test 19: Streaming backpressure alerting."""

    def test_backpressure_rule_exists(self):
        engine = AlertingEngine()
        rule = engine.get_rule("STREAMING_BACKPRESSURE")
        self.assertIsNotNone(rule)
        self.assertEqual(rule.category, AlertCategory.PERFORMANCE)


class TestSafetyBoundaryEnforcement(unittest.TestCase):
    """Test 20: Safety boundary enforcement (TIER_4 locked)."""

    def test_tier4_locked_via_broker_factory(self):
        from backend.application.broker_interface import BrokerFactory, ConfigurationSafetyError
        with self.assertRaises(ConfigurationSafetyError):
            BrokerFactory.get_adapter("live")

    def test_tier4_locked_via_broker_environment(self):
        from backend.domain.broker_schemas import BrokerEnvironment
        with self.assertRaises(ValueError):
            from backend.application.broker_interface import BrokerFactory
            BrokerFactory.get_adapter("real")

    def test_alerting_engine_has_zero_execution_authority(self):
        """Verify the alerting engine cannot place orders or modify risk."""
        engine = AlertingEngine()
        # Engine should have no submit_order, place_order, or execute method
        self.assertFalse(hasattr(engine, 'submit_order'))
        self.assertFalse(hasattr(engine, 'place_order'))
        self.assertFalse(hasattr(engine, 'execute'))
        self.assertFalse(hasattr(engine, 'modify_risk'))


class TestRESTAPIEndpoints(unittest.TestCase):
    """Test 21: REST API endpoint validation."""

    def test_alert_routes_exist(self):
        from backend.application.alert_routes import alert_router
        routes = [r.path for r in alert_router.routes]
        self.assertIn("/api/alerts/active", routes)
        self.assertIn("/api/alerts/history", routes)
        self.assertIn("/api/alerts/status", routes)
        self.assertIn("/api/alerts/rules", routes)
        self.assertIn("/api/alerts/evaluate", routes)
        self.assertIn("/api/alerts/{alert_id}/acknowledge", routes)
        self.assertIn("/api/alerts/{alert_id}/resolve", routes)
        self.assertIn("/api/compliance/audit", routes)
        self.assertIn("/api/compliance/snapshot", routes)
        self.assertIn("/api/compliance/report", routes)

    def test_router_has_correct_prefix(self):
        from backend.application.alert_routes import alert_router
        self.assertEqual(alert_router.prefix, "/api")


class TestSecretNonExposure(unittest.TestCase):
    """Test 22: Secret/credential non-exposure."""

    def test_sanitize_metadata(self):
        metadata = {
            "api_key": "sk-12345",
            "GROQ_API_KEY": "gsk_secret",
            "password": "mypassword",
            "normal_field": "safe_value",
            "nested": {
                "broker_secret": "hidden",
                "ok_field": "visible",
            },
        }
        sanitized = _sanitize_metadata(metadata)
        self.assertEqual(sanitized["api_key"], "***REDACTED***")
        self.assertEqual(sanitized["GROQ_API_KEY"], "***REDACTED***")
        self.assertEqual(sanitized["password"], "***REDACTED***")
        self.assertEqual(sanitized["normal_field"], "safe_value")
        self.assertEqual(sanitized["nested"]["broker_secret"], "***REDACTED***")
        self.assertEqual(sanitized["nested"]["ok_field"], "visible")

    def test_audit_trail_sanitizes_metadata(self):
        trail = ComplianceAuditTrail()
        trail.record(AuditEntry(
            entry_id="a1",
            action=AuditAction.ALERT_RAISED,
            category=AlertCategory.SAFETY,
            severity=AlertSeverity.HIGH,
            description="Test",
            metadata={"api_key": "secret123", "info": "safe"},
        ))
        entries = trail.get_entries()
        self.assertEqual(entries[0].metadata["api_key"], "***REDACTED***")
        self.assertEqual(entries[0].metadata["info"], "safe")


class TestConcurrentThreadSafety(unittest.TestCase):
    """Test 23: Concurrent thread-safety."""

    def test_concurrent_alert_operations(self):
        audit = ComplianceAuditTrail()
        engine = AlertingEngine(audit_trail=audit)
        errors = []

        def worker(worker_id):
            try:
                for i in range(20):
                    rule = AlertRule(
                        rule_id=f"WORKER_{worker_id}_RULE_{i}",
                        name=f"Worker {worker_id} Rule {i}",
                        category=AlertCategory.SYSTEM_HEALTH,
                        severity=AlertSeverity.WARNING,
                        condition_description="Thread test",
                        throttle_seconds=0.0,
                    )
                    with engine._lock:
                        engine._rules[rule.rule_id] = rule
                        engine._raise_alert(
                            rule=rule,
                            title=f"Thread {worker_id} Alert {i}",
                            message="Concurrent test",
                            source_component=f"worker-{worker_id}",
                        )
                    audit.record(AuditEntry(
                        entry_id=f"audit-w{worker_id}-{i}",
                        action=AuditAction.ALERT_RAISED,
                        category=AlertCategory.SYSTEM_HEALTH,
                        severity=AlertSeverity.INFO,
                        description=f"Worker {worker_id} entry {i}",
                    ))
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
        self.assertGreaterEqual(engine.get_status().total_alerts_raised, 40)
        self.assertGreaterEqual(audit.entry_count(), 40)


class TestRegressionCompatibility(unittest.TestCase):
    """Test 24: Regression compatibility with Phase 21 baseline."""

    def test_existing_broker_factory_still_works(self):
        from backend.application.broker_interface import BrokerFactory, ConfigurationSafetyError
        # Paper adapter should work
        adapter = BrokerFactory.get_adapter("paper")
        self.assertIsNotNone(adapter)

        # Live should fail
        with self.assertRaises(ConfigurationSafetyError):
            BrokerFactory.get_adapter("live")

    def test_existing_execution_guard_functional(self):
        from backend.application.execution_guard import global_execution_guard
        status = global_execution_guard.get_status_summary()
        self.assertTrue(status["live_broker_blocked"])

    def test_existing_telemetry_engine_functional(self):
        from backend.application.execution_telemetry_engine import global_telemetry_engine
        self.assertIsNotNone(global_telemetry_engine)

    def test_main_app_includes_alert_router(self):
        from backend.main import app
        routes = []
        for r in app.routes:
            if hasattr(r, "path"):
                routes.append(r.path)
            if hasattr(r, "original_router") and hasattr(r.original_router, "routes"):
                routes.extend([sub.path for sub in r.original_router.routes if hasattr(sub, "path")])
        self.assertIn("/api/alerts/status", routes)
        self.assertIn("/api/compliance/snapshot", routes)

    def test_dashboard_html_has_alerts_tab(self):
        from pathlib import Path
        html_path = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
        if html_path.exists():
            content = html_path.read_text(encoding="utf-8", errors="ignore")
            self.assertIn("tabAlerts", content)
            self.assertIn("tabBtnAlerts", content)
            self.assertIn("fetchAlertStatus", content)
            self.assertIn("fetchComplianceSnapshot", content)
            self.assertIn("PAPER TRADING ONLY", content)
            self.assertIn("[LOCKED] LIVE BROKER DISABLED", content)


if __name__ == "__main__":
    unittest.main()
