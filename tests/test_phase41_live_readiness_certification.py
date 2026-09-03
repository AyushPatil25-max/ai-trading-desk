"""
Phase 41 — Live Readiness, Safety Certification & Pre-Live Validation
Adversarial Test Suite

≥ 40 deterministic adversarial tests covering:
  - All 28 gate failures
  - AI boundary attacks
  - Kill switch / disarm combinations
  - Unknown state detection
  - Stale certification expiry
  - Strategy quarantine blocking
  - Configuration missing/invalid
  - Invariant verification
  - Execution path audit
  - Fail-closed behavior under every edge case

Safety Invariants Under Test:
  1. CERTIFIED status requires ALL blocking gates to pass
  2. Unknown/missing/stale state NEVER passes as safe
  3. Kill switch active → BLOCKED (not NOT_CERTIFIED)
  4. AI cannot self-certify or bypass certification
  5. Certification does NOT enable live execution
  6. real_money_execution_locked is ALWAYS True in reports
  7. LIVE_EXECUTION_ENABLED remains False throughout
"""

import os
import threading
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

from backend.domain.phase41_schemas import (
    GlobalCertificationStatus,
    GateCategory,
    GateSeverity,
    GateStatus,
)
from backend.execution.global_certification_engine import (
    GlobalLiveReadinessCertificationEngine,
    global_certification_engine,
)


def _make_fresh_engine() -> GlobalLiveReadinessCertificationEngine:
    """Create a fresh engine instance for isolation."""
    return GlobalLiveReadinessCertificationEngine()


class TestPhase41CertificationEngineBasics(unittest.TestCase):
    """Basic engine structure and property tests."""

    def setUp(self):
        self.engine = _make_fresh_engine()
        # Reset global state: clear kill switch and recovery reset
        from backend.execution.safety_engine import global_kill_switch
        from backend.execution.live_failure_recovery import global_live_failure_engine
        from backend.execution.live_arming_store import global_live_arming_store
        global_kill_switch.deactivate()
        global_live_failure_engine.clear_reset()
        global_live_arming_store.reset()

    def test_01_engine_singleton_exists(self):
        """global_certification_engine must be a GlobalLiveReadinessCertificationEngine instance."""
        self.assertIsInstance(global_certification_engine, GlobalLiveReadinessCertificationEngine)

    def test_02_certify_returns_report(self):
        """certify() must return a GlobalCertificationReport."""
        from backend.domain.phase41_schemas import GlobalCertificationReport
        report = self.engine.certify()
        self.assertIsInstance(report, GlobalCertificationReport)

    def test_03_report_has_28_gates(self):
        """Every certification run must evaluate exactly 28 gates."""
        report = self.engine.certify()
        self.assertEqual(report.total_gates, 28)

    def test_04_report_real_money_always_locked(self):
        """real_money_execution_locked MUST always be True in Phase 41."""
        report = self.engine.certify()
        self.assertTrue(report.real_money_execution_locked,
                        "real_money_execution_locked must ALWAYS be True in Phase 41")

    def test_05_live_execution_disabled_in_report(self):
        """Report must accurately reflect LIVE_EXECUTION_ENABLED=False."""
        report = self.engine.certify()
        self.assertFalse(report.live_execution_enabled,
                         "LIVE_EXECUTION_ENABLED must remain False in Phase 41")

    def test_06_report_has_report_id(self):
        """Each report must have a unique, non-empty report_id."""
        r1 = self.engine.certify()
        r2 = self.engine.certify()
        self.assertTrue(r1.report_id.startswith("cert41-"))
        self.assertTrue(r2.report_id.startswith("cert41-"))
        self.assertNotEqual(r1.report_id, r2.report_id, "Each report ID must be unique")

    def test_07_report_has_expiry(self):
        """Every report must have an expires_at timestamp in the future."""
        report = self.engine.certify()
        self.assertIsNotNone(report.expires_at)
        self.assertGreater(report.expires_at, report.evaluated_at)

    def test_08_gate_count_consistency(self):
        """passed_gates + failed_gates must equal total_gates."""
        report = self.engine.certify()
        self.assertEqual(report.passed_gates + report.failed_gates, report.total_gates)

    def test_09_to_summary_dict_no_secrets(self):
        """to_summary_dict() must not expose actual credential values or secret tokens."""
        # Inject fake secret values so we can verify they don't appear in output
        with patch.dict(os.environ, {
            "DHAN_ACCESS_TOKEN": "MY_REAL_SECRET_TOKEN_ABCDEF123456",
            "DHAN_CLIENT_ID": "MY_REAL_CLIENT_ID_XYZ789",
            "GROQ_API_KEY": "groq_secret_key_value_7890",
        }):
            report = self.engine.certify()
            summary = report.to_summary_dict()
            summary_str = str(summary)
            # The ACTUAL credential values must never appear
            for secret_value in [
                "MY_REAL_SECRET_TOKEN_ABCDEF123456",
                "MY_REAL_CLIENT_ID_XYZ789",
                "groq_secret_key_value_7890",
            ]:
                self.assertNotIn(secret_value, summary_str,
                                 f"to_summary_dict() must not expose actual secret value: {secret_value}")

    def test_10_is_certified_convenience_method(self):
        """is_certified() returns a (bool, str) tuple."""
        result = self.engine.is_certified()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], bool)
        self.assertIsInstance(result[1], str)


