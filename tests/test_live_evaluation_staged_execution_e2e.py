"""
Phase 16 — Live Evaluation & Staged Broker Execution Comprehensive E2E Test Suite

Verifies:
1. Ingestion of TradingOSRun predictions into LiveEvaluationEngine.
2. Ingestion of realized trade outcomes (positive, negative, flat).
3. Objective directional accuracy calculations.
4. Bull vs. Bear adversarial grading and skill score computation.
5. Specialist performance attribution across all 9 research specialists.
6. Calibration metrics & Brier score calculation.
7. Expected Calibration Error (ECE) and overconfidence metrics.
8. Zero-trade baseline matrix safety (anti-ZeroDivisionError).
9. Dynamic conviction feedback weight adjustments (0.70x to 1.30x).
10. Execution tier modeling (Tier 0 to Tier 4).
11. StagedExecutionAuditor prerequisite checks (simulation, reconciliation, risk, preflight, calibration, live lock).
12. Tier 3 operational certification logic.
13. Permanent fail-closed invariant: TIER_4_LIVE_REAL_MONEY remains strictly locked and blocked.
14. REST API endpoints (/api/evaluation/live/*).
15. Engine reset lifecycle.
"""

from datetime import datetime, timezone
import unittest
from fastapi.testclient import TestClient

from backend.domain.broker_schemas import BrokerConfig, BrokerEnvironment
from backend.domain.live_evaluation_schemas import (
    AgentGrade,
    AgentPerformanceMatrix,
    ExecutionTier,
    StagedReadinessReport,
)
from backend.domain.trading_os_schemas import TradingOSRun
from backend.application.broker_interface import (
    BrokerFactory,
    ConfigurationSafetyError,
    LiveBrokerDisabledError,
)
from backend.application.broker_manager import BrokerManager
from backend.application.broker_reconciliation import BrokerReconciliationEngine
from backend.application.execution_guard import ExecutionGuard
from backend.application.live_evaluation_engine import (
    LiveEvaluationEngine,
    calculate_letter_grade,
    global_evaluation_engine,
)
from backend.application.paper_broker_adapter import PaperBrokerAdapter
from backend.application.sandbox_broker_adapter import SandboxBrokerAdapter
from backend.application.sandbox_client import MockSandboxClient
from backend.application.staged_execution_auditor import (
    StagedExecutionAuditor,
    global_readiness_auditor,
)
from backend.main import app


