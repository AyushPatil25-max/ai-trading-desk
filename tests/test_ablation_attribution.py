"""
Unit tests for Ablation Studies & Specialist Attributions — Phase 5.4

Validates pipeline variant ablation testing (Tech -> Mom -> Quant -> 9 Specialists -> Debate -> Committee)
and individual specialist contributions.
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
from backend.validation.robustness import RobustnessEngine


class TestAblationAttribution(unittest.TestCase):
    def setUp(self):
        self.engine = RobustnessEngine()
        self.metrics = PerformanceMetrics(
            initial_capital=100000.0,
            final_capital=120000.0,
            total_return_pct=20.0,
            annualized_volatility=12.0,
            max_drawdown_pct=6.5,
            sharpe_ratio=1.65,
            win_rate=65.0,
            profit_factor=2.10,
            total_trades=10,
        )
        self.trade_journal = [
            TradeJournalEntry(
                trade_id="t1",
                order_id="o1",
                timestamp=datetime(2023, 1, 1),
                symbol="TCS.NS",
                side=OrderSide.BUY,
                quantity=10.0,
                requested_price=3000.0,
                executed_price=3000.0,
                realized_pnl=2000.0,
                context_id="c1",
                committee_decision_state=InvestmentDecisionState.APPROVE,
                confidence=0.85,
                execution_decision=ExecutionDecision.ALLOWED,
                order_status=OrderStatus.FILLED,
            )
        ]

    def test_ablation_evaluates_all_pipeline_variants(self):
        ablation = self.engine.evaluate_ablation(self.metrics)
        variant_names = [a.pipeline_variant for a in ablation]

        self.assertTrue(any("Variant A" in v for v in variant_names))
        self.assertTrue(any("Variant B" in v for v in variant_names))
        self.assertTrue(any("Variant C" in v for v in variant_names))
        self.assertTrue(any("Variant D" in v for v in variant_names))
        self.assertTrue(any("Variant E" in v for v in variant_names))
        self.assertTrue(any("Variant F" in v for v in variant_names))

        # Full pipeline should show peak return
        var_f = next(a for a in ablation if "Variant F" in a.pipeline_variant)
        var_a = next(a for a in ablation if "Variant A" in a.pipeline_variant)
        self.assertGreater(var_f.total_return_pct, var_a.total_return_pct)

    def test_specialist_attribution_evaluates_all_9_specialists(self):
        specialists = self.engine.evaluate_specialist_attribution(self.trade_journal)
        self.assertEqual(len(specialists), 9)
        names = [s.specialist_name for s in specialists]

        self.assertIn("TechnicalSpecialist", names)
        self.assertIn("FundamentalSpecialist", names)
        self.assertIn("InstitutionalSpecialist", names)


if __name__ == "__main__":
    unittest.main()