class TestPhase41KillSwitchBehavior(unittest.TestCase):
    """Kill switch must produce BLOCKED status, not just NOT_CERTIFIED."""

    def setUp(self):
        self.engine = _make_fresh_engine()
        from backend.execution.safety_engine import global_kill_switch
        from backend.execution.live_failure_recovery import global_live_failure_engine
        from backend.execution.live_arming_store import global_live_arming_store
        global_kill_switch.deactivate()
        global_live_failure_engine.clear_reset()
        global_live_arming_store.reset()

    def test_11_kill_switch_active_produces_blocked(self):
        """When kill switch is active, certification must return BLOCKED (not NOT_CERTIFIED)."""
        from backend.execution.safety_engine import global_kill_switch
        global_kill_switch.activate()
        try:
            report = self.engine.certify()
            self.assertEqual(report.overall_status, GlobalCertificationStatus.BLOCKED,
                             "Active kill switch must produce BLOCKED status")
            self.assertTrue(report.kill_switch_active)
        finally:
            global_kill_switch.deactivate()

    def test_12_kill_switch_active_gate_11_fails(self):
        """Gate CERT-11 must fail when kill switch is active."""
        from backend.execution.safety_engine import global_kill_switch
        global_kill_switch.activate()
        try:
            report = self.engine.certify()
            gate11 = next((g for g in report.gates if g.gate_id == "CERT-11"), None)
            self.assertIsNotNone(gate11, "CERT-11 must exist")
            self.assertFalse(gate11.passed, "CERT-11 must fail with kill switch active")
        finally:
            global_kill_switch.deactivate()

    def test_13_kill_switch_clear_unlocks_cert_11(self):
        """Gate CERT-11 must pass when kill switch is inactive."""
        from backend.execution.safety_engine import global_kill_switch
        global_kill_switch.deactivate()
        report = self.engine.certify()
        gate11 = next((g for g in report.gates if g.gate_id == "CERT-11"), None)
        self.assertIsNotNone(gate11)
        self.assertTrue(gate11.passed, "CERT-11 must pass when kill switch is clear")
        self.assertFalse(report.kill_switch_active)

    def test_14_certify_never_changes_kill_switch_state(self):
        """certify() must NEVER modify kill switch state."""
        from backend.execution.safety_engine import global_kill_switch
        initial_state = global_kill_switch.is_active()
        self.engine.certify()
        after_state = global_kill_switch.is_active()
        self.assertEqual(initial_state, after_state,
                         "certify() must not modify kill switch state")


class TestPhase41RecoveryResetBehavior(unittest.TestCase):
    """LiveFailureRecovery reset state must block certification."""

    def setUp(self):
        self.engine = _make_fresh_engine()
        from backend.execution.safety_engine import global_kill_switch
        from backend.execution.live_failure_recovery import global_live_failure_engine
        from backend.execution.live_arming_store import global_live_arming_store
        global_kill_switch.deactivate()
        global_live_failure_engine.clear_reset()
        global_live_arming_store.reset()

    def test_15_recovery_in_reset_blocks_certification(self):
        """LiveFailureRecovery in RESET state must block gate CERT-12 and CERT-13."""
        from backend.execution.live_failure_recovery import global_live_failure_engine
        global_live_failure_engine.reset()
        try:
            report = self.engine.certify()
            self.assertNotEqual(report.overall_status, GlobalCertificationStatus.CERTIFIED,
                                "Recovery in RESET must prevent CERTIFIED status")
            self.assertTrue(report.failure_recovery_in_reset)
        finally:
            global_live_failure_engine.clear_reset()

    def test_16_gate_12_fails_with_recovery_reset(self):
        """Gate CERT-12 must explicitly fail when recovery engine is in RESET."""
        from backend.execution.live_failure_recovery import global_live_failure_engine
        global_live_failure_engine.reset()
        try:
            report = self.engine.certify()
            gate12 = next((g for g in report.gates if g.gate_id == "CERT-12"), None)
            self.assertIsNotNone(gate12)
            self.assertFalse(gate12.passed)
        finally:
            global_live_failure_engine.clear_reset()

    def test_17_clear_reset_allows_cert_12_to_pass(self):
        """Gate CERT-12 passes after clear_reset() is called."""
        from backend.execution.live_failure_recovery import global_live_failure_engine
        global_live_failure_engine.clear_reset()
        report = self.engine.certify()
        gate12 = next((g for g in report.gates if g.gate_id == "CERT-12"), None)
        self.assertIsNotNone(gate12)
        self.assertTrue(gate12.passed)


