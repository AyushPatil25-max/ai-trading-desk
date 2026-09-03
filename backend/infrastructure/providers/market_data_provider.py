import logging
from typing import List, Dict, Optional
import asyncio
from datetime import datetime
import yfinance as yf

from backend.domain.stock_schemas import StockFundamentalData, StockTechnicalData
from backend.infrastructure.security_master import get_security_master

logger = logging.getLogger(__name__)

class IMarketDataProvider:
    async def get_fundamentals(self, symbol: str) -> Optional[StockFundamentalData]:
        pass
    
    async def get_technicals(self, symbol: str) -> Optional[StockTechnicalData]:
        pass

class PublicMarketDataProvider(IMarketDataProvider):
    """
    Uses yfinance to fetch real market data.
    """
    def __init__(self):
        self.sm = get_security_master()

    def _get_yf_ticker(self, symbol: str) -> str:
        # yfinance expects .NS for NSE or .BO for BSE
        sec = self.sm.resolve_symbol(symbol)
        if sec:
            if sec.exchange == "NSE":
                return f"{sec.canonical_symbol}.NS"
            elif sec.exchange == "BSE":
                return f"{sec.canonical_symbol}.BO"
        return f"{symbol}.NS"  # Default to NSE

    async def get_fundamentals(self, symbol: str) -> Optional[StockFundamentalData]:
        try:
            ticker = self._get_yf_ticker(symbol)
            # Run in executor to not block async loop
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, lambda: yf.Ticker(ticker).info)
            
            if not info or 'regularMarketPrice' not in info and 'currentPrice' not in info:
                # Some symbols might be delisted or invalid
                return None
                
            return StockFundamentalData(
                symbol=symbol,
                company_name=info.get('longName', symbol),
                sector=info.get('sector', 'Unknown'),
                industry=info.get('industry', 'Unknown'),
                market_cap=info.get('marketCap', 0.0),
                revenue=info.get('totalRevenue', 0.0),
                revenue_growth=info.get('revenueGrowth', 0.0) * 100 if info.get('revenueGrowth') else 0.0,
                ebitda=info.get('ebitda', 0.0),
                ebitda_margin=info.get('ebitdaMargins', 0.0) * 100 if info.get('ebitdaMargins') else 0.0,
                pat=info.get('netIncomeToCommon', 0.0),
                pat_growth=info.get('earningsGrowth', 0.0) * 100 if info.get('earningsGrowth') else 0.0,
                roe=info.get('returnOnEquity', 0.0) * 100 if info.get('returnOnEquity') else 0.0,
                roce=info.get('returnOnAssets', 0.0) * 100 if info.get('returnOnAssets') else 0.0, # approximation
                debt_equity=info.get('debtToEquity', 0.0),
                pe=info.get('trailingPE', 0.0),
                pb=info.get('priceToBook', 0.0),
                promoter_holding=info.get('heldPercentInsiders', 0.0) * 100 if info.get('heldPercentInsiders') else 0.0,
                promoter_pledge=0.0,
                dividend_yield=info.get('dividendYield', 0.0) * 100 if info.get('dividendYield') else 0.0,
                last_updated=datetime.now()
            )
        except Exception as e:
            logger.error(f"Failed to fetch fundamentals for {symbol}: {e}")
            return None

    async def get_technicals(self, symbol: str) -> Optional[StockTechnicalData]:
        try:
            ticker = self._get_yf_ticker(symbol)
            loop = asyncio.get_event_loop()
            
            # Fetch history for moving averages
            hist = await loop.run_in_executor(None, lambda: yf.Ticker(ticker).history(period="1y"))
            info = await loop.run_in_executor(None, lambda: yf.Ticker(ticker).info)
            
            if hist.empty:
                return None
                
            current_price = hist['Close'].iloc[-1]
            prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else current_price
            daily_return = (current_price - prev_close) / prev_close
            
            sma_20 = hist['Close'].rolling(window=20).mean().iloc[-1] if len(hist) >= 20 else current_price
            sma_50 = hist['Close'].rolling(window=50).mean().iloc[-1] if len(hist) >= 50 else current_price
            sma_200 = hist['Close'].rolling(window=200).mean().iloc[-1] if len(hist) >= 200 else current_price
            
            # Trend calculation
            trend = "BULLISH" if current_price > sma_50 and sma_50 > sma_200 else "BEARISH"
            if current_price > sma_50 and sma_50 <= sma_200:
                trend = "NEUTRAL_BULLISH"
            elif current_price <= sma_50 and sma_50 > sma_200:
                trend = "NEUTRAL_BEARISH"

            return StockTechnicalData(
                symbol=symbol,
                current_price=current_price,
                daily_return=daily_return,
                high_52w=info.get('fiftyTwoWeekHigh', hist['High'].max()),
                low_52w=info.get('fiftyTwoWeekLow', hist['Low'].min()),
                sma_20=sma_20,
                sma_50=sma_50,
                sma_200=sma_200,
                ema_20=sma_20, # Rough approx
                rsi_14=50.0, # Requires more complex calculation, default neutral
                macd=0.0,
                macd_signal=0.0,
                trend=trend,
                last_updated=datetime.now()
            )
        except Exception as e:
            logger.error(f"Failed to fetch technicals for {symbol}: {e}")
            return None
