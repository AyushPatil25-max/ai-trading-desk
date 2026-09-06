import logging
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional
from backend.domain.opportunity_scanner_schemas import (
    OpportunityScannerResult, ScannerBatchResult, OpportunityType, OpportunityDirection,
    TrendClassification, BreakoutStatus, VolumeStatus, GapStatus
)
from backend.application.opportunity_scanner_engine import OpportunityScannerEngine
from backend.infrastructure.security_master import get_security_master

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/scanner", tags=["scanner"])

def get_scanner_engine():
    return OpportunityScannerEngine()

async def fetch_and_filter_opportunities(
    engine: OpportunityScannerEngine,
    limit: int = 50,
    min_score: float = 0.0,
    min_confidence: float = 0.0,
    opportunity_type: Optional[OpportunityType] = None,
    direction: Optional[OpportunityDirection] = None,
    trend: Optional[TrendClassification] = None,
    breakout: Optional[BreakoutStatus] = None,
    volume_spike: Optional[VolumeStatus] = None,
    gap: Optional[GapStatus] = None,
    liquidity: Optional[str] = None,
    sort_by: str = "opportunity_score"
):
    try:
        sec_master = get_security_master()
        all_symbols = [s.symbol for s in sec_master.get_all_securities()]
        
        if len(all_symbols) > 100:
            all_symbols = all_symbols[:100]
            
        result = await engine.scan_symbols(all_symbols)
        
        filtered_ops = []
        for op in result.opportunities:
            if op.opportunity.opportunity_score >= min_score and op.opportunity.confidence >= min_confidence:
                if opportunity_type and op.opportunity.opportunity_type != opportunity_type: continue
                if direction and op.opportunity.direction != direction: continue
                if trend and op.technical.trend != trend: continue
                if breakout and op.signals.breakout_signal != breakout: continue
                if volume_spike and op.signals.volume_spike_signal != volume_spike: continue
                if gap and op.signals.gap_signal != gap: continue
                if liquidity and op.market.liquidity_classification != liquidity: continue
                
                filtered_ops.append(op)
                    
        def sort_key(op: OpportunityScannerResult):
            if sort_by == "confidence": return op.opportunity.confidence
            elif sort_by == "volume_ratio": return op.market.volume_ratio or -1.0
            elif sort_by == "fundamental_score": return op.fundamental.fundamental_score or -1.0
            elif sort_by == "valuation_score": return op.fundamental.valuation_score or -1.0
            elif sort_by == "risk_reward": return op.risk.risk_reward or -1.0
            elif sort_by == "price_change": return op.market.ltp or 0.0
            return op.opportunity.opportunity_score
            
        filtered_ops.sort(key=sort_key, reverse=True)
        filtered_ops = filtered_ops[:limit]
        
        result.opportunities = filtered_ops
        result.total_opportunities = len(filtered_ops)
        return result
    except Exception as e:
        logger.error(f"Error getting scanner opportunities: {e}")
        raise HTTPException(status_code=500, detail="Internal scanning error")


@router.get("/opportunities", response_model=ScannerBatchResult)
async def get_scanner_opportunities_endpoint(
    engine: OpportunityScannerEngine = Depends(get_scanner_engine),
    limit: int = Query(50, description="Max opportunities to return"),
    min_score: float = Query(0.0, description="Minimum opportunity score"),
    min_confidence: float = Query(0.0, description="Minimum confidence"),
    opportunity_type: Optional[OpportunityType] = None,
    direction: Optional[OpportunityDirection] = None,
    trend: Optional[TrendClassification] = None,
    breakout: Optional[BreakoutStatus] = None,
    volume_spike: Optional[VolumeStatus] = None,
    gap: Optional[GapStatus] = None,
    liquidity: Optional[str] = Query(None, description="HIGH, MODERATE, LOW"),
    sector: Optional[str] = Query(None, description="Currently unavailable natively, handled locally"),
    sort_by: str = Query("opportunity_score", description="Sort field: score, confidence, volume_ratio, fundamental_score, valuation_score, risk_reward, price_change")
):
    return await fetch_and_filter_opportunities(
        engine=engine, limit=limit, min_score=min_score, min_confidence=min_confidence,
        opportunity_type=opportunity_type, direction=direction, trend=trend,
        breakout=breakout, volume_spike=volume_spike, gap=gap, liquidity=liquidity, sort_by=sort_by
    )

@router.get("/symbol/{symbol}", response_model=OpportunityScannerResult)
async def get_scanner_by_symbol(
    symbol: str,
    engine: OpportunityScannerEngine = Depends(get_scanner_engine)
):
    result = await engine.scan_single(symbol)
    if not result:
        raise HTTPException(status_code=404, detail="Symbol not found or insufficient data")
    return result

@router.get("/top", response_model=ScannerBatchResult)
async def get_top_opportunities(
    engine: OpportunityScannerEngine = Depends(get_scanner_engine),
    limit: int = 10
):
    return await fetch_and_filter_opportunities(engine, limit=limit, min_score=50.0, min_confidence=0.5)

@router.get("/momentum", response_model=ScannerBatchResult)
async def get_momentum_opportunities(engine: OpportunityScannerEngine = Depends(get_scanner_engine)):
    return await fetch_and_filter_opportunities(engine, opportunity_type=OpportunityType.MOMENTUM)

@router.get("/breakouts", response_model=ScannerBatchResult)
async def get_breakout_opportunities(engine: OpportunityScannerEngine = Depends(get_scanner_engine)):
    return await fetch_and_filter_opportunities(engine, opportunity_type=OpportunityType.BREAKOUT)

@router.get("/reversals", response_model=ScannerBatchResult)
async def get_reversal_opportunities(engine: OpportunityScannerEngine = Depends(get_scanner_engine)):
    return await fetch_and_filter_opportunities(engine, opportunity_type=OpportunityType.REVERSAL)

@router.get("/volume-spikes", response_model=ScannerBatchResult)
async def get_volume_opportunities(engine: OpportunityScannerEngine = Depends(get_scanner_engine)):
    return await fetch_and_filter_opportunities(engine, opportunity_type=OpportunityType.VOLUME_SPIKE)

@router.get("/gaps", response_model=ScannerBatchResult)
async def get_gap_opportunities(engine: OpportunityScannerEngine = Depends(get_scanner_engine)):
    up = await fetch_and_filter_opportunities(engine, opportunity_type=OpportunityType.GAP_UP)
    down = await fetch_and_filter_opportunities(engine, opportunity_type=OpportunityType.GAP_DOWN)
    up.opportunities.extend(down.opportunities)
    up.opportunities.sort(key=lambda x: x.opportunity.opportunity_score, reverse=True)
    up.total_opportunities = len(up.opportunities)
    return up