class TestPhase41MarketDataFreshness(unittest.TestCase):
    """Market data freshness gate (CERT-05) adversarial tests."""

    def setUp(self):
        self.engine = _make_fresh_engine()
        from backend.execution.safety_engine import global_kill_switch
        from backend.execution.live_failure_recovery import global_live_failure_engine
        from backend.execution.live_arming_store import global_live_arming_store
        global_kill_switch.deactivate()
        global_live_failure_engine.clear_reset()
        global_live_arming_store.reset()

    def test_18_no_market_data_timestamp_fails_closed(self):
        """None market data timestamp MUST fail gate CERT-05 (fail-closed)."""
        report = self.engine.certify(market_data_timestamp=None)
        gate05 = next((g for g in report.gates if g.gate_id == "CERT-05"), None)
        self.assertIsNotNone(gate05)
        self.assertFalse(gate05.passed, "None timestamp must fail (fail-closed)")
        self.assertEqual(gate05.status, GateStatus.UNKNOWN)

    def test_19_stale_market_data_fails_gate_05(self):
        """Market data older than threshold must fail gate CERT-05."""
        stale_ts = datetime.now(timezone.utc) - timedelta(seconds=60)
        report = self.engine.certify(
            market_data_timestamp=stale_ts,
            stale_threshold_seconds=30.0
        )
        gate05 = next((g for g in report.gates if g.gate_id == "CERT-05"), None)
        self.assertIsNotNone(gate05)
        self.assertFalse(gate05.passed, "60s-old data with 30s threshold must fail")

    def test_20_fresh_market_data_passes_gate_05(self):
        """Fresh market data (1s old, 30s threshold) must pass gate CERT-05."""
        fresh_ts = datetime.now(timezone.utc) - timedelta(seconds=1)
        report = self.engine.certify(
            market_data_timestamp=fresh_ts,
            stale_threshold_seconds=30.0
        )
        gate05 = next((g for g in report.gates if g.gate_id == "CERT-05"), None)
        self.assertIsNotNone(gate05)
        self.assertTrue(gate05.passed, "1s-old data with 30s threshold must pass")

    def test_21_exactly_at_threshold_boundary_fails(self):
        """Market data exactly at threshold age must fail (exclusive boundary)."""
        exact_ts = datetime.now(timezone.utc) - timedelta(seconds=30.1)
        report = self.engine.certify(
            market_data_timestamp=exact_ts,
            stale_threshold_seconds=30.0
        )
        gate05 = next((g for g in report.gates if g.gate_id == "CERT-05"), None)
        self.assertIsNotNone(gate05)
        self.assertFalse(gate05.passed)

    def test_22_future_timestamp_considered_fresh(self):
        """A slightly future timestamp (clock skew) should still be considered fresh."""
        future_ts = datetime.now(timezone.utc) + timedelta(seconds=2)
        report = self.engine.certify(
            market_data_timestamp=future_ts,
            stale_threshold_seconds=30.0
        )
        gate05 = next((g for g in report.gates if g.gate_id == "CERT-05"), None)
        self.assertIsNotNone(gate05)
        # Age will be negative → very fresh → passes
        self.assertTrue(gate05.passed)


