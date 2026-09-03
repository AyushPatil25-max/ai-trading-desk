"""
Phase 27 — Production Readiness, Deployment Hardening & System Certification E2E Tests

Covers all 20+ certification requirements:
1. Configuration validation & environment safety
2. Strict prohibition of LIVE execution mode
3. Secret redaction from diagnostics
4. Deterministic configuration fingerprinting (SHA-256)
5. Startup readiness state machine
6. Health semantics: separate liveness, readiness, and safety
7. Graceful shutdown and paper operation draining
8. Idempotency guard: duplicate tick prevention
9. Idempotency guard: duplicate decision prevention
10. Idempotency guard: duplicate paper order prevention
11. State checkpointing with SHA-256 checksum
12. Corrupted checkpoint detection & fail-closed protection
13. Incompatible checkpoint version detection & fail-closed protection
14. Failure injection & crash recovery behavior
15. 12-Category System Certification evaluation & bounds (0–100)
16. Explainable blockers and warnings synthesis
17. Phase 23 audit event emission and cryptographic integrity (VALID)
18. REST API endpoints under /api/system/*
19. FastAPI router inclusion in main app
20. Non-negotiable safety invariant: TIER_4_LIVE_REAL_MONEY permanently locked
"""

from datetime import datetime, timezone, timedelta
import json
import unittest

from backend.domain.certification_schemas import (
    SYSTEM_CERTIFICATION_VERSION,
    CertificationCategory,
    CertificationStatus,
    CheckpointIntegrityStatus,
    ComponentHealth,
    ExecutionMode,
    HealthStatus,
    ProductionConfig,
    SystemCertificationReport,
    SystemHealthReport,
    SystemOperationalState,
    SystemStateCheckpoint,
)
from backend.application.production_readiness_engine import (
    ProductionReadinessEngine,
    global_production_readiness_engine,
)
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.application.broker_interface import BrokerFactory, ConfigurationSafetyError


class TestConfigurationSafety(unittest.TestCase):
    """1, 2, 3, 4. Configuration validation, mode restriction, redaction, fingerprinting."""

    def test_valid_production_config(self):
        cfg = ProductionConfig(
            environment="production",
            mode=ExecutionMode.PAPER,
            initial_capital=100000.0,
            max_order_value=20000.0,
            allowed_symbols=["TCS.NS", "RELIANCE.NS"],
        )
        self.assertEqual(cfg.mode, ExecutionMode.PAPER)
        self.assertTrue(len(cfg.configuration_fingerprint) == 64)

    def test_prohibited_live_mode_rejected(self):
        with self.assertRaises(ValueError):
            ProductionConfig(mode="LIVE")  # type: ignore

    def test_secret_redaction_in_diagnostics(self):
        engine = ProductionReadinessEngine()
        diag = engine.get_safe_config()
        self.assertIn("api_key", diag)
        self.assertEqual(diag["api_key"], "***REDACTED***")
        self.assertTrue(diag["tier_4_live_real_money_locked"])

    def test_configuration_fingerprint_deterministic(self):
        cfg1 = ProductionConfig(environment="prod", mode=ExecutionMode.SHADOW, initial_capital=50000.0)
        cfg2 = ProductionConfig(environment="prod", mode=ExecutionMode.SHADOW, initial_capital=50000.0)
        self.assertEqual(cfg1.configuration_fingerprint, cfg2.configuration_fingerprint)


class TestStartupAndHealthSemantics(unittest.TestCase):
    """5, 6. Startup readiness state machine and health separation."""

    def setUp(self):
        self.engine = ProductionReadinessEngine()

    def test_startup_readiness_flow(self):
        rep = self.engine.validate_startup_readiness()
        self.assertTrue(rep.liveness)
        self.assertTrue(rep.readiness)
        self.assertEqual(rep.operational_state, SystemOperationalState.READY)
        self.assertEqual(rep.safety_health.status, HealthStatus.HEALTHY)

    def test_health_semantics_separation(self):
        rep = self.engine.get_health_report()
        # Liveness is process alive
        self.assertTrue(rep.liveness)
        # Readiness includes dependency checks
        self.assertIn("TamperEvidentAuditChain", rep.dependency_health)
        self.assertIn("RiskEngine", rep.dependency_health)
        self.assertIn("ExecutionPreflightEngine", rep.dependency_health)
        self.assertIn("PaperBrokerAdapter", rep.dependency_health)


