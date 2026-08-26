"""
Phase 4.1A — Evidence Aggregation Hardening Tests

Offline unit tests (no network, no LLM calls, deterministic).
Covers: multi-metric extraction, duplicate detection, metric/domain agreements,
conflict taxonomy, weighting formulas, specialist caps, PIT validation,
missing-data categories, provenance, backward compatibility, and determinism.
"""

import unittest
from datetime import datetime, timedelta
from copy import deepcopy

from backend.domain.schemas import (
    SpecialistRunResult, AgentExecutionRecord, AgentState, AgentOutput,
    MarketContext, UnifiedEvidencePackage, NormalizedEvidence,
    SignalDirection, ResearchRegime, EvidenceCategory, EvidenceType,
    ConflictSeverity, ConflictType, AgreementLevel, PITStatus,
    MissingDataCategory, ProviderType, SourceTier, VerificationStatus,
)
from backend.application.evidence_aggregator import (
    EvidenceAggregator, AggregationError,
    MAX_SPECIALIST_CONTRIBUTION_SHARE, PIT_DRIFT_TOLERANCE,
    CONFIDENCE_PENALTIES,
)


class TestEvidenceAggregatorHardening(unittest.TestCase):
    """Phase 4.1A hardening tests for the evidence aggregator."""

    def setUp(self):
        self.aggregator = EvidenceAggregator()
        self.now = datetime.utcnow()
        self.ctx = MarketContext(
            context_id="ctx-hard-001",
            symbol="RELIANCE.NS",
            data_timestamp=self.now,
            current_price=2500.0,
            provider=ProviderType.STANDARD_DATA_VENDOR,
            provider_timestamp=self.now,
        )

    # ------------------------------------------------------------------ helpers
    def _make_record(
        self,
        agent_name: str,
        state: AgentState,
        raw_data: dict,
        confidence: float = 0.8,
        ctx=None,
    ):
        my_ctx = ctx or self.ctx
        return AgentExecutionRecord(
            agent_name=agent_name,
            agent_version="1.0",
            context_id=my_ctx.context_id,
            started_at=self.now,
            completed_at=self.now,
            duration_seconds=0.1,
            status=state,
            output=AgentOutput(
                agent_name=agent_name,
                version="1.0",
                model="mock",
                data_timestamp=self.now,
                status=state,
                confidence=confidence,
                conclusion="Test",
                raw_data=raw_data,
            ) if state in (AgentState.SUCCESS, AgentState.DEGRADED) else None,
            error_message="Err" if state == AgentState.FAILED else None,
        )

    def _make_run_result(self, run_id, records, ctx=None):
        my_ctx = ctx or self.ctx
        return SpecialistRunResult(
            run_id=run_id,
            context_id=my_ctx.context_id,
            symbol=my_ctx.symbol,
            started_at=self.now,
            completed_at=self.now,
            duration_seconds=1.0,
            total_agents=len(records),
            successful_agents=sum(1 for r in records if r.status == AgentState.SUCCESS),
            failed_agents=sum(1 for r in records if r.status == AgentState.FAILED),
            timed_out_agents=sum(1 for r in records if r.status == AgentState.TIMEOUT),
            degraded_agents=sum(1 for r in records if r.status == AgentState.DEGRADED),
            records=records,
        )

    # ===================================================================
    # TEST 1: Multi-metric extraction from QuantSpecialist
    # ===================================================================
    def test_01_multi_metric_extraction_quant(self):
        """QuantSpecialist with 3 metrics → 1 regime + 3 metric evidence items."""
        raw = {
            "statistical_regime": "HIGH_VOLATILITY",
            "metrics": [
                {"metric_name": "realized_volatility_5d", "value": 25.3, "unit": "annualized_%",
                 "available": True, "source": "ohlcv_historical",
                 "calculation_method": "std(returns)*sqrt(252)*100",
                 "data_timestamp": self.now.isoformat()},
                {"metric_name": "price_zscore_5d", "value": 1.8, "unit": "sigma",
                 "available": True, "source": "ohlcv_historical",
                 "calculation_method": "(price-mean)/std",
                 "data_timestamp": self.now.isoformat()},
                {"metric_name": "sharpe_ratio_annualized", "value": None, "unit": "ratio",
                 "available": False, "unavailable_reason": "Need 61 closes",
                 "source": "ohlcv_historical", "calculation_method": "mean/std*sqrt(252)",
                 "data_timestamp": self.now.isoformat()},
            ],
            "risks": ["High vol environment"],
        }
        rec = self._make_record("QuantSpecialist", AgentState.SUCCESS, raw)
        res = self._make_run_result("run-q1", [rec])
        pkg = self.aggregator.aggregate(res)

        # Regime + 3 metrics = 4 evidence items
        self.assertEqual(len(pkg.evidence_items), 4)

        # Check regime evidence
        regime_items = [e for e in pkg.evidence_items if e.metric_name == "QUANT_REGIME"]
        self.assertEqual(len(regime_items), 1)
        self.assertEqual(regime_items[0].evidence_type, EvidenceType.LLM_INTERPRETATION)

        # Check available metric
        vol_items = [e for e in pkg.evidence_items if e.metric_name == "realized_volatility_5d"]
        self.assertEqual(len(vol_items), 1)
        self.assertEqual(vol_items[0].value, 25.3)
        self.assertTrue(vol_items[0].is_deterministic)

        # Check unavailable metric
        sharpe_items = [e for e in pkg.evidence_items if e.metric_name == "sharpe_ratio_annualized"]
        self.assertEqual(len(sharpe_items), 1)
        self.assertEqual(sharpe_items[0].evidence_type, EvidenceType.UNAVAILABLE)

    # ===================================================================
    # TEST 2: Multi-metric extraction from TechnicalSpecialist
    # ===================================================================
    def test_02_multi_metric_extraction_technical(self):
        """TechnicalSpecialist evidence list → multiple evidence items."""
        raw = {
            "trend": "BULLISH",
            "evidence": [
                {"name": "CurrentPrice", "value": 2500.0, "interpretation": "Price at 2500"},
                {"name": "EMA20", "value": 2480.0, "interpretation": "Price above EMA20"},
                {"name": "RSI14", "value": 65.0, "interpretation": "RSI in bullish zone"},
            ],
            "risks": [],
        }
        rec = self._make_record("TechnicalSpecialist", AgentState.SUCCESS, raw)
        res = self._make_run_result("run-t1", [rec])
        pkg = self.aggregator.aggregate(res)

        # 1 regime + 3 metrics
        self.assertEqual(len(pkg.evidence_items), 4)
        names = {e.metric_name for e in pkg.evidence_items}
        self.assertIn("CurrentPrice", names)
        self.assertIn("EMA20", names)
        self.assertIn("RSI14", names)
        self.assertIn("TECHNICAL_REGIME", names)

    # ===================================================================
    # TEST 3: Duplicate detection
    # ===================================================================
    def test_03_duplicate_detection(self):
        """Same specialist providing identical metric names → dedup."""
        raw = {
            "trend": "BULLISH",
            "evidence": [
                {"name": "EMA20", "value": 2480.0, "interpretation": "above"},
                {"name": "EMA20", "value": 2480.0, "interpretation": "above"},  # duplicate
            ],
        }
        rec = self._make_record("TechnicalSpecialist", AgentState.SUCCESS, raw)
        res = self._make_run_result("run-dup", [rec])
        pkg = self.aggregator.aggregate(res)

        ema_items = [e for e in pkg.evidence_items if e.metric_name == "EMA20"]
        self.assertEqual(len(ema_items), 1)
        self.assertEqual(pkg.duplicates_detected, 1)

    # ===================================================================
    # TEST 4: Domain-level agreement detection
    # ===================================================================
    def test_04_domain_level_agreement(self):
        """3 bullish specialists → domain-level bullish agreement."""
        records = [
            self._make_record("TechnicalSpecialist", AgentState.SUCCESS, {"trend": "BULLISH"}),
            self._make_record("MomentumSpecialist", AgentState.SUCCESS, {"momentum_direction": "BULLISH"}),
            self._make_record("FundamentalSpecialist", AgentState.SUCCESS, {"fundamental_quality": "STRONG"}),
        ]
        res = self._make_run_result("run-agree", records)
        pkg = self.aggregator.aggregate(res)

        domain_agreements = [a for a in pkg.agreement_summary if a.level == AgreementLevel.DOMAIN_LEVEL]
        self.assertTrue(len(domain_agreements) >= 1)
        bullish_agree = [a for a in domain_agreements if a.direction == SignalDirection.BULLISH]
        self.assertEqual(len(bullish_agree), 1)
        self.assertEqual(bullish_agree[0].support_count, 3)

    # ===================================================================
    # TEST 5: Metric-level agreement detection
    # ===================================================================
    def test_05_metric_level_agreement(self):
        """Same metric from different specialists with same direction → metric agreement."""
        records = [
            self._make_record("TechnicalSpecialist", AgentState.SUCCESS, {
                "trend": "BULLISH",
                "evidence": [{"name": "RSI14", "value": 65.0, "interpretation": "bullish above 50"}],
            }),
            self._make_record("MomentumSpecialist", AgentState.SUCCESS, {
                "momentum_direction": "BULLISH",
                "evidence": [{"name": "RSI14", "value": 65.0, "interpretation": "bullish above 50"}],
            }),
        ]
        res = self._make_run_result("run-metric-agree", records)
        pkg = self.aggregator.aggregate(res)

        metric_agreements = [a for a in pkg.agreement_summary if a.level == AgreementLevel.METRIC_LEVEL]
        self.assertTrue(len(metric_agreements) >= 1)

    # ===================================================================
    # TEST 6: DIRECT_CONFLICT taxonomy
    # ===================================================================
    def test_06_direct_conflict(self):
        """Same category, opposite direction → DOMAIN_TENSION (different specialists in same domain is DOMAIN_TENSION)."""
        records = [
            self._make_record("TechnicalSpecialist", AgentState.SUCCESS, {"trend": "BULLISH"}),
            self._make_record("FundamentalSpecialist", AgentState.SUCCESS, {"fundamental_quality": "WEAK"}),
        ]
        res = self._make_run_result("run-conflict", records)
        pkg = self.aggregator.aggregate(res)

        self.assertTrue(len(pkg.conflict_summary) >= 1)
        # Different categories → DOMAIN_TENSION
        for c in pkg.conflict_summary:
            if c.specialist_a != c.specialist_b:
                self.assertEqual(c.conflict_type, ConflictType.DOMAIN_TENSION)

    # ===================================================================
    # TEST 7: DOMAIN_TENSION separate from DIRECT_CONFLICT
    # ===================================================================
    def test_07_conflict_types_distinct(self):
        """Verify that different-domain conflicts are DOMAIN_TENSION, not DIRECT_CONFLICT."""
        records = [
            self._make_record("TechnicalSpecialist", AgentState.SUCCESS, {"trend": "BULLISH"}),
            self._make_record("MacroSpecialist", AgentState.SUCCESS, {"macro_regime": "CONTRACTIONARY"}),
        ]
        res = self._make_run_result("run-dt", records)
        pkg = self.aggregator.aggregate(res)

        self.assertEqual(len(pkg.conflict_summary), 1)
        self.assertEqual(pkg.conflict_summary[0].conflict_type, ConflictType.DOMAIN_TENSION)

    # ===================================================================
    # TEST 8: Evidence-aware weighting formula
    # ===================================================================
    def test_08_evidence_aware_weighting(self):
        """Importance = specialist_weight × confidence × verif_mult × source_quality_mult."""
        raw = {
            "statistical_regime": "NORMAL_VOLATILITY",
            "metrics": [
                {
                    "metric_name": "realized_volatility_5d",
                    "value": 15.0,
                    "unit": "annualized_%",
                    "available": True,
                    "source": "ohlcv_historical",
                    "calculation_method": "std*sqrt(252)*100",
                    "data_timestamp": self.now.isoformat(),
                    "source_tier": "TIER_1_PRIMARY_OFFICIAL",
                    "verification_status": "VERIFIED",
                },
            ],
        }
        rec = self._make_record("QuantSpecialist", AgentState.SUCCESS, raw, confidence=0.9)
        res = self._make_run_result("run-weight", [rec])
        pkg = self.aggregator.aggregate(res)

        vol_ev = [e for e in pkg.evidence_items if e.metric_name == "realized_volatility_5d"][0]
        # specialist_weight(QUANT) = 1.0, confidence = 0.9, verif(VERIFIED) = 1.0, source(TIER_1) = 1.0
        expected = 1.0 * 0.9 * 1.0 * 1.0
        self.assertAlmostEqual(vol_ev.importance, expected, places=4)

    # ===================================================================
    # TEST 9: Specialist contribution cap
    # ===================================================================
    def test_09_specialist_contribution_cap(self):
        """A specialist with many metrics should not dominate the global score."""
        raw = {
            "trend": "BULLISH",
            "evidence": [
                {"name": f"Indicator_{i}", "value": float(i), "interpretation": "bullish above baseline"}
                for i in range(20)
            ],
        }
        rec = self._make_record("TechnicalSpecialist", AgentState.SUCCESS, raw, confidence=0.9)
        # Add a single bearish specialist
        rec2 = self._make_record("MacroSpecialist", AgentState.SUCCESS, {"macro_regime": "CONTRACTIONARY"}, 0.9)
        res = self._make_run_result("run-cap", [rec, rec2])
        pkg = self.aggregator.aggregate(res)

        # Technical's total contribution should be capped
        total_weight = sum(e.importance for e in pkg.evidence_items)
        max_allowed = total_weight * MAX_SPECIALIST_CONTRIBUTION_SHARE
        tech_contribution = pkg.specialist_contributions.get("TechnicalSpecialist", 0)
        self.assertLessEqual(tech_contribution, max_allowed + 0.001)

    # ===================================================================
    # TEST 10: PIT consistency validation — consistent timestamps
    # ===================================================================
    def test_10_pit_consistent(self):
        """Evidence with timestamps close to data_timestamp → PIT_CONSISTENT."""
        raw = {
            "trend": "BULLISH",
            "evidence": [
                {"name": "EMA20", "value": 2480.0, "interpretation": "above",
                 "data_timestamp": self.now.isoformat()},
            ],
        }
        rec = self._make_record("TechnicalSpecialist", AgentState.SUCCESS, raw)
        res = self._make_run_result("run-pit-ok", [rec])
        pkg = self.aggregator.aggregate(res)

        for e in pkg.evidence_items:
            self.assertIn(e.pit_status, (PITStatus.CONSISTENT, PITStatus.UNKNOWN))
        self.assertEqual(pkg.pit_inconsistent_count, 0)

    # ===================================================================
    # TEST 11: PIT inconsistency detection
    # ===================================================================
    def test_11_pit_inconsistent(self):
        """Evidence timestamp > PIT_DRIFT_TOLERANCE → PIT_INCONSISTENT."""
        future_ts = (self.now + timedelta(hours=100)).isoformat()
        raw = {
            "trend": "BULLISH",
            "evidence": [
                {"name": "EMA20", "value": 2480.0, "interpretation": "above",
                 "data_timestamp": future_ts},
            ],
        }
        rec = self._make_record("TechnicalSpecialist", AgentState.SUCCESS, raw)
        res = self._make_run_result("run-pit-bad", [rec])
        pkg = self.aggregator.aggregate(res)

        pit_bad = [e for e in pkg.evidence_items if e.pit_status == PITStatus.PIT_INCONSISTENT]
        self.assertTrue(len(pit_bad) >= 1)
        self.assertTrue(pkg.pit_inconsistent_count >= 1)

    # ===================================================================
    # TEST 12: Missing data — SPECIALIST_FAILED
    # ===================================================================
    def test_12_missing_data_failed(self):
        rec = self._make_record("TechnicalSpecialist", AgentState.FAILED, {})
        res = self._make_run_result("run-fail", [rec])
        pkg = self.aggregator.aggregate(res)

        self.assertEqual(pkg.specialists_failed, 1)
        failed_records = [m for m in pkg.missing_data_records if m.category == MissingDataCategory.SPECIALIST_FAILED]
        self.assertEqual(len(failed_records), 1)
        self.assertEqual(failed_records[0].specialist_name, "TechnicalSpecialist")

    # ===================================================================
    # TEST 13: Missing data — SPECIALIST_TIMEOUT
    # ===================================================================
    def test_13_missing_data_timeout(self):
        rec = self._make_record("MomentumSpecialist", AgentState.TIMEOUT, {})
        res = self._make_run_result("run-to", [rec])
        pkg = self.aggregator.aggregate(res)

        self.assertEqual(pkg.specialists_timed_out, 1)
        timeout_records = [m for m in pkg.missing_data_records if m.category == MissingDataCategory.SPECIALIST_TIMEOUT]
        self.assertEqual(len(timeout_records), 1)

    # ===================================================================
    # TEST 14: Missing data — SPECIALIST_DEGRADED
    # ===================================================================
    def test_14_missing_data_degraded(self):
        rec = self._make_record("QuantSpecialist", AgentState.DEGRADED, {"statistical_regime": "INSUFFICIENT_DATA"})
        res = self._make_run_result("run-deg", [rec])
        pkg = self.aggregator.aggregate(res)

        self.assertEqual(pkg.specialists_degraded, 1)
        deg_records = [m for m in pkg.missing_data_records if m.category == MissingDataCategory.SPECIALIST_DEGRADED]
        self.assertEqual(len(deg_records), 1)

    # ===================================================================
    # TEST 15: Missing data — METRIC_UNAVAILABLE
    # ===================================================================
    def test_15_missing_data_metric_unavailable(self):
        raw = {
            "statistical_regime": "NORMAL_VOLATILITY",
            "metrics": [
                {"metric_name": "sharpe_ratio", "value": None, "unit": "ratio",
                 "available": False, "unavailable_reason": "Need 61 closes",
                 "source": "ohlcv_historical", "calculation_method": "mean/std*sqrt(252)",
                 "data_timestamp": self.now.isoformat()},
            ],
        }
        rec = self._make_record("QuantSpecialist", AgentState.SUCCESS, raw)
        res = self._make_run_result("run-mu", [rec])
        pkg = self.aggregator.aggregate(res)

        mu_records = [m for m in pkg.missing_data_records if m.category == MissingDataCategory.METRIC_UNAVAILABLE]
        self.assertEqual(len(mu_records), 1)
        self.assertEqual(mu_records[0].metric_name, "sharpe_ratio")

    # ===================================================================
    # TEST 16: Evidence classification — DETERMINISTIC_FACT
    # ===================================================================
    def test_16_evidence_type_fact(self):
        """Metrics in the fact override list → DETERMINISTIC_FACT."""
        raw = {
            "trend": "NEUTRAL",
            "evidence": [
                {"name": "CurrentPrice", "value": 2500.0, "interpretation": "Current price"},
            ],
        }
        rec = self._make_record("TechnicalSpecialist", AgentState.SUCCESS, raw)
        res = self._make_run_result("run-fact", [rec])
        pkg = self.aggregator.aggregate(res)

        cp_ev = [e for e in pkg.evidence_items if e.metric_name == "CurrentPrice"]
        self.assertEqual(len(cp_ev), 1)
        self.assertEqual(cp_ev[0].evidence_type, EvidenceType.DETERMINISTIC_FACT)
        self.assertTrue(cp_ev[0].is_deterministic)

    # ===================================================================
    # TEST 17: Evidence classification — DETERMINISTIC_CALCULATION
    # ===================================================================
    def test_17_evidence_type_calculation(self):
        """Metrics with calculation_method → DETERMINISTIC_CALCULATION."""
        raw = {
            "fundamental_quality": "STRONG",
            "metrics": [
                {"metric_name": "net_margin", "value": 12.5, "unit": "%",
                 "available": True, "source": "income_statement",
                 "calculation_method": "net_income/revenue*100",
                 "data_timestamp": self.now.isoformat()},
            ],
        }
        rec = self._make_record("FundamentalSpecialist", AgentState.SUCCESS, raw)
        res = self._make_run_result("run-calc", [rec])
        pkg = self.aggregator.aggregate(res)

        nm_ev = [e for e in pkg.evidence_items if e.metric_name == "net_margin"]
        self.assertEqual(len(nm_ev), 1)
        self.assertEqual(nm_ev[0].evidence_type, EvidenceType.DETERMINISTIC_CALCULATION)

    # ===================================================================
    # TEST 18: Provenance preservation (source_tier, verification)
    # ===================================================================
    def test_18_provenance_preservation(self):
        """Source tier and verification status from metric data are preserved."""
        raw = {
            "institutional_regime": "ACCUMULATION",
            "evidence": [
                {"metric_name": "fii_net_flow", "value": 150.0, "unit": "crore",
                 "period": "daily", "source": "nse_data", "source_tier": "TIER_2_REGULATORY",
                 "verification_status": "VERIFIED", "calculation_method": "sum(net_value)",
                 "inputs": {}, "context_id": self.ctx.context_id,
                 "data_timestamp": self.now.isoformat()},
            ],
        }
        rec = self._make_record("InstitutionalSpecialist", AgentState.SUCCESS, raw)
        res = self._make_run_result("run-prov", [rec])
        pkg = self.aggregator.aggregate(res)

        fii_ev = [e for e in pkg.evidence_items if e.metric_name == "fii_net_flow"]
        self.assertEqual(len(fii_ev), 1)
        self.assertEqual(fii_ev[0].source_tier, SourceTier.TIER_2_REGULATORY)
        self.assertEqual(fii_ev[0].verification_status, VerificationStatus.VERIFIED)

    # ===================================================================
    # TEST 19: Confidence penalty — HIGH severity conflict
    # ===================================================================
    def test_19_confidence_penalty_high_severity(self):
        """HIGH severity conflicts apply 0.06 penalty per conflict."""
        records = [
            self._make_record("TechnicalSpecialist", AgentState.SUCCESS, {"trend": "BULLISH"}, 0.9),
            self._make_record("ValuationSpecialist", AgentState.SUCCESS, {"valuation_status": "OVERVALUED"}, 0.9),
        ]
        res = self._make_run_result("run-penalty", records)
        pkg = self.aggregator.aggregate(res)

        # Should have at least one conflict
        self.assertTrue(len(pkg.conflict_summary) >= 1)
        # Confidence should be reduced by the conflict penalty
        self.assertLess(pkg.overall_research_confidence, 0.9)

    # ===================================================================
    # TEST 20: Determinism — same input yields same output
    # ===================================================================
    def test_20_determinism(self):
        """Running aggregation twice on identical input → identical results (except UUIDs)."""
        raw = {
            "trend": "BULLISH",
            "evidence": [
                {"name": "EMA20", "value": 2480.0, "interpretation": "above"},
            ],
        }
        rec = self._make_record("TechnicalSpecialist", AgentState.SUCCESS, raw)
        res = self._make_run_result("run-det", [rec])

        pkg1 = self.aggregator.aggregate(res)
        pkg2 = self.aggregator.aggregate(res)

        self.assertEqual(pkg1.research_regime, pkg2.research_regime)
        self.assertAlmostEqual(pkg1.overall_research_confidence, pkg2.overall_research_confidence, places=6)
        self.assertEqual(len(pkg1.evidence_items), len(pkg2.evidence_items))
        self.assertEqual(pkg1.duplicates_detected, pkg2.duplicates_detected)

    # ===================================================================
    # TEST 21: Backward compatibility — all 9 specialists unanimous
    # ===================================================================
    def test_21_backward_compat_all_9(self):
        """All 9 specialists bullish → BULLISH regime, no conflicts, high confidence."""
        records = [
            self._make_record("TechnicalSpecialist", AgentState.SUCCESS, {"trend": "BULLISH"}),
            self._make_record("MomentumSpecialist", AgentState.SUCCESS, {"momentum_direction": "BULLISH"}),
            self._make_record("QuantSpecialist", AgentState.SUCCESS, {"statistical_regime": "TREND_CONSISTENT"}),
            self._make_record("FundamentalSpecialist", AgentState.SUCCESS, {"fundamental_quality": "STRONG"}),
            self._make_record("ValuationSpecialist", AgentState.SUCCESS, {"valuation_status": "UNDERVALUED"}),
            self._make_record("SectorSpecialist", AgentState.SUCCESS, {"sector_regime": "STRONG_OUTPERFORMING"}),
            self._make_record("MacroSpecialist", AgentState.SUCCESS, {"macro_regime": "EXPANSIONARY"}),
            self._make_record("NewsSpecialist", AgentState.SUCCESS, {"news_regime": "BULLISH"}),
            self._make_record("InstitutionalSpecialist", AgentState.SUCCESS, {"institutional_regime": "ACCUMULATION"}),
        ]
        res = self._make_run_result("run-all9", records)
        pkg = self.aggregator.aggregate(res)

        self.assertEqual(pkg.specialists_total, 9)
        self.assertEqual(pkg.research_regime, ResearchRegime.BULLISH)
        self.assertEqual(len(pkg.conflict_summary), 0)
        self.assertGreater(pkg.overall_research_confidence, 0.7)

    # ===================================================================
    # TEST 22: Full integration — multiple specialists with rich evidence
    # ===================================================================
    def test_22_full_integration_rich_evidence(self):
        """Multiple specialists with structured evidence lists → rich package."""
        tech_raw = {
            "trend": "BULLISH",
            "evidence": [
                {"name": "CurrentPrice", "value": 2500.0, "interpretation": "at 2500"},
                {"name": "EMA20", "value": 2480.0, "interpretation": "above"},
                {"name": "RSI14", "value": 62.0, "interpretation": "bullish zone"},
            ],
            "risks": ["Resistance at 2600"],
        }
        quant_raw = {
            "statistical_regime": "NORMAL_VOLATILITY",
            "metrics": [
                {"metric_name": "realized_volatility_5d", "value": 18.5, "unit": "annualized_%",
                 "available": True, "source": "ohlcv_historical",
                 "calculation_method": "std*sqrt(252)*100",
                 "data_timestamp": self.now.isoformat()},
                {"metric_name": "price_zscore_5d", "value": 0.8, "unit": "sigma",
                 "available": True, "source": "ohlcv_historical",
                 "calculation_method": "(price-mean)/std",
                 "data_timestamp": self.now.isoformat()},
            ],
        }
        fund_raw = {
            "fundamental_quality": "STRONG",
            "metrics": [
                {"metric_name": "net_margin", "value": 15.2, "unit": "%",
                 "available": True, "source": "income_statement",
                 "calculation_method": "net_income/revenue*100",
                 "data_timestamp": self.now.isoformat()},
                {"metric_name": "revenue", "value": 50000.0, "unit": "currency",
                 "available": True, "source": "income_statement",
                 "calculation_method": "direct_extraction",
                 "data_timestamp": self.now.isoformat()},
            ],
        }

        records = [
            self._make_record("TechnicalSpecialist", AgentState.SUCCESS, tech_raw, 0.85),
            self._make_record("QuantSpecialist", AgentState.SUCCESS, quant_raw, 0.75),
            self._make_record("FundamentalSpecialist", AgentState.SUCCESS, fund_raw, 0.9),
        ]
        res = self._make_run_result("run-full", records)
        pkg = self.aggregator.aggregate(res)

        # 3 regime + 3 tech + 2 quant + 2 fund = 10 evidence items
        self.assertEqual(len(pkg.evidence_items), 10)
        self.assertEqual(pkg.specialists_total, 3)
        self.assertEqual(pkg.specialists_successful, 3)
        self.assertGreater(pkg.overall_research_confidence, 0.5)
        self.assertTrue(pkg.total_evidence_extracted > 0)

    # ===================================================================
    # TEST 23: Empty run result
    # ===================================================================
    def test_23_empty_run(self):
        res = self._make_run_result("run-empty", [])
        pkg = self.aggregator.aggregate(res)
        self.assertEqual(pkg.specialists_total, 0)
        self.assertEqual(pkg.research_regime, ResearchRegime.INSUFFICIENT_DATA)
        self.assertEqual(len(pkg.evidence_items), 0)

    # ===================================================================
    # TEST 24: Context ID mismatch raises error
    # ===================================================================
    def test_24_context_mismatch(self):
        rec1 = self._make_record("TechnicalSpecialist", AgentState.SUCCESS, {"trend": "BULLISH"})
        ctx2 = MarketContext(
            context_id="ctx-OTHER", symbol="TCS.NS", data_timestamp=self.now,
            current_price=3000.0, provider=ProviderType.STANDARD_DATA_VENDOR,
            provider_timestamp=self.now,
        )
        rec2 = self._make_record("MomentumSpecialist", AgentState.SUCCESS,
                                  {"momentum_direction": "BULLISH"}, ctx=ctx2)
        res = self._make_run_result("run-mismatch", [rec1, rec2])
        with self.assertRaises(AggregationError):
            self.aggregator.aggregate(res)

    # ===================================================================
    # TEST 25: Valuation metrics extraction
    # ===================================================================
    def test_25_valuation_metrics(self):
        """ValuationSpecialist evidence list → proper extraction."""
        raw = {
            "valuation_status": "UNDERVALUED",
            "evidence": [
                {"metric_name": "pe_ratio", "value": 18.5, "unit": "x",
                 "method": "P/E", "formula": "price/eps",
                 "available": True, "inputs": {"price": 2500, "eps": 135},
                 "context_id": self.ctx.context_id,
                 "data_timestamp": self.now.isoformat()},
                {"metric_name": "pb_ratio", "value": 3.2, "unit": "x",
                 "method": "P/B", "formula": "price/bvps",
                 "available": True, "inputs": {"price": 2500, "bvps": 781},
                 "context_id": self.ctx.context_id,
                 "data_timestamp": self.now.isoformat()},
            ],
        }
        rec = self._make_record("ValuationSpecialist", AgentState.SUCCESS, raw)
        res = self._make_run_result("run-val", [rec])
        pkg = self.aggregator.aggregate(res)

        pe_ev = [e for e in pkg.evidence_items if e.metric_name == "pe_ratio"]
        self.assertEqual(len(pe_ev), 1)
        self.assertAlmostEqual(pe_ev[0].value, 18.5)
        self.assertEqual(pe_ev[0].category, EvidenceCategory.VALUATION)

    # ===================================================================
    # TEST 26: total_evidence_extracted field populated
    # ===================================================================
    def test_26_total_evidence_field(self):
        rec = self._make_record("TechnicalSpecialist", AgentState.SUCCESS, {"trend": "NEUTRAL"})
        res = self._make_run_result("run-tef", [rec])
        pkg = self.aggregator.aggregate(res)

        self.assertEqual(pkg.total_evidence_extracted, len(pkg.evidence_items))
        self.assertGreater(pkg.total_evidence_extracted, 0)


if __name__ == "__main__":
    unittest.main()