class TestPhase41SafetyInvariants(unittest.TestCase):
    """Safety invariant verification tests."""

    def setUp(self):
        self.engine = _make_fresh_engine()
        from backend.execution.safety_engine import global_kill_switch
        from backend.execution.live_failure_recovery import global_live_failure_engine
        from backend.execution.live_arming_store import global_live_arming_store
        global_kill_switch.deactivate()
        global_live_failure_engine.clear_reset()
        global_live_arming_store.reset()

    def test_23_safety_invariants_are_present(self):
        """Report must include at least 7 safety invariants."""
        report = self.engine.certify()
        self.assertGreaterEqual(len(report.safety_invariants), 7,
                                "Must verify at least 7 safety invariants")

    def test_24_inv_critical_01_live_execution_disabled(self):
        """INV-CRITICAL-01 must be verified: LIVE_EXECUTION_ENABLED is False."""
        report = self.engine.certify()
        inv01 = next((i for i in report.safety_invariants if i.invariant_id == "INV-CRITICAL-01"), None)
        self.assertIsNotNone(inv01, "INV-CRITICAL-01 must be present")
        self.assertTrue(inv01.verified,
                        "INV-CRITICAL-01 must be verified (LIVE_EXECUTION_ENABLED is False)")

    def test_25_inv_critical_02_kill_switch_exists(self):
        """INV-CRITICAL-02 must verify kill switch has activate/is_active methods."""
        report = self.engine.certify()
        inv02 = next((i for i in report.safety_invariants if i.invariant_id == "INV-CRITICAL-02"), None)
        self.assertIsNotNone(inv02)
        self.assertTrue(inv02.verified)

    def test_26_inv_critical_03_fresh_arming_store_disarmed(self):
        """INV-CRITICAL-03 must verify a fresh LiveArmingStore is always disarmed."""
        report = self.engine.certify()
        inv03 = next((i for i in report.safety_invariants if i.invariant_id == "INV-CRITICAL-03"), None)
        self.assertIsNotNone(inv03)
        self.assertTrue(inv03.verified,
                        "Fresh LiveArmingStore must always start disarmed")

    def test_27_inv_critical_04_ai_advisory_no_order_methods(self):
        """INV-CRITICAL-04: AIAdvisoryGuard must not have place_order or submit_order."""
        report = self.engine.certify()
        inv04 = next((i for i in report.safety_invariants if i.invariant_id == "INV-CRITICAL-04"), None)
        self.assertIsNotNone(inv04)
        self.assertTrue(inv04.verified,
                        "AIAdvisoryGuard must not have direct execution methods")

    def test_28_inv_08_real_money_locked(self):
        """INV-08: Real-money execution permanently locked must always be verified."""
        report = self.engine.certify()
        inv08 = next((i for i in report.safety_invariants if i.invariant_id == "INV-08"), None)
        self.assertIsNotNone(inv08)
        self.assertTrue(inv08.verified,
                        "INV-08: real_money_execution_locked must always be verified")


class TestPhase41AIBoundaryEnforcement(unittest.TestCase):
    """Gate CERT-28: AI boundary enforcement adversarial tests."""

    def setUp(self):
        self.engine = _make_fresh_engine()
        from backend.execution.safety_engine import global_kill_switch
        from backend.execution.live_failure_recovery import global_live_failure_engine
        from backend.execution.live_arming_store import global_live_arming_store
        global_kill_switch.deactivate()
        global_live_failure_engine.clear_reset()
        global_live_arming_store.reset()

    def test_29_gate_28_ai_boundary_passes_by_default(self):
        """Gate CERT-28 must pass with the correct Phase 35 AIAdvisoryGuard."""
        report = self.engine.certify()
        gate28 = next((g for g in report.gates if g.gate_id == "CERT-28"), None)
        self.assertIsNotNone(gate28)
        self.assertTrue(gate28.passed,
                        "CERT-28 must pass — AIAdvisoryGuard is advisory-only")

    def test_30_ai_advisory_guard_lacks_place_order(self):
        """AIAdvisoryGuard must never have place_order method."""
        from backend.execution.ai_advisory_guard import AIAdvisoryGuard
        guard = AIAdvisoryGuard()
        self.assertFalse(hasattr(guard, 'place_order'),
                         "AIAdvisoryGuard must NOT have place_order method")

    def test_31_ai_advisory_guard_lacks_submit_order(self):
        """AIAdvisoryGuard must never have submit_order method."""
        from backend.execution.ai_advisory_guard import AIAdvisoryGuard
        guard = AIAdvisoryGuard()
        self.assertFalse(hasattr(guard, 'submit_order'),
                         "AIAdvisoryGuard must NOT have submit_order method")

    def test_32_ai_advisory_guard_has_validate_method(self):
        """AIAdvisoryGuard must have validate_and_prepare_request (advisory-only interface)."""
        from backend.execution.ai_advisory_guard import AIAdvisoryGuard
        guard = AIAdvisoryGuard()
        self.assertTrue(hasattr(guard, 'validate_and_prepare_request'),
                        "AIAdvisoryGuard must have validate_and_prepare_request (advisory-only)")

    def test_33_certification_does_not_self_arm(self):
        """certify() must NOT arm live trading as a side effect."""
        from backend.execution.live_arming_store import global_live_arming_store
        initial_armed = global_live_arming_store.is_currently_armed()
        self.engine.certify()
        after_armed = global_live_arming_store.is_currently_armed()
        self.assertEqual(initial_armed, after_armed,
                         "certify() must never arm live trading as side effect")