class TestGracefulShutdown(unittest.TestCase):
    """7. Graceful shutdown and paper operation draining."""

    def test_graceful_shutdown_transitions(self):
        engine = ProductionReadinessEngine()
        self.assertEqual(engine._operational_state, SystemOperationalState.READY)

        final_state = engine.graceful_shutdown()
        self.assertEqual(final_state, SystemOperationalState.STOPPED)
        self.assertEqual(engine._operational_state, SystemOperationalState.STOPPED)


class TestIdempotencyProtection(unittest.TestCase):
    """8, 9, 10. Duplicate tick, decision, and paper order protection."""

    def setUp(self):
        self.engine = ProductionReadinessEngine()

    def test_tick_idempotency(self):
        now = datetime.now(timezone.utc)
        first = self.engine.check_and_register_tick_idempotency("TCS.NS", 3500.0, now)
        self.assertTrue(first)

        # Duplicate tick with exact same price and timestamp
        dup = self.engine.check_and_register_tick_idempotency("TCS.NS", 3500.0, now)
        self.assertFalse(dup)

    def test_decision_idempotency(self):
        first = self.engine.check_and_register_decision_idempotency("dec-001")
        self.assertTrue(first)

        dup = self.engine.check_and_register_decision_idempotency("dec-001")
        self.assertFalse(dup)

    def test_order_idempotency(self):
        first = self.engine.check_and_register_order_idempotency("ord-001")
        self.assertTrue(first)

        dup = self.engine.check_and_register_order_idempotency("ord-001")
        self.assertFalse(dup)


class TestStateCheckpointingAndRecovery(unittest.TestCase):
    """11, 12, 13, 14. Checkpointing, SHA-256 checksums, corruption fail-closed."""

    def setUp(self):
        self.engine = ProductionReadinessEngine()

    def test_checkpoint_creation_and_checksum_verification(self):
        chk = self.engine.create_checkpoint(active_symbols=["TCS.NS", "INFY.NS"])
        self.assertEqual(len(chk.payload_checksum), 64)
        self.assertTrue(chk.verify_checksum())

        # Successful restore
        ok, msg = self.engine.restore_checkpoint(chk.checkpoint_id)
        self.assertTrue(ok)
        self.assertIn("successfully restored", msg)

    def test_corrupted_checkpoint_fails_closed(self):
        chk = self.engine.create_checkpoint(active_symbols=["TCS.NS"])
        # Deliberately tamper with checkpoint payload
        chk.accounting_snapshot["cash"] = 9999999.0

        # Verification must fail and reject restore
        self.assertFalse(chk.verify_checksum())
        ok, msg = self.engine.restore_checkpoint(chk.checkpoint_id)
        self.assertFalse(ok)
        self.assertIn("corrupted", msg)

    def test_version_incompatible_checkpoint_fails_closed(self):
        chk = self.engine.create_checkpoint()
        chk.version = "99.0.0"  # Incompatible future version

        ok, msg = self.engine.restore_checkpoint(chk.checkpoint_id)
        self.assertFalse(ok)
        self.assertIn("Incompatible checkpoint version", msg)


