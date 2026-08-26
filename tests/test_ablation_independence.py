"""
Unit tests for Ablation Independence Auditor — Phase 5.5

Validates verification of distinct sub-pipeline execution signatures across all 6 variants.
"""

import unittest

from backend.validation.ablation_independence_audit import AblationIndependenceAuditor
from backend.validation.ablation_runner import RealAblationVariantResult


class TestAblationIndependence(unittest.TestCase):
    def test_audit_passes_for_six_distinct_variants(self):
        variants = [
            RealAblationVariantResult(
                variant_name="Variant A: Technical Only", description="", specialists_executed=["TechnicalSpecialist"],
                debate_enabled=False, committee_enabled=False, safety_enabled=False, llm_calls=1, contexts_processed=1,
                total_return_pct=7.85, cagr_pct=7.85, max_drawdown_pct=11.2, win_rate=48.5, trades=5, turnover=1.0,
            ),
            RealAblationVariantResult(
                variant_name="Variant B: Tech + Momentum", description="", specialists_executed=["TechnicalSpecialist", "MomentumSpecialist"],
                debate_enabled=False, committee_enabled=False, safety_enabled=False, llm_calls=2, contexts_processed=1,
                total_return_pct=9.95, cagr_pct=9.95, max_drawdown_pct=9.8, win_rate=53.0, trades=6, turnover=1.2,
            ),
            RealAblationVariantResult(
                variant_name="Variant C: Tech + Mom + Quant", description="", specialists_executed=["TechnicalSpecialist", "MomentumSpecialist", "QuantSpecialist"],
                debate_enabled=False, committee_enabled=False, safety_enabled=False, llm_calls=3, contexts_processed=1,
                total_return_pct=11.40, cagr_pct=11.40, max_drawdown_pct=8.9, win_rate=56.2, trades=7, turnover=1.4,
            ),
            RealAblationVariantResult(
                variant_name="Variant D: All 9 Specialists", description="", specialists_executed=["TechnicalSpecialist", "MomentumSpecialist", "QuantSpecialist", "FundamentalSpecialist", "ValuationSpecialist", "SectorSpecialist", "MacroSpecialist", "NewsSpecialist", "InstitutionalSpecialist"],
                debate_enabled=False, committee_enabled=False, safety_enabled=False, llm_calls=9, contexts_processed=1,
                total_return_pct=12.85, cagr_pct=12.85, max_drawdown_pct=8.1, win_rate=58.8, trades=8, turnover=1.6,
            ),
            RealAblationVariantResult(
                variant_name="Variant E: 9 Specialists + Debate", description="", specialists_executed=["TechnicalSpecialist", "MomentumSpecialist", "QuantSpecialist", "FundamentalSpecialist", "ValuationSpecialist", "SectorSpecialist", "MacroSpecialist", "NewsSpecialist", "InstitutionalSpecialist"],
                debate_enabled=True, committee_enabled=False, safety_enabled=False, llm_calls=12, contexts_processed=1,
                total_return_pct=13.90, cagr_pct=13.90, max_drawdown_pct=7.65, win_rate=60.5, trades=9, turnover=1.8,
            ),
            RealAblationVariantResult(
                variant_name="Variant F: Full Pipeline", description="", specialists_executed=["TechnicalSpecialist", "MomentumSpecialist", "QuantSpecialist", "FundamentalSpecialist", "ValuationSpecialist", "SectorSpecialist", "MacroSpecialist", "NewsSpecialist", "InstitutionalSpecialist"],
                debate_enabled=True, committee_enabled=True, safety_enabled=True, llm_calls=13, contexts_processed=1,
                total_return_pct=14.80, cagr_pct=14.80, max_drawdown_pct=7.20, win_rate=62.5, trades=10, turnover=2.1,
            ),
        ]
        res = AblationIndependenceAuditor.audit_ablation_results(variants)
        self.assertTrue(res.is_fully_independent)
        self.assertEqual(len(res.isolation_violations), 0)


if __name__ == "__main__":
    unittest.main()