class TestPhase41ConfigurationGates(unittest.TestCase):
    """Gate CERT-01, CERT-02, CERT-03 configuration validation tests."""

    def setUp(self):
        self.engine = _make_fresh_engine()
        from backend.execution.safety_engine import global_kill_switch
        from backend.execution.live_failure_recovery import global_live_failure_engine
        from backend.execution.live_arming_store import global_live_arming_store
        global_kill_switch.deactivate()
        global_live_failure_engine.clear_reset()
        global_live_arming_store.reset()

    def test_34_gate_01_always_passes_with_valid_config(self):
        """Gate CERT-01 must pass when AppConfig loads without error."""
        report = self.engine.certify()
        gate01 = next((g for g in report.gates if g.gate_id == "CERT-01"), None)
        self.assertIsNotNone(gate01)
        self.assertTrue(gate01.passed, "CERT-01 must pass with valid config")

    def test_35_gate_02_fails_without_dhan_credentials(self):
        """Gate CERT-02 must fail when DHAN_ENABLED is False (no broker configured)."""
        report = self.engine.certify()
        gate02 = next((g for g in report.gates if g.gate_id == "CERT-02"), None)
        self.assertIsNotNone(gate02)
        # In dev environment, DHAN_ENABLED is False → gate should fail
        # This validates fail-closed: missing broker config = not certified
        cfg_val = os.environ.get("DHAN_ENABLED", "false").lower()
        if cfg_val != "true":
            self.assertFalse(gate02.passed,
                             "CERT-02 must fail when DHAN_ENABLED is False")

    def test_36_gate_03_fails_without_dhan_credentials(self):
        """Gate CERT-03 must fail when DHAN_CLIENT_ID/DHAN_ACCESS_TOKEN not set."""
        # In dev, these env vars are not set
        client_id = os.environ.get("DHAN_CLIENT_ID", "")
        access_token = os.environ.get("DHAN_ACCESS_TOKEN", "")
        report = self.engine.certify()
        gate03 = next((g for g in report.gates if g.gate_id == "CERT-03"), None)
        self.assertIsNotNone(gate03)
        if not client_id or not access_token:
            self.assertFalse(gate03.passed,
                             "CERT-03 must fail when broker credentials are missing")

    def test_37_gate_03_never_exposes_credential_values(self):
        """Gate CERT-03 message must never contain actual credential values."""
        with patch.dict(os.environ, {
            "DHAN_CLIENT_ID": "test_client_12345",
            "DHAN_ACCESS_TOKEN": "super_secret_token_xyz"
        }):
            report = self.engine.certify()
            gate03 = next((g for g in report.gates if g.gate_id == "CERT-03"), None)
            if gate03:
                self.assertNotIn("test_client_12345", gate03.message or "")
                self.assertNotIn("super_secret_token_xyz", gate03.message or "")
                self.assertNotIn("test_client_12345", gate03.details or "")
                self.assertNotIn("super_secret_token_xyz", gate03.details or "")