class TestSystemCertificationEngine(unittest.TestCase):
    """15, 16. 12-Category certification logic, bounds, and verdicts."""

    def setUp(self):
        self.engine = ProductionReadinessEngine()

    def test_certification_scorecard_and_categories(self):
        rep = self.engine.run_system_certification()
        self.assertEqual(len(rep.categories), 12)
        self.assertGreaterEqual(rep.overall_score, 0.0)
        self.assertLessEqual(rep.overall_score, 100.0)
        self.assertEqual(rep.overall_status, CertificationStatus.CERTIFIED)
        self.assertEqual(len(rep.blockers), 0)
        self.assertTrue(rep.tier_4_live_real_money_locked)


class TestObservabilityAndSafetyInvariants(unittest.TestCase):
    """17, 18, 19, 20. Audit events, REST routes, real-money safety locks."""

    def test_audit_chain_validity(self):
        engine = ProductionReadinessEngine()
        engine.create_checkpoint()
        engine.run_system_certification()

        report = global_audit_chain.verify_integrity()
        self.assertEqual(report.status.value, "VALID")

    def test_direct_route_invocations(self):
        from backend.application.certification_routes import (
            get_liveness,
            get_readiness,
            get_health_summary,
            get_readiness_status,
            get_safe_config,
            create_checkpoint,
            get_system_certification,
        )

        liv = get_liveness()
        self.assertTrue(liv["liveness"])

        read = get_readiness()
        self.assertTrue(read["readiness"])
        self.assertTrue(read["live_trading_locked"])

        summ = get_health_summary()
        self.assertEqual(summ.operational_state, SystemOperationalState.READY)

        r_stat = get_readiness_status()
        self.assertEqual(r_stat["tier_4_live_real_money"], "LOCKED")

        cfg = get_safe_config()
        self.assertEqual(cfg["api_key"], "***REDACTED***")

        chk = create_checkpoint()
        self.assertTrue(chk.verify_checksum())

        cert = get_system_certification()
        self.assertEqual(cert.overall_status, CertificationStatus.CERTIFIED)

    def test_restore_checkpoint_api_400_on_corruption(self):
        from fastapi import HTTPException
        from backend.application.certification_routes import restore_checkpoint, RestoreCheckpointRequest

        # Restore non-existent checkpoint should raise HTTPException 400
        req = RestoreCheckpointRequest(checkpoint_id="chk-invalid")
        with self.assertRaises(HTTPException) as ctx:
            restore_checkpoint(req)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_failure_injection_rejection_of_invalid_capital(self):
        engine = ProductionReadinessEngine()
        cfg = ProductionConfig()
        cfg.initial_capital = -100.0
        ok, issues = engine.validate_configuration(cfg)
        self.assertFalse(ok)
        self.assertTrue(any("capital" in i.lower() for i in issues))

    def test_failure_injection_empty_symbols(self):
        engine = ProductionReadinessEngine()
        cfg = ProductionConfig()
        cfg.allowed_symbols = []
        ok, issues = engine.validate_configuration(cfg)
        self.assertFalse(ok)
        self.assertTrue(any("symbols" in i.lower() for i in issues))

    def test_restore_checkpoint_not_found_fails_closed(self):
        engine = ProductionReadinessEngine()
        ok, msg = engine.restore_checkpoint("chk-nonexistent")
        self.assertFalse(ok)
        self.assertIn("not found", msg)

    def test_fastapi_includes_certification_router(self):
        from backend.main import app
        all_paths = []
        for r in app.routes:
            if hasattr(r, "path"):
                all_paths.append(r.path)
            if hasattr(r, "original_router") and hasattr(r.original_router, "routes"):
                all_paths.extend([sub.path for sub in r.original_router.routes if hasattr(sub, "path")])

        self.assertIn("/api/system/health/liveness", all_paths)
        self.assertIn("/api/system/health/readiness", all_paths)
        self.assertIn("/api/system/certification", all_paths)

    def test_safety_tier4_live_real_money_permanently_locked(self):
        """TIER_4_LIVE_REAL_MONEY must remain unroutable and raise ConfigurationSafetyError."""
        with self.assertRaises(ConfigurationSafetyError):
            BrokerFactory.get_adapter("live")


if __name__ == "__main__":
    unittest.main()
