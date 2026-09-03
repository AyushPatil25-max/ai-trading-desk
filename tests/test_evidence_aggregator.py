import unittest
from datetime import datetime, timezone
import uuid

from backend.domain.schemas import (
    SpecialistRunResult, AgentExecutionRecord, AgentState, AgentOutput, MarketContext,
    UnifiedEvidencePackage, SignalDirection, ResearchRegime, EvidenceCategory, ConflictSeverity
)
from backend.application.evidence_aggregator import EvidenceAggregator, AggregationError

class TestEvidenceAggregator(unittest.TestCase):
    def setUp(self):
        from backend.domain.schemas import ProviderType
        self.aggregator = EvidenceAggregator()
        self.now = datetime.now(timezone.utc)
        self.ctx = MarketContext(
            context_id="ctx-123",
            symbol="RELIANCE.NS",
            data_timestamp=self.now,
            current_price=2500.0,
            provider=ProviderType.STANDARD_DATA_VENDOR,
            provider_timestamp=self.now
        )

    def _make_record(self, agent_name: str, state: AgentState, raw_data: dict, confidence: float = 1.0, ctx=None):
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
                raw_data=raw_data
            ) if state in [AgentState.SUCCESS, AgentState.DEGRADED] else None,
            error_message="Err" if state == AgentState.FAILED else None
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
            records=records
        )

    def test_1_empty(self):
        res = self._make_run_result("run-1", [])
        pkg = self.aggregator.aggregate(res)
        self.assertEqual(pkg.specialists_total, 0)
        self.assertEqual(pkg.research_regime, ResearchRegime.INSUFFICIENT_DATA)

    def test_2_single_specialist(self):
        rec = self._make_record("TechnicalSpecialist", AgentState.SUCCESS, {"trend_direction": "BULLISH"})
        res = self._make_run_result("run-1", [rec])
        pkg = self.aggregator.aggregate(res)
        self.assertEqual(pkg.specialists_total, 1)
        self.assertEqual(pkg.specialists_successful, 1)
        self.assertEqual(pkg.evidence_items[0].direction, SignalDirection.BULLISH)

    def test_3_context_id_mismatch(self):
        rec1 = self._make_record("TechnicalSpecialist", AgentState.SUCCESS, {"trend_direction": "BULLISH"})
        from backend.domain.schemas import ProviderType
        ctx2 = MarketContext(context_id="ctx-999", symbol="TCS.NS", data_timestamp=self.now, current_price=3000, provider=ProviderType.STANDARD_DATA_VENDOR, provider_timestamp=self.now)
        rec2 = self._make_record("MomentumSpecialist", AgentState.SUCCESS, {"momentum_regime": "BULLISH"}, ctx=ctx2)
        res = self._make_run_result("run-1", [rec1, rec2]) # the run result uses context-123 but rec2 has context-999
        with self.assertRaises(AggregationError):
            self.aggregator.aggregate(res)

    def test_4_failed_timeout_degraded(self):
        rec1 = self._make_record("TechnicalSpecialist", AgentState.FAILED, {})
        rec2 = self._make_record("MomentumSpecialist", AgentState.TIMEOUT, {})
        rec3 = self._make_record("QuantSpecialist", AgentState.DEGRADED, {"quant_regime": "MIXED"})
        res = self._make_run_result("run-1", [rec1, rec2, rec3])
        pkg = self.aggregator.aggregate(res)
        self.assertEqual(pkg.specialists_failed, 1)
        self.assertEqual(pkg.specialists_timed_out, 1)
        self.assertEqual(pkg.specialists_degraded, 1)
        self.assertEqual(len(pkg.evidence_items), 1)
        self.assertEqual(pkg.evidence_items[0].direction, SignalDirection.MIXED)
        self.assertTrue(pkg.overall_research_confidence < 1.0)

    def test_5_numerical_weighting_test(self):
        r1 = self._make_record("TechnicalSpecialist", AgentState.SUCCESS, {"trend_direction": "BULLISH"}, 0.8)
        r2 = self._make_record("MomentumSpecialist", AgentState.SUCCESS, {"momentum_regime": "BULLISH"}, 0.7)
        r3 = self._make_record("FundamentalSpecialist", AgentState.SUCCESS, {"fundamental_regime": "BULLISH"}, 0.9)
        r4 = self._make_record("ValuationSpecialist", AgentState.SUCCESS, {"valuation_regime": "BEARISH"}, 0.8)
        
        res = self._make_run_result("run-num", [r1, r2, r3, r4])
        pkg = self.aggregator.aggregate(res)
        
        self.assertEqual(pkg.research_regime, ResearchRegime.BULLISH)
        self.assertEqual(len(pkg.conflict_summary), 3)
        self.assertAlmostEqual(pkg.overall_research_confidence, 0.58714, places=4)

    def test_6_agreement_and_conflict(self):
        r1 = self._make_record("FundamentalSpecialist", AgentState.SUCCESS, {"fundamental_regime": "BULLISH"})
        r2 = self._make_record("ValuationSpecialist", AgentState.SUCCESS, {"valuation_regime": "BEARISH"})
        r3 = self._make_record("MacroSpecialist", AgentState.SUCCESS, {"macro_regime": "BEARISH"})
        r4 = self._make_record("SectorSpecialist", AgentState.SUCCESS, {"sector_regime": "BULLISH"})

        res = self._make_run_result("run-num", [r1, r2, r3, r4])
        pkg = self.aggregator.aggregate(res)
        
        self.assertEqual(len(pkg.conflict_summary), 4)
        self.assertEqual(len(pkg.agreement_summary), 2)
        self.assertEqual(pkg.research_regime, ResearchRegime.MIXED)

    def test_7_insufficient_data(self):
        r1 = self._make_record("NewsSpecialist", AgentState.SUCCESS, {"news_sentiment": "BULLISH"}, 0.5)
        res = self._make_run_result("run-1", [r1])
        pkg = self.aggregator.aggregate(res)
        self.assertEqual(pkg.research_regime, ResearchRegime.INSUFFICIENT_DATA)

    def test_8_all_9_specialists(self):
        records = [
            self._make_record("TechnicalSpecialist", AgentState.SUCCESS, {"trend_direction": "BULLISH"}),
            self._make_record("MomentumSpecialist", AgentState.SUCCESS, {"momentum_regime": "BULLISH"}),
            self._make_record("QuantSpecialist", AgentState.SUCCESS, {"quant_regime": "BULLISH"}),
            self._make_record("FundamentalSpecialist", AgentState.SUCCESS, {"fundamental_regime": "BULLISH"}),
            self._make_record("ValuationSpecialist", AgentState.SUCCESS, {"valuation_regime": "BULLISH"}),
            self._make_record("SectorSpecialist", AgentState.SUCCESS, {"sector_regime": "BULLISH"}),
            self._make_record("MacroSpecialist", AgentState.SUCCESS, {"macro_regime": "BULLISH"}),
            self._make_record("NewsSpecialist", AgentState.SUCCESS, {"news_sentiment": "BULLISH"}),
            self._make_record("InstitutionalSpecialist", AgentState.SUCCESS, {"institutional_regime": "BULLISH"}),
        ]
        res = self._make_run_result("run-all", records)
        pkg = self.aggregator.aggregate(res)
        self.assertEqual(pkg.specialists_total, 9)
        self.assertEqual(pkg.research_regime, ResearchRegime.BULLISH)
        self.assertEqual(len(pkg.conflict_summary), 0)
        self.assertEqual(pkg.overall_research_confidence, 1.0)
        self.assertEqual(len(pkg.agreement_summary), 1)

if __name__ == '__main__':
    unittest.main()