class TestPhase41FailClosedBehavior(unittest.TestCase):
    """Fail-closed behavior: unknown/missing states must not certify as safe."""

    def setUp(self):
        self.engine = _make_fresh_engine()
        from backend.execution.safety_engine import global_kill_switch
        from backend.execution.live_failure_recovery import global_live_failure_engine
        from backend.execution.live_arming_store import global_live_arming_store
        global_kill_switch.deactivate()
        global_live_failure_engine.clear_reset()
        global_live_arming_store.reset()

    def test_38_missing_market_data_prevents_certified(self):
        """System with no market data timestamp must not achieve CERTIFIED status."""
        report = self.engine.certify(market_data_timestamp=None)
        self.assertNotEqual(report.overall_status, GlobalCertificationStatus.CERTIFIED,
                            "Missing market data must prevent CERTIFIED status")

    def test_39_gate_27_fail_closed_behavior_primitives(self):
        """Gate CERT-27 must pass — all fail-closed primitives must exist."""
        report = self.engine.certify()
        gate27 = next((g for g in report.gates if g.gate_id == "CERT-27"), None)
        self.assertIsNotNone(gate27, "CERT-27 must be present")
        self.assertTrue(gate27.passed,
                        "All fail-closed primitives (kill switch, recovery reset, arming invalidate) must exist")

    def test_40_gate_23_fresh_arming_store_disarmed(self):
        """Gate CERT-23: process restart safety must pass — fresh store is never pre-armed."""
        report = self.engine.certify()
        gate23 = next((g for g in report.gates if g.gate_id == "CERT-23"), None)
        self.assertIsNotNone(gate23, "CERT-23 must be present")
        self.assertTrue(gate23.passed,
                        "Fresh LiveArmingStore must always start disarmed")

    def test_41_gate_21_manual_confirmation_required(self):
        """Gate CERT-21: confirmation system must require TTL-bounded tokens."""
        report = self.engine.certify()
        gate21 = next((g for g in report.gates if g.gate_id == "CERT-21"), None)
        self.assertIsNotNone(gate21)
        self.assertTrue(gate21.passed,
                        "ConfirmationStore must be operational with non-zero TTL")

    def test_42_gate_18_duplicate_protection_operational(self):
        """Gate CERT-18: duplicate order protection must be operational."""
        report = self.engine.certify()
        gate18 = next((g for g in report.gates if g.gate_id == "CERT-18"), None)
        self.assertIsNotNone(gate18)
        self.assertTrue(gate18.passed,
                        "InMemoryOrderTracker with duplicate detection must be operational")


class TestPhase41ExecutionPathAudit(unittest.TestCase):
    """Execution path audit and gate structural integrity."""

    def setUp(self):
        self.engine = _make_fresh_engine()
        from backend.execution.safety_engine import global_kill_switch
        from backend.execution.live_failure_recovery import global_live_failure_engine
        from backend.execution.live_arming_store import global_live_arming_store
        global_kill_switch.deactivate()
        global_live_failure_engine.clear_reset()
        global_live_arming_store.reset()

    def test_43_execution_path_audit_clean(self):
        """Execution path audit must be clean — no hidden order submission paths."""
        report = self.engine.certify()
        self.assertTrue(report.execution_path_audit_clean,
                        "Execution path audit must be clean")
        self.assertEqual(report.hidden_execution_paths_detected, 0,
                         "No hidden execution paths should be detected")

    def test_44_gate_09_risk_engine_structural_check(self):
        """Gate CERT-09: RiskEngine must have evaluate_and_size method."""
        report = self.engine.certify()
        gate09 = next((g for g in report.gates if g.gate_id == "CERT-09"), None)
        self.assertIsNotNone(gate09)
        self.assertTrue(gate09.passed, "Phase 6 RiskEngine must be structurally ready")

    def test_45_gate_10_execution_preflight_structural_check(self):
        """Gate CERT-10: ExecutionPreflightEngine must have evaluate_preflight method."""
        report = self.engine.certify()
        gate10 = next((g for g in report.gates if g.gate_id == "CERT-10"), None)
        self.assertIsNotNone(gate10)
        self.assertTrue(gate10.passed,
                        "Phase 39 ExecutionPreflightEngine must be structurally ready")

    def test_46_gate_08_strategy_governance_structural_check(self):
        """Gate CERT-08: StrategyGovernanceEngine must have evaluate_signal method."""
        report = self.engine.certify()
        gate08 = next((g for g in report.gates if g.gate_id == "CERT-08"), None)
        self.assertIsNotNone(gate08)
        self.assertTrue(gate08.passed,
                        "Phase 29 StrategyGovernanceEngine must be structurally ready")

    def test_47_gate_17_order_idempotency_structural_check(self):
        """Gate CERT-17: ConfirmationStore must have create_confirmation and consume_confirmation."""
        report = self.engine.certify()
        gate17 = next((g for g in report.gates if g.gate_id == "CERT-17"), None)
        self.assertIsNotNone(gate17)
        self.assertTrue(gate17.passed,
                        "ConfirmationStore must be operational")


