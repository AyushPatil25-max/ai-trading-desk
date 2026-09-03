import logging
from typing import List, Optional
from datetime import datetime

from backend.domain.ipo_schemas import (
    IPOMaster, IPOAnalysis, IPOScoreVerdict, IPOStatus
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
        
        # Segment scores
        f_score = 0.0
        v_score = 0.0
        s_score = 0.0
        g_score = 0.0
        r_score = 0.0
        
        # Analyze fundamental missing data
        if not ipo.issue_price or not ipo.lot_size:
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
                analyzed_at=datetime.now()
            )

        # Fundamental
        if ipo.revenue is not None and ipo.revenue > 100:
            f_score += 30; strengths.append("Solid revenue base")
        if ipo.pat is not None and ipo.pat > 0:
            f_score += 30; strengths.append("Profitable")
        elif ipo.pat is not None and ipo.pat < 0:
            f_score -= 20; weaknesses.append("Loss making")
        if ipo.debt_equity is not None and ipo.debt_equity > 2:
            f_score -= 20; r_score += 40; red_flags.append("High debt-to-equity")
            
        # Valuation
        if ipo.pe is not None:
            if ipo.pe < 25: v_score += 40; strengths.append("Reasonable P/E")
            elif ipo.pe > 60: v_score -= 30; weaknesses.append("Expensive valuation")
            
        # GMP Analysis (separated as requested)
        if ipo.gmp and ipo.estimated_listing_gain_pct:
            if ipo.estimated_listing_gain_pct > 20:
                g_score += 40; strengths.append("Strong grey market demand")
            elif ipo.estimated_listing_gain_pct > 10:
                g_score += 20
            elif ipo.estimated_listing_gain_pct < 0:
                g_score -= 30
                warnings.append("Negative GMP")
                
        # Subscription Analysis
        if ipo.total_subscription and ipo.total_subscription > 50:
            s_score += 40; strengths.append("Massive total subscription")
        elif ipo.qib_subscription and ipo.qib_subscription > 10:
            s_score += 20
                
        overall = (f_score * 0.4) + (v_score * 0.3) + (s_score * 0.2) + (g_score * 0.1)
        
        verdict = IPOScoreVerdict.NEUTRAL
        if overall > 60 and r_score < 30:
            verdict = IPOScoreVerdict.STRONG
        elif overall > 30:
            verdict = IPOScoreVerdict.POSITIVE
        elif overall < -20:
            verdict = IPOScoreVerdict.AVOID
        elif overall < 0:
            verdict = IPOScoreVerdict.WEAK

        return IPOAnalysis(
            ipo_id=ipo_id,
            overall_score=overall,
            fundamental_score=f_score,
            valuation_score=v_score,
            subscription_score=s_score,
            gmp_score=g_score,
            risk_score=r_score,
            confidence=0.8,
            verdict=verdict,
            strengths=strengths,
            weaknesses=weaknesses,
            red_flags=red_flags,
            warnings=warnings,
            analyzed_at=datetime.now()
        )

# Maintain backwards compatibility for test suite
class DeterministicFixtureIPOProvider:
    def __init__(self):
        from backend.infrastructure.ipo.ipo_repository import IPORepository
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
