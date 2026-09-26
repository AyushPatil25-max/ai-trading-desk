import asyncio
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import uuid

from backend.domain.earnings_schemas import (
    EarningsEvent, EarningsResult, EarningsMetric, EarningsEventStatus,
    EarningsResponse, GuidanceRecord
)
from backend.domain.earnings_schemas import EarningsProvenance
from backend.infrastructure.security_master import get_security_master
from backend.infrastructure.providers.yfinance_provider import YFinanceProvider

logger = logging.getLogger(__name__)

class EarningsEngine:
    def __init__(self):
        self.provider = YFinanceProvider()
        self.sm = get_security_master()

    def _safe_float(self, val) -> Optional[float]:
        if val is None:
            return None
        try:
            f = float(val)
            import math
            if math.isnan(f) or math.isinf(f):
                return None
            return f
        except (ValueError, TypeError):
            return None

    def _calc_pct_change(self, current: Optional[float], prior: Optional[float]) -> Optional[float]:
        if current is None or prior is None:
            return None
        if prior == 0:
            return None
        # Handle sign changes properly (if prior < 0 and current > 0, etc.)
        # Typical growth % formula for negative prior is tricky, usually we do absolute prior
        return round(((current - prior) / abs(prior)) * 100.0, 2)

    async def get_earnings_calendar(self, symbol: str) -> EarningsResponse:
        try:
            res = await self.provider.get_earnings_calendar(symbol)
            if res.status == "ERROR":
                return EarningsResponse(
                    symbol=symbol,
                    status=EarningsEventStatus.PROVIDER_ERROR,
                    error_message=res.error
                )
            
            events_data = res.data.get("events", []) if res.data else []
            prov = res.provenance[0] if res.provenance else None
            
            events = []
            for e in events_data:
                events.append(EarningsEvent(
                    event_id=str(uuid.uuid4()),
                    symbol=symbol,
                    expected_report_date=e.get("earnings_date"),
                    status=EarningsEventStatus.ESTIMATED,  # yfinance dates are often estimates until confirmed
                    source=self.provider.name,
                    provenance=EarningsProvenance(provenance_id=prov.provenance_id, source_name=prov.source_name, source_type=prov.source_type, fetched_at=prov.fetched_at) if prov else None
                ))
                
            return EarningsResponse(
                symbol=symbol,
                events=events,
                status=EarningsEventStatus.AVAILABLE if events else EarningsEventStatus.UNAVAILABLE
            )
        except Exception as e:
            logger.error(f"Error fetching earnings calendar for {symbol}: {e}")
            return EarningsResponse(
                symbol=symbol,
                status=EarningsEventStatus.PROVIDER_ERROR,
                error_message=str(e)
            )

    async def get_earnings_results(self, symbol: str) -> EarningsResponse:
        try:
            res = await self.provider.get_quarterly_fundamentals(symbol)
            if res.status == "ERROR":
                return EarningsResponse(
                    symbol=symbol,
                    status=EarningsEventStatus.PROVIDER_ERROR,
                    error_message=res.error
                )
                
            stmts = res.data.get("statements", []) if res.data else []
            if not stmts:
                return EarningsResponse(symbol=symbol, status=EarningsEventStatus.UNAVAILABLE)
                
            # Fetch calendar to merge expectations and surprises
            cal_res = await self.provider.get_earnings_calendar(symbol)
            cal_events = cal_res.data.get("events", []) if (cal_res.status != "ERROR" and cal_res.data) else []
            
            results = []
            for i, stmt in enumerate(stmts):
                rev = self._safe_float(getattr(stmt, "revenue", None))
                op = self._safe_float(getattr(stmt, "operating_profit", None))
                ebitda = self._safe_float(getattr(stmt, "ebitda", None))
                ni = self._safe_float(getattr(stmt, "net_income", None))
                eps = self._safe_float(getattr(stmt, "eps", None))
                
                # Try to find QoQ / YoY from historical
                prior_q = stmts[i+1] if i+1 < len(stmts) else None
                prior_y = stmts[i+4] if i+4 < len(stmts) else None
                
                def make_metric(val):
                    if val is None:
                        return None
                    return EarningsMetric(actual=val)
                    
                rev_m = make_metric(rev)
                if rev_m and prior_q:
                    rev_m.qoq_change_pct = self._calc_pct_change(rev, self._safe_float(getattr(prior_q, "revenue", None)))
                if rev_m and prior_y:
                    rev_m.yoy_change_pct = self._calc_pct_change(rev, self._safe_float(getattr(prior_y, "revenue", None)))

                op_m = make_metric(op)
                if op_m and prior_q:
                    op_m.qoq_change_pct = self._calc_pct_change(op, self._safe_float(getattr(prior_q, "operating_profit", None)))
                if op_m and prior_y:
                    op_m.yoy_change_pct = self._calc_pct_change(op, self._safe_float(getattr(prior_y, "operating_profit", None)))

                ebitda_m = make_metric(ebitda)
                if ebitda_m and prior_q:
                    ebitda_m.qoq_change_pct = self._calc_pct_change(ebitda, self._safe_float(getattr(prior_q, "ebitda", None)))
                if ebitda_m and prior_y:
                    ebitda_m.yoy_change_pct = self._calc_pct_change(ebitda, self._safe_float(getattr(prior_y, "ebitda", None)))

                ni_m = make_metric(ni)
                if ni_m and prior_q:
                    ni_m.qoq_change_pct = self._calc_pct_change(ni, self._safe_float(getattr(prior_q, "net_income", None)))
                if ni_m and prior_y:
                    ni_m.yoy_change_pct = self._calc_pct_change(ni, self._safe_float(getattr(prior_y, "net_income", None)))

                eps_m = make_metric(eps)
                if eps_m and prior_q:
                    eps_m.qoq_change_pct = self._calc_pct_change(eps, self._safe_float(getattr(prior_q, "eps", None)))
                if eps_m and prior_y:
                    eps_m.yoy_change_pct = self._calc_pct_change(eps, self._safe_float(getattr(prior_y, "eps", None)))
                    
                # Merge expectations if calendar matches (approximate by sorting and matching next available)
                # For a robust match, we might match by nearest date.
                if eps_m and cal_events:
                    # simplistic date matching or just leave None if we can't be perfectly sure.
                    # yfinance earnings_dates is just date and eps.
                    # We'll just look for an event in calendar_events that has reported_eps == eps_m.actual
                    # or nearest date.
                    stmt_dt = stmt.period_end_date
                    # Let's find the closest event within 45 days after period_end_date
                    matched_event = None
                    for ce in cal_events:
                        try:
                            ce_dt = datetime.fromisoformat(ce["earnings_date"])
                            delta = ce_dt - stmt_dt
                            if 0 <= delta.days <= 60: # typical reporting lag
                                matched_event = ce
                                break
                        except:
                            pass
                    
                    if matched_event:
                        est = matched_event.get("eps_estimate")
                        if est is not None:
                            eps_m.expected = est
                            eps_m.surprise_pct = matched_event.get("surprise_pct")

                op_margin = None
                if op is not None and rev is not None and rev > 0:
                    op_margin = round((op / rev) * 100.0, 2)
                    
                net_margin = None
                if ni is not None and rev is not None and rev > 0:
                    net_margin = round((ni / rev) * 100.0, 2)
                    
                prov = EarningsProvenance(
                    provenance_id=str(uuid.uuid4()),
                    source_name=stmt.source,
                    source_type="API",
                    fetched_at=stmt.retrieved_at.isoformat()
                )

                results.append(EarningsResult(
                    symbol=symbol,
                    reporting_period=stmt.period_end_date.isoformat(),
                    revenue=rev_m,
                    operating_profit=op_m,
                    ebitda=ebitda_m,
                    net_income=ni_m,
                    eps=eps_m,
                    operating_margin=op_margin,
                    net_margin=net_margin,
                    data_quality=EarningsEventStatus.AVAILABLE,
                    provenance=EarningsProvenance(provenance_id=prov.provenance_id, source_name=prov.source_name, source_type=prov.source_type, fetched_at=prov.fetched_at) if prov else None
                ))
                
            latest = results[0] if results else None
            hist = results[1:] if len(results) > 1 else []
            
            return EarningsResponse(
                symbol=symbol,
                latest_result=latest,
                historical_results=hist,
                status=EarningsEventStatus.AVAILABLE if latest else EarningsEventStatus.UNAVAILABLE
            )
        except Exception as e:
            logger.error(f"Error fetching earnings results for {symbol}: {e}")
            return EarningsResponse(
                symbol=symbol,
                status=EarningsEventStatus.PROVIDER_ERROR,
                error_message=str(e)
            )

_engine_instance = EarningsEngine()
def get_earnings_engine() -> EarningsEngine:
    return _engine_instance
