import logging
from typing import List, Dict, Optional
import asyncio

from backend.domain.stock_schemas import (
    StockFundamentalData,
    StockTechnicalData,
    StockAnalysisResult,
    ScreenerCriteria,
    StockScreenerResult
)
from backend.infrastructure.security_master import get_security_master
from backend.infrastructure.providers.market_data_provider import get_market_data_provider
from backend.application.stock_analysis_engine import StockAnalysisEngine

logger = logging.getLogger(__name__)

class StockScreener:
    def __init__(self):
        self.sm = get_security_master()
        self.provider = get_market_data_provider()
        self.engine = StockAnalysisEngine()

    async def screen_undervalued_strong_fundamentals(self, limit: int = 50) -> List[StockScreenerResult]:
        """
        Screens the entire universe (or a subset) for strong fundamentals + undervalued characteristics.
        """
        # Get active securities
        securities = self.sm.list_securities(active_only=True)
        # Limit processing for the purpose of the immediate return to avoid massive wait times
        # In a real batch pipeline, this would run overnight and cache results.
        securities_to_process = securities[:50] # Take first 50 to avoid massive wait times on-the-fly
        
        results = []
        
        # We process in batches of 50
        batch_size = 50
        for i in range(0, len(securities_to_process), batch_size):
            batch = securities_to_process[i:i+batch_size]
            tasks = []
            for sec in batch:
                tasks.append(self._evaluate_stock(sec.canonical_symbol))
                
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in batch_results:
                if isinstance(res, StockScreenerResult):
                    results.append(res)
                    if len(results) >= limit:
                        return results
                        
        # Sort by best fundamental and valuation reasons length roughly or custom score
        return results

    async def _evaluate_stock(self, symbol: str) -> Optional[StockScreenerResult]:
        try:
            fundamental = await self.provider.get_fundamentals(symbol)
            technical = await self.provider.get_technicals(symbol)
            
            if not fundamental or not technical or not technical.current_price:
                return None
                
            analysis = await self.engine.analyze_stock(symbol, fundamental, technical)
            
            # Screening criteria for "Strong Fundamental + Undervalued"
            if analysis.fundamental_score > 50 and analysis.valuation_score > 50 and analysis.risk_score < 50:
                sec = self.sm.resolve_symbol(symbol)
                comp_name = sec.company_name if sec else symbol
                return StockScreenerResult(
                    symbol=symbol,
                    company_name=comp_name,
                    overall_score=analysis.overall_score,
                    decision=analysis.decision.value if hasattr(analysis.decision, 'value') else str(analysis.decision),
                    price=technical.current_price,
                    pe_ratio=fundamental.pe or fundamental.pe_ratio,
                    roe=fundamental.roe,
                    confidence=analysis.confidence,
                    thesis=", ".join(analysis.positive_factors[:3]) or "Strong fundamentals with acceptable risk profile.",
                    fundamental_reasons=[p for p in analysis.positive_factors if "growth" in p.lower() or "roe" in p.lower() or "debt" in p.lower()],
                    valuation_reasons=[p for p in analysis.positive_factors if "p/e" in p.lower() or "p/b" in p.lower() or "attractive" in p.lower()],
                    trend_reasons=[p for p in analysis.positive_factors if "sma" in p.lower() or "macd" in p.lower()],
                    risk_reasons=analysis.risk_warnings,
                    data_source="Upstox"
                )
            return None
        except Exception as e:
            logger.error(f"Error screening {symbol}: {e}")
            return None