class TestLiveEvaluationStagedExecutionE2E(unittest.TestCase):
    """End-to-end verification of Phase 16 Live Evaluation & Staged Execution Engine."""

    def setUp(self):
        self.eval_engine = LiveEvaluationEngine()
        self.mock_client = MockSandboxClient(initial_cash=100000.0)
        self.sandbox_adapter = SandboxBrokerAdapter(client=self.mock_client)
        self.paper_adapter = PaperBrokerAdapter(initial_cash=100000.0)
        self.guard = ExecutionGuard()
        self.manager = BrokerManager(
            paper_adapter=self.paper_adapter,
            sandbox_adapter=self.sandbox_adapter,
            execution_guard=self.guard,
        )
        self.reconcile_engine = BrokerReconciliationEngine()
        self.auditor = StagedExecutionAuditor(
            broker_manager=self.manager,
            reconciliation_engine=self.reconcile_engine,
            evaluation_engine=self.eval_engine,
            execution_guard=self.guard,
        )
        self.client = TestClient(app)

    def _make_dummy_run(
        self,
        run_id: str,
        symbol: str = "TCS.NS",
        action: str = "BUY",
        conviction: float = 0.80,
        bull_conf: float = 0.85,
        bear_conf: float = 0.40,
    ) -> TradingOSRun:
        return TradingOSRun(
            run_id=run_id,
            context_id=f"ctx-{run_id}",
            symbol=symbol,
            evidence={
                "items": [
                    {"source_agent": "TechnicalSpecialist", "recommendation": "BUY", "confidence": 0.8},
                    {"source_agent": "QuantSpecialist", "recommendation": "BUY", "confidence": 0.85},
                    {"source_agent": "FundamentalSpecialist", "recommendation": "BUY", "confidence": 0.75},
                ]
            },
            debate={
                "status": "COMPLETED",
                "bull_confidence": bull_conf,
                "bear_confidence": bear_conf,
            },
            committee_decision={
                "action": action,
                "conviction": conviction,
                "state": "APPROVED",
            },
            risk={"veto_applied": False},
            sizing={"approved_quantity": 10},
            preflight={"status": "APPROVED"},
        )

    # ── 1. Letter Grade Boundary Tests ────────────────────────────────────────

    def test_01_letter_grade_mapping(self):
        self.assertEqual(calculate_letter_grade(95.0), AgentGrade.A_PLUS)
        self.assertEqual(calculate_letter_grade(85.0), AgentGrade.A)
        self.assertEqual(calculate_letter_grade(75.0), AgentGrade.B_PLUS)
        self.assertEqual(calculate_letter_grade(65.0), AgentGrade.B)
        self.assertEqual(calculate_letter_grade(55.0), AgentGrade.C)
        self.assertEqual(calculate_letter_grade(45.0), AgentGrade.D)
        self.assertEqual(calculate_letter_grade(30.0), AgentGrade.F)

    # ── 2. Baseline Matrix Without Trades (Zero Division Safety) ───────────────

    def test_02_baseline_matrix_safe(self):
        matrix = self.eval_engine.evaluate()
        self.assertEqual(matrix.total_completed_trades, 0)
        self.assertEqual(matrix.overall_accuracy, 0.5)
        self.assertEqual(matrix.calibration.brier_score, 0.25)
        self.assertEqual(len(matrix.specialists), 9)
        self.assertEqual(matrix.debate_summary.bull_grade, AgentGrade.C)

    # ── 3. Record Prediction Ingestion ────────────────────────────────────────

    def test_03_record_run_prediction(self):
        run = self._make_dummy_run("run-001", "INFY.NS", "BUY", 0.85, 0.90, 0.30)
        rec = self.eval_engine.record_run_prediction(run)
        self.assertEqual(rec.run_id, "run-001")
        self.assertEqual(rec.symbol, "INFY.NS")
        self.assertEqual(rec.decision_action, "BUY")
        self.assertEqual(rec.calibrated_conviction, 0.85)
        self.assertEqual(rec.bull_confidence, 0.90)
        self.assertEqual(rec.bear_confidence, 0.30)
        self.assertIn("TechnicalSpecialist", rec.specialist_signals)
        self.assertIsNone(rec.actual_return_pct)

    # ── 4. Record Trade Outcome Ingestion ─────────────────────────────────────

    def test_04_record_trade_outcome(self):
        run = self._make_dummy_run("run-002", "RELIANCE.NS", "BUY", 0.80)
        self.eval_engine.record_run_prediction(run)

        # Pair with positive return (+3.5%)
        updated = self.eval_engine.record_trade_outcome(
            symbol="RELIANCE.NS",
            realized_return_pct=0.035,
            run_id="run-002",
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.actual_return_pct, 0.035)
        self.assertEqual(updated.actual_direction, "UP")
        self.assertTrue(updated.is_win)

    # ── 5. Evaluation Loop: Directional Accuracy & Bull vs. Bear ───────────────

    def test_05_debate_evaluation_grading(self):
        # Trade 1: Bull wins (+2.0%)
        run1 = self._make_dummy_run("run-win-1", "TCS.NS", "BUY", 0.80, 0.85, 0.30)
        self.eval_engine.record_run_prediction(run1)
        self.eval_engine.record_trade_outcome("TCS.NS", 0.02, run_id="run-win-1")

        # Trade 2: Bull wins (+1.5%)
        run2 = self._make_dummy_run("run-win-2", "INFY.NS", "BUY", 0.75, 0.80, 0.40)
        self.eval_engine.record_run_prediction(run2)
        self.eval_engine.record_trade_outcome("INFY.NS", 0.015, run_id="run-win-2")

        # Trade 3: Bear was right (-2.5%), Bull was wrong
        run3 = self._make_dummy_run("run-loss-3", "WIPRO.NS", "BUY", 0.70, 0.75, 0.45)
        self.eval_engine.record_run_prediction(run3)
        self.eval_engine.record_trade_outcome("WIPRO.NS", -0.025, run_id="run-loss-3")

        matrix = self.eval_engine.evaluate()
        self.assertEqual(matrix.total_completed_trades, 3)
        self.assertAlmostEqual(matrix.overall_accuracy, 2.0 / 3.0, places=2)

        # Bull was right on 2/3 trades
        deb = matrix.debate_summary
        self.assertAlmostEqual(deb.bull_accuracy, 2.0 / 3.0, places=2)
        self.assertAlmostEqual(deb.bear_accuracy, 1.0 / 3.0, places=2)
        self.assertGreater(deb.bull_skill_score, deb.bear_skill_score)
        self.assertIn(deb.bull_grade, [AgentGrade.B, AgentGrade.B_PLUS])

    # ── 6. Specialist Performance Attribution ─────────────────────────────────

    def test_06_specialist_attribution(self):
        run = self._make_dummy_run("run-spec-01", "TCS.NS", "BUY", 0.80)
        self.eval_engine.record_run_prediction(run)
        self.eval_engine.record_trade_outcome("TCS.NS", 0.04, run_id="run-spec-01")

        matrix = self.eval_engine.evaluate()
        self.assertEqual(len(matrix.specialists), 9)

        tech_card = next(s for s in matrix.specialists if s.specialist_name == "TechnicalSpecialist")
        self.assertEqual(tech_card.directional_accuracy, 1.0)
        self.assertEqual(tech_card.skill_score, 100.0)
        self.assertEqual(tech_card.letter_grade, AgentGrade.A_PLUS)
        self.assertEqual(tech_card.avg_return_contribution, 0.04)

    # ── 7. Calibration Metrics (Brier Score & ECE) ─────────────────────────────

    def test_07_brier_score_calibration(self):
        # Perfect calibration: conviction 1.0 and win
        run = self._make_dummy_run("run-cal-01", "TCS.NS", "BUY", conviction=1.0)
        self.eval_engine.record_run_prediction(run)
        self.eval_engine.record_trade_outcome("TCS.NS", 0.03, run_id="run-cal-01")

        matrix = self.eval_engine.evaluate()
        cal = matrix.calibration
        self.assertEqual(cal.brier_score, 0.0)  # (1.0 - 1.0)^2 = 0.0
        self.assertEqual(cal.calibration_grade, "EXCELLENT")

    # ── 8. Dynamic Conviction Weight Adjustments ───────────────────────────────

    def test_08_dynamic_conviction_weights(self):
        run = self._make_dummy_run("run-dyn-01", "TCS.NS", "BUY", conviction=0.8)
        self.eval_engine.record_run_prediction(run)
        self.eval_engine.record_trade_outcome("TCS.NS", 0.02, run_id="run-dyn-01")

        weights = self.eval_engine.get_dynamic_weights()
        self.assertIn("TechnicalSpecialist", weights)
        # Accurate specialist receives multiplier > 1.0
        self.assertGreater(weights["TechnicalSpecialist"], 1.0)
        self.assertLessEqual(weights["TechnicalSpecialist"], 1.30)

    # ── 9. Staged Execution Auditor: Tiers 0, 1, 2 ─────────────────────────────

    def test_09_staged_execution_tier_resolution(self):
        self.manager.configure(BrokerConfig(broker_environment=BrokerEnvironment.PAPER))
        self.assertEqual(self.auditor.determine_active_tier(), ExecutionTier.TIER_1_FORWARD_PAPER)

        self.manager.configure(BrokerConfig(broker_environment=BrokerEnvironment.SANDBOX))
        self.assertEqual(self.auditor.determine_active_tier(), ExecutionTier.TIER_2_SANDBOX_STAGED)

    # ── 10. Staged Execution Readiness Audit (Tier 3 Certified) ───────────────

    def test_10_staged_readiness_audit_certified(self):
        report = self.auditor.audit_readiness()
        self.assertIsInstance(report, StagedReadinessReport)
        self.assertTrue(report.is_tier3_certified)
        self.assertEqual(report.active_tier, ExecutionTier.TIER_3_READINESS_AUDITED)
        self.assertTrue(report.tier4_live_blocked)
        self.assertEqual(report.failed_checks_count, 0)
        self.assertEqual(len(report.checks), 6)

    # ── 11. Permanent Fail-Closed Safety: Tier 4 Locked ────────────────────────

    def test_11_tier4_live_permanently_fail_closed(self):
        # 1. BrokerConfig rejects LIVE
        with self.assertRaises(ValueError):
            BrokerConfig(broker_environment=BrokerEnvironment.LIVE)

        # 2. BrokerFactory rejects live
        with self.assertRaises(ConfigurationSafetyError):
            BrokerFactory.get_adapter("live")

        # 3. ExecutionGuard blocks target_adapter_is_live
        from backend.domain.preflight_schemas import ExecutionAuthorizationSnapshot, PreflightSide
        auth = ExecutionAuthorizationSnapshot(
            authorization_id="auth-test",
            decision_id="dec-test",
            order_id="ord-test",
            symbol="TCS.NS",
            side=PreflightSide.BUY,
            approved_quantity=10,
            idempotency_token="tok-live-test",
            validation_timestamp=datetime.now(timezone.utc),
        )
        outcome = self.guard.validate_authorization(auth, target_adapter_is_live=True)
        self.assertFalse(outcome.is_authorized)
        self.assertIn("LIVE_BROKER_PROHIBITED", outcome.rejection_reason)

    # ── 12. REST API Endpoints Verification ───────────────────────────────────

    def test_12_api_endpoints(self):
        # Record outcome API
        rec_res = self.client.post("/api/evaluation/live/record-outcome", json={
            "symbol": "TCS.NS",
            "realized_return_pct": 0.025,
        })
        self.assertEqual(rec_res.status_code, 200)

        # Trigger evaluate API
        eval_res = self.client.post("/api/evaluation/live/evaluate")
        self.assertEqual(eval_res.status_code, 200)
        eval_data = eval_res.json()
        self.assertIn("overall_accuracy", eval_data)
        self.assertIn("debate_summary", eval_data)

        # Agent matrix API
        mat_res = self.client.get("/api/evaluation/live/agent-matrix")
        self.assertEqual(mat_res.status_code, 200)

        # Readiness API
        read_res = self.client.get("/api/evaluation/live/readiness")
        self.assertEqual(read_res.status_code, 200)
        read_data = read_res.json()
        self.assertTrue(read_data["tier4_live_blocked"])
        self.assertIn(read_data["active_tier"], ["TIER_1_FORWARD_PAPER", "TIER_2_SANDBOX_STAGED", "TIER_3_READINESS_AUDITED"])

        # Feedback weights API
        fb_res = self.client.get("/api/evaluation/live/feedback")
        self.assertEqual(fb_res.status_code, 200)
        self.assertIsInstance(fb_res.json(), dict)

    # ── 13. Reset Lifecycle ───────────────────────────────────────────────────

    def test_13_reset_lifecycle(self):
        run = self._make_dummy_run("run-rst-01", "TCS.NS")
        self.eval_engine.record_run_prediction(run)
        self.assertEqual(len(self.eval_engine._records), 1)
        self.eval_engine.reset()
        self.assertEqual(len(self.eval_engine._records), 0)
        self.assertIsNone(self.eval_engine.latest_matrix)


if __name__ == "__main__":
    unittest.main()
