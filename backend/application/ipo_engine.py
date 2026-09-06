import logging
from typing import List, Optional
from datetime import datetime

from backend.domain.ipo_schemas import (
    IPOMaster, IPOAnalysis, IPOScoreVerdict, IPOStatus, DataQuality, ValuationVerdict
)
from backend.infrastructure.ipo.ipo_repository import get_ipo_repository
from backend.infrastructure.ipo.ipo_data_provider import ingest_all_ipos

logger = logging.getLogger(__name__)

class IPOEngine:
    def __init__(self, ipo_provider=None, gmp_provider=None, sub_provider=None):
        self.repo = get_ipo_repository()

    async def trigger_refresh(self) -> None:
        try:
            records = ingest_all_ipos()
            for r in records:
                self.repo.upsert_ipo(r)
            logger.info(f"Refreshed {len(records)} IPO records")
        except Exception as e:
            logger.error(f"Error refreshing IPOs: {e}")

    async def get_ipo_list(self, status_filter: Optional[str] = None) -> List[IPOMaster]:
        if status_filter:
            status_enum = getattr(IPOStatus, status_filter.upper(), None)
            if status_enum == IPOStatus.UPCOMING:
                return self.repo.get_upcoming()
            elif status_enum == IPOStatus.OPEN:
                return self.repo.get_open()
            elif status_enum == IPOStatus.LISTED:
                return self.repo.get_listed()
            elif status_enum == IPOStatus.CLOSED:
                return [ipo for ipo in self.repo.get_all() if ipo.status == IPOStatus.CLOSED]
            return []
        return self.repo.get_all()

    async def get_ipo_details(self, ipo_id: str) -> Optional[IPOMaster]:
        return self.repo.get_ipo(ipo_id)

    async def get_gmp_trend(self, ipo_id: str):
        ipo = self.repo.get_ipo(ipo_id)
        if ipo:
            from backend.domain.ipo_schemas import GMPObservation
            return [GMPObservation(**obs) for obs in ipo.gmp_history]
        return []

    async def get_subscription(self, ipo_id: str):
        ipo = self.repo.get_ipo(ipo_id)
        if ipo:
            from backend.domain.ipo_schemas import IPOSubscriptionObservation
            return [IPOSubscriptionObservation(**obs) for obs in ipo.subscription_history]
        return []

    async def analyze_ipo(self, ipo_id: str) -> IPOAnalysis:
        ipo = self.repo.get_ipo(ipo_id)
        if not ipo:
            raise ValueError(f"IPO {ipo_id} not found")

        warnings = []
        strengths = []
        weaknesses = []
        red_flags = []
        dq_reasons = []
        
        # Segment scores
        f_score = 50.0
        v_score = 50.0
        s_score = 0.0
        g_score = 50.0
        r_score = 0.0
        confidence = 1.0
        
        # Analyze missing data
        if not ipo.issue_price or not ipo.lot_size:
            dq_reasons.append("Missing issue price or lot size")
            return IPOAnalysis(
                ipo_id=ipo_id,
                overall_score=0.0,
                fundamental_score=0.0,
                valuation_score=0.0,
                subscription_score=0.0,
                gmp_score=0.0,
                risk_score=0.0,
                confidence=0.0,
                verdict=IPOScoreVerdict.INSUFFICIENT_DATA,
                warnings=["Missing issue price or lot size"],
                analyzed_at=datetime.now(),
                data_quality_status=DataQuality.ERROR,
                data_quality_reasons=dq_reasons
            )
            
        if not ipo.revenue and not ipo.pat:
            confidence -= 0.4
            dq_reasons.append("Missing financials")
        
        if not ipo.pe:
            confidence -= 0.2
            dq_reasons.append("Missing PE")
            
        if not ipo.gmp:
            confidence -= 0.1
            dq_reasons.append("Missing GMP")
            
        if not ipo.total_subscription:
            dq_reasons.append("Missing subscription")
            
        if not ipo.promoters:
            dq_reasons.append("Missing promoter data")
            
        # Data Quality Status
        if len(dq_reasons) == 0: dq_status = DataQuality.COMPLETE
        elif len(dq_reasons) <= 2: dq_status = DataQuality.PARTIAL
        elif len(dq_reasons) <= 4: dq_status = DataQuality.INSUFFICIENT
        else: dq_status = DataQuality.ERROR

        # Fundamental
        if ipo.revenue is not None and ipo.revenue > 100:
            f_score += 15; strengths.append("Solid revenue base")
        if ipo.pat is not None and ipo.pat > 0:
            f_score += 15; strengths.append("Profitable")
        elif ipo.pat is not None and ipo.pat < 0:
            f_score -= 30; weaknesses.append("Loss making")
            
        if getattr(ipo, 'pat_margin', None):
            if ipo.pat_margin > 15:
                f_score += 10; strengths.append("High margins")
        if getattr(ipo, 'roe', None):
            if ipo.roe > 15:
                f_score += 10; strengths.append("High ROE")
            elif ipo.roe < 5:
                f_score -= 10
                
        if ipo.debt_equity is not None and ipo.debt_equity > 2:
            f_score -= 20; r_score += 40; red_flags.append("High debt-to-equity")
            
        # Valuation
        val_verdict = ValuationVerdict.INSUFFICIENT_DATA
        if ipo.pe is not None:
            peer_pe = getattr(ipo, 'peer_pe_median', getattr(ipo, 'sector_pe', None))
            if peer_pe is not None:
                # Compare to peer
                if ipo.pe < peer_pe * 0.8:
                    v_score += 30; strengths.append("Valuation discount to peers")
                    val_verdict = ValuationVerdict.UNDERVALUED
                elif ipo.pe > peer_pe * 1.2:
                    v_score -= 30; weaknesses.append("Expensive relative to peers")
                    val_verdict = ValuationVerdict.OVERVALUED
                else:
                    val_verdict = ValuationVerdict.FAIRLY_VALUED
            else:
                # Absolute thresholds only if peer data is missing, but with lower confidence
                confidence -= 0.1
                dq_reasons.append("Missing peer valuation context")
                if ipo.pe < 25: 
                    v_score += 20; strengths.append("Reasonable absolute P/E")
                    val_verdict = ValuationVerdict.UNDERVALUED
                elif ipo.pe > 60: 
                    v_score -= 20; weaknesses.append("Expensive absolute valuation")
                    val_verdict = ValuationVerdict.OVERVALUED
                else:
                    val_verdict = ValuationVerdict.FAIRLY_VALUED
        else:
            confidence -= 0.2
            dq_reasons.append("Missing P/E")
            
        # GMP Analysis
        gmp_pct = ipo.latest_gmp.gmp_percentage
        if ipo.gmp and gmp_pct is not None:
            if gmp_pct > 20:
                g_score += 40; strengths.append("Strong grey market demand")
            elif gmp_pct > 10:
                g_score += 20
            elif gmp_pct < 0:
                g_score -= 40
                warnings.append("Negative GMP")
                
        # Subscription Analysis
        if ipo.total_subscription and ipo.total_subscription > 50:
            s_score += 80; strengths.append("Massive total subscription")
        elif ipo.total_subscription and ipo.total_subscription > 10:
            s_score += 40
        elif ipo.total_subscription and ipo.total_subscription < 1:
            warnings.append("Under-subscribed")
            
        f_score = max(0.0, min(100.0, f_score))
        v_score = max(0.0, min(100.0, v_score))
        s_score = max(0.0, min(100.0, s_score))
        g_score = max(0.0, min(100.0, g_score))
                
        overall = (f_score * 0.3) + (v_score * 0.2) + (s_score * 0.3) + (g_score * 0.2) - (r_score * 0.5)
        overall = max(0.0, min(100.0, overall))
        
        confidence = max(0.0, min(1.0, confidence))
        
        verdict = IPOScoreVerdict.NEUTRAL
        if confidence < 0.3:
            verdict = IPOScoreVerdict.INSUFFICIENT_DATA
        elif overall > 75 and r_score < 30:
            verdict = IPOScoreVerdict.STRONG_POSITIVE
        elif overall > 55:
            verdict = IPOScoreVerdict.POSITIVE
        elif overall < 20:
            verdict = IPOScoreVerdict.AVOID
        elif overall < 40:
            verdict = IPOScoreVerdict.NEGATIVE

        # Set scores back to the IPO master object for filtering
        ipo.fundamental_score = f_score
        ipo.valuation_score = v_score
        ipo.subscription_score = s_score
        ipo.gmp_score = g_score
        ipo.risk_score = r_score
        ipo.ai_score = overall
        ipo.ai_confidence = confidence
        ipo.ai_verdict = verdict.value
        ipo.data_quality_status = dq_status
        ipo.data_quality_reasons = dq_reasons
        self.repo.save_ipo(ipo)

        return IPOAnalysis(
            ipo_id=ipo_id,
            overall_score=round(overall, 1),
            fundamental_score=round(f_score, 1),
            valuation_score=round(v_score, 1),
            subscription_score=round(s_score, 1),
            gmp_score=round(g_score, 1),
            risk_score=round(r_score, 1),
            confidence=round(confidence, 2),
            verdict=verdict,
            strengths=strengths,
            weaknesses=weaknesses,
            red_flags=red_flags,
            warnings=warnings,
            analyzed_at=datetime.now(),
            data_quality_status=dq_status,
            data_quality_reasons=dq_reasons
        )

# Maintain backwards compatibility for test suite
class DeterministicFixtureIPOProvider:
    def __init__(self):
        from backend.infrastructure.ipo.ipo_repository import get_ipo_repository
        self.repo = get_ipo_repository()
    def add_ipo(self, ipo):
        self.repo.save_ipo(ipo)
    def add_gmp(self, ipo_id, gmp_obs):
        ipo = self.repo.get_ipo(ipo_id)
        if ipo:
            ipo.gmp = gmp_obs.gmp_value
            ipo.gmp_source = gmp_obs.source
            ipo.gmp_timestamp = gmp_obs.observed_at
            if ipo.issue_price:
                ipo.estimated_listing_price = ipo.issue_price + ipo.gmp
                ipo.estimated_listing_gain_pct = (ipo.gmp / ipo.issue_price) * 100
            ipo.gmp_history.append(gmp_obs.model_dump())
            self.repo.save_ipo(ipo)
    def add_subscription(self, ipo_id, sub_obs):
        ipo = self.repo.get_ipo(ipo_id)
        if ipo:
            ipo.total_subscription = sub_obs.total
            ipo.subscription_timestamp = sub_obs.observed_at
            ipo.subscription_history.append(sub_obs.model_dump())
            self.repo.save_ipo(ipo)