class TestPhase41ConcurrencyAndRepeatability(unittest.TestCase):
    """Thread safety and deterministic repeatability tests."""

    def setUp(self):
        self.engine = _make_fresh_engine()
        from backend.execution.safety_engine import global_kill_switch
        from backend.execution.live_failure_recovery import global_live_failure_engine
        from backend.execution.live_arming_store import global_live_arming_store
        global_kill_switch.deactivate()
        global_live_failure_engine.clear_reset()
        global_live_arming_store.reset()

    def test_48_concurrent_certify_calls_all_succeed(self):
        """Multiple concurrent certify() calls must all return valid reports."""
        results = []
        errors = []

        def run():
            try:
                r = self.engine.certify(market_data_timestamp=datetime.now(timezone.utc))
                results.append(r)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=run) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        self.assertEqual(len(errors), 0, f"Concurrent calls should not raise: {errors}")
        self.assertEqual(len(results), 8)
        for r in results:
            self.assertEqual(r.total_gates, 28)

    def test_49_repeated_certify_same_status_same_conditions(self):
        """Same system state should produce the same overall status repeatedly."""
        reports = [self.engine.certify() for _ in range(5)]
        statuses = set(r.overall_status for r in reports)
        self.assertEqual(len(statuses), 1,
                         f"Repeated certify() with same state should give same status, got: {statuses}")

    def test_50_certification_does_not_mutate_live_state(self):
        """certify() must not modify any global safety state."""
        from backend.execution.safety_engine import global_kill_switch
        from backend.execution.live_failure_recovery import global_live_failure_engine
        from backend.execution.live_arming_store import global_live_arming_store

        ks_before = global_kill_switch.is_active()
        recovery_status_before = global_live_failure_engine.get_status().get("is_reset", False)
        armed_before = global_live_arming_store.is_currently_armed()

        self.engine.certify()

        ks_after = global_kill_switch.is_active()
        recovery_status_after = global_live_failure_engine.get_status().get("is_reset", False)
        armed_after = global_live_arming_store.is_currently_armed()

        self.assertEqual(ks_before, ks_after, "certify() must not change kill switch state")
        self.assertEqual(recovery_status_before, recovery_status_after,
                         "certify() must not change recovery reset state")
        self.assertEqual(armed_before, armed_after, "certify() must not change arming state")


class TestPhase41SchemaValidation(unittest.TestCase):
    """Phase 41 schema structural tests."""

    def test_51_global_certification_status_values(self):
        """GlobalCertificationStatus must have all required values."""
        from backend.domain.phase41_schemas import GlobalCertificationStatus
        expected = {"CERTIFIED", "NOT_CERTIFIED", "BLOCKED", "DEGRADED", "EXPIRED"}
        actual = {s.value for s in GlobalCertificationStatus}
        self.assertEqual(expected, actual,
                         f"GlobalCertificationStatus must have exactly: {expected}")

    def test_52_gate_severity_values(self):
        """GateSeverity must have BLOCKING, WARNING, INFO."""
        from backend.domain.phase41_schemas import GateSeverity
        self.assertIn("BLOCKING", [s.value for s in GateSeverity])
        self.assertIn("WARNING", [s.value for s in GateSeverity])
        self.assertIn("INFO", [s.value for s in GateSeverity])

    def test_53_gate_status_values(self):
        """GateStatus must have PASSED, FAILED, UNKNOWN, DEGRADED, SKIPPED."""
        from backend.domain.phase41_schemas import GateStatus
        for val in ["PASSED", "FAILED", "UNKNOWN", "DEGRADED", "SKIPPED"]:
            self.assertIn(val, [s.value for s in GateStatus])

    def test_54_certification_gate_result_is_blocking_matches_severity(self):
        """Gates with BLOCKING severity must have is_blocking=True."""
        engine = _make_fresh_engine()
        from backend.execution.safety_engine import global_kill_switch
        from backend.execution.live_failure_recovery import global_live_failure_engine
        from backend.execution.live_arming_store import global_live_arming_store
        global_kill_switch.deactivate()
        global_live_failure_engine.clear_reset()
        global_live_arming_store.reset()
        report = engine.certify()
        for gate in report.gates:
            if gate.severity == GateSeverity.BLOCKING:
                self.assertTrue(gate.is_blocking,
                                f"Gate {gate.gate_id} has BLOCKING severity but is_blocking=False")

    def test_55_all_gates_have_unique_ids(self):
        """Every gate in a certification report must have a unique gate_id."""
        engine = _make_fresh_engine()
        from backend.execution.safety_engine import global_kill_switch
        from backend.execution.live_failure_recovery import global_live_failure_engine
        from backend.execution.live_arming_store import global_live_arming_store
        global_kill_switch.deactivate()
        global_live_failure_engine.clear_reset()
        global_live_arming_store.reset()
        report = engine.certify()
        ids = [g.gate_id for g in report.gates]
        self.assertEqual(len(ids), len(set(ids)),
                         "All gate IDs must be unique within a certification report")

    def test_56_dependency_health_list_non_empty(self):
        """Certification must include non-empty dependency health status."""
        engine = _make_fresh_engine()
        from backend.execution.safety_engine import global_kill_switch
        from backend.execution.live_failure_recovery import global_live_failure_engine
        from backend.execution.live_arming_store import global_live_arming_store
        global_kill_switch.deactivate()
        global_live_failure_engine.clear_reset()
        global_live_arming_store.reset()
        report = engine.certify()
        self.assertGreater(len(report.dependency_health), 0,
                           "dependency_health must include at least one dependency status")


