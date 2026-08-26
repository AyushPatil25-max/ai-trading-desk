"""
Unit tests for Empirical Runner Integrity Auditor — Phase 5.4B

Validates trade lineage reconstruction, specialist execution mode audits,
parametric proxy detection, and forensic run classification.
"""

from datetime import datetime
import unittest

from backend.domain.execution_schemas import (
    ExecutionDecision,
    OrderSide,
    OrderStatus,
)
from backend.domain.investment_committee_schemas import InvestmentDecisionState
from backend.simulation.simulation_state import PerformanceMetrics, TradeJournalEntry
from backend.validation.integrity_auditor import (
    AuditClassification,
    EmpiricalIntegrityAuditor,
    ExecutionMode,
    TradeLineageRecord,
)
from backend.validation.validation_state import (
    AblationResult,
    BaselineStrategyResult,
    LeakageFinding,
    LeakageSeverity,
    ValidationScorecard,
    WalkForwardResult,
    WalkForwardWindow,
)


class TestIntegrityAuditor(unittest.TestCase):
    def setUp(self):
        self.metrics = PerformanceMetrics(
            initial_capital=100000.0,
            final_capital=114800.0,
            total_return_pct=14.8,
            annualized_volatility=13.5,
            max_drawdown_pct=7.2,
            sharpe_ratio=1.42,
            win_rate=62.5,
            profit_factor=1.92,
            total_trades=10,
        )
        self.scorecard = ValidationScorecard(
            predictive_quality_score=75.0,
            risk_adjusted_score=75.0,
            drawdown_score=78.0,
            consistency_score=80.0,
            robustness_score=80.0,
            data_quality_score=100.0,
            out_of_sample_score=80.0,
            overall_validation_score=78.0,
            passed_validation=True,
            summary="Passed",
        )
        self.result = WalkForwardResult(
            run_id="wf-test-audit",
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 12, 31),
            windows=[
                WalkForwardWindow(
                    window_index=0,
                    train_start=datetime(2022, 1, 1),
                    train_end=datetime(2022, 6, 1),
                    val_start=datetime(2022, 6, 1),
                    val_end=datetime(2022, 12, 31),
                    test_start=datetime(2023, 1, 1),
                    test_end=datetime(2023, 12, 31),
                    is_valid=True,
                )
            ],
            overall_out_of_sample_metrics=self.metrics,
            baseline_comparisons=[
                BaselineStrategyResult(strategy_name="Buy-and-Hold Benchmark (^NSEI)", total_return_pct=8.5)
            ],
            ablation_results=[
                AblationResult(pipeline_variant="Variant A: Technical Only", description="", total_return_pct=8.14)
            ],
            scorecard=self.scorecard,
        )

    def test_audit_detects_parametric_proxies_and_classifies_partially_valid(self):
        report = EmpiricalIntegrityAuditor.audit_walk_forward_run(
            result=self.result,
            historical_datasets={"TCS.NS": {}},
        )
        self.assertEqual(report.audit_classification, AuditClassification.PARTIALLY_VALID_EMPIRICAL_RUN)
        self.assertGreater(len(report.synthetic_proxy_findings), 0)
        self.assertFalse(report.ablation_independence_verified)
        self.assertFalse(report.baseline_independence_verified)

    def test_audit_flags_leakage_as_invalid_run(self):
        leaked_res = self.result.model_copy(deep=True)
        leaked_res.windows[0].leakage_findings.append(
            LeakageFinding(
                category="OHLCV",
                symbol="TCS.NS",
                context_id="c1",
                offending_timestamp=datetime(2024, 1, 1),
                decision_timestamp=datetime(2023, 1, 1),
                source="NSE",
                severity=LeakageSeverity.CRITICAL,
                description="Future bar",
            )
        )
        report = EmpiricalIntegrityAuditor.audit_walk_forward_run(
            result=leaked_res,
            historical_datasets={"TCS.NS": {}},
        )
        self.assertEqual(report.audit_classification, AuditClassification.INVALID_EMPIRICAL_RUN)
        self.assertGreater(report.pit_violations_count, 0)

    def test_specialist_execution_summary(self):
        report = EmpiricalIntegrityAuditor.audit_walk_forward_run(
            result=self.result,
            historical_datasets={"TCS.NS": {}},
        )
        self.assertEqual(report.specialist_execution_summary["TechnicalSpecialist"], ExecutionMode.EXECUTED)
        self.assertEqual(report.specialist_execution_summary["NewsSpecialist"], ExecutionMode.DEGRADED)


if __name__ == "__main__":
    unittest.main()