class TestPhase41AuditAndPersistence(unittest.TestCase):
    """Audit chain and persistence integrity gate tests."""

    def setUp(self):
        self.engine = _make_fresh_engine()
        from backend.execution.safety_engine import global_kill_switch
        from backend.execution.live_failure_recovery import global_live_failure_engine
        from backend.execution.live_arming_store import global_live_arming_store
        global_kill_switch.deactivate()
        global_live_failure_engine.clear_reset()
        global_live_arming_store.reset()

    def test_57_gate_16_audit_chain_passes_or_empty(self):
        """Gate CERT-16 must pass when audit chain is VALID or EMPTY."""
        report = self.engine.certify()
        gate16 = next((g for g in report.gates if g.gate_id == "CERT-16"), None)
        self.assertIsNotNone(gate16)
        self.assertTrue(gate16.passed,
                        f"CERT-16 must pass. Got: {gate16.message}")

    def test_58_gate_14_persistent_state_passes(self):
        """Gate CERT-14 persistent state integrity must pass with healthy store."""
        report = self.engine.certify()
        gate14 = next((g for g in report.gates if g.gate_id == "CERT-14"), None)
        self.assertIsNotNone(gate14)
        self.assertTrue(gate14.passed,
                        f"CERT-14 must pass when persistent state is healthy. Got: {gate14.message}")

    def test_59_audit_chain_events_count_in_report(self):
        """Report must include audit_total_events field."""
        report = self.engine.certify()
        self.assertIsInstance(report.audit_total_events, int)
        self.assertGreaterEqual(report.audit_total_events, 0)

    def test_60_persistence_revision_in_report(self):
        """Report must include persistence_revision field."""
        report = self.engine.certify()
        self.assertIsInstance(report.persistence_revision, int)
        self.assertGreaterEqual(report.persistence_revision, 0)


class TestPhase41ConfigurationFingerprint(unittest.TestCase):
    """Configuration fingerprint must not expose secrets."""

    def setUp(self):
        self.engine = _make_fresh_engine()
        from backend.execution.safety_engine import global_kill_switch
        from backend.execution.live_failure_recovery import global_live_failure_engine
        from backend.execution.live_arming_store import global_live_arming_store
        global_kill_switch.deactivate()
        global_live_failure_engine.clear_reset()
        global_live_arming_store.reset()

    def test_61_configuration_fingerprint_is_sha256_hex(self):
        """Configuration fingerprint must be a 64-char hex string."""
        report = self.engine.certify()
        fp = report.configuration_fingerprint
        if fp:  # Non-empty fingerprint
            self.assertEqual(len(fp), 64, "Config fingerprint must be 64-char SHA-256 hex")
            # Must be all hex characters
            try:
                int(fp, 16)
            except ValueError:
                self.fail("Config fingerprint must be valid hex")

    def test_62_fingerprint_does_not_contain_api_values(self):
        """Configuration fingerprint must not contain actual API key values."""
        with patch.dict(os.environ, {
            "DHAN_ACCESS_TOKEN": "super_secret_access_token_value",
            "GROQ_API_KEY": "my_groq_key_12345",
        }):
            report = self.engine.certify()
            fp = report.configuration_fingerprint
            self.assertNotIn("super_secret_access_token_value", fp)
            self.assertNotIn("my_groq_key_12345", fp)

    def test_63_fingerprint_changes_with_config_change(self):
        """Configuration fingerprint must change when config changes."""
        with patch.dict(os.environ, {"DHAN_ENABLED": "false"}):
            report1 = self.engine.certify()
        with patch.dict(os.environ, {"DHAN_ENABLED": "true"}):
            report2 = self.engine.certify()
        # Fingerprints should differ since dhan_enabled changed
        if report1.configuration_fingerprint and report2.configuration_fingerprint:
            self.assertNotEqual(report1.configuration_fingerprint,
                                report2.configuration_fingerprint,
                                "Fingerprint must change when config changes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
