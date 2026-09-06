import logging
from typing import List, Dict, Optional
import asyncio
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
import numpy as np

from backend.domain.stock_schemas import StockFundamentalData, StockTechnicalData, OHLCV
from backend.infrastructure.security_master import get_security_master
from backend.application.market_data_gateway import get_market_data_gateway
from backend.execution.live_execution_gate import global_live_execution_gate
from backend.infrastructure.providers.technical_indicators import (
    calc_sma, calc_ema, calc_rsi, calc_macd, calc_atr, calc_adx,
    calc_bollinger_bands, calc_supertrend, calc_pivot_points
)

logger = logging.getLogger(__name__)

class IMarketDataProvider:
    async def get_fundamentals(self, symbol: str) -> Optional[StockFundamentalData]:
        pass
    
    async def get_technicals(self, symbol: str) -> Optional[StockTechnicalData]:
        pass

class UpstoxMarketDataProvider(IMarketDataProvider):
    """
    Legitimate live market data provider hooked into the Upstox Gateway and Integrity Engine.
    Also fetches historical data and fundamentals via yfinance.
    """
    def __init__(self):
        self.sm = get_security_master()
        self.integrity_engine = global_live_execution_gate.market_data_engine
        self.gateway = get_market_data_gateway()

    async def get_fundamentals(self, symbol: str) -> Optional[StockFundamentalData]:
        sec = self.sm.resolve_symbol(symbol)
        if not sec:
            return None
        
        yf_symbol = sec.canonical_symbol
        if not yf_symbol.endswith(".NS") and sec.exchange == "NSE":
            yf_symbol += ".NS"
            
        try:
            ticker = yf.Ticker(yf_symbol)
            info = ticker.info
            
            if not info:
                raise ValueError("No info returned from yfinance")
            
            return StockFundamentalData(
                symbol=symbol,
                company_name=info.get("longName") or sec.company_name,
                exchange=sec.exchange,
                sector=info.get("sector") or sec.sector,
                industry=info.get("industry") or sec.industry,
                market_cap=info.get("marketCap"),
                revenue=info.get("totalRevenue"),
                revenue_growth=info.get("revenueGrowth"),
                ebitda=info.get("ebitda"),
                ebitda_margin=info.get("ebitdaMargins"),
                operating_profit=info.get("operatingMargins"),
                pat=info.get("netIncomeToCommon"),
                eps=info.get("trailingEps"),
                pe=info.get("trailingPE"),
                pe_ratio=info.get("trailingPE"),
                pb=info.get("priceToBook"),
                pb_ratio=info.get("priceToBook"),
                roe=info.get("returnOnEquity"),
                roce=None, # DO NOT MOCK ROCE AS ROE
                total_debt=info.get("totalDebt"),
                debt_equity=info.get("debtToEquity"),
                cash=info.get("totalCash"),
                free_cash_flow=info.get("freeCashflow"),
                dividend_yield=info.get("dividendYield"),
                promoter_holding=info.get("heldPercentInsiders") * 100 if info.get("heldPercentInsiders") else None,
                institutional_holding=info.get("heldPercentInstitutions") * 100 if info.get("heldPercentInstitutions") else None,
                data_source="yfinance",
                last_updated=datetime.now()
            )
        except Exception as e:
            logger.error(f"Error fetching fundamentals for {symbol}: {e}")
            return StockFundamentalData(
                symbol=symbol,
                company_name=sec.company_name,
                sector=sec.sector,
                industry=sec.industry,
                data_source="SecurityMaster",
                last_updated=datetime.now()
            )

    def _safe_float(self, val):
        if pd.isna(val) or np.isnan(val) or np.isinf(val):
            return None
        return float(val)

    async def get_technicals(self, symbol: str) -> Optional[StockTechnicalData]:
        sec = self.sm.resolve_symbol(symbol)
        if not sec:
            return None
            
        quote = self.gateway.get_latest_quote(symbol)
        if not quote and sec.canonical_symbol:
            quote = self.gateway.get_latest_quote(sec.canonical_symbol)

        ltp = None
        prev_close = None
        
        if quote:
            ltp = quote.get("last_traded_price")
            prev_close = quote.get("previous_close")
        else:
            snapshot = self.integrity_engine.snapshots.get(symbol) or self.integrity_engine.snapshots.get(sec.canonical_symbol)
            if snapshot and snapshot.latest_tick:
                ltp = snapshot.latest_tick.last_traded_price

        yf_symbol = sec.canonical_symbol
        if not yf_symbol.endswith(".NS") and sec.exchange == "NSE":
            yf_symbol += ".NS"
            
        df = None
        data_freshness = "FRESH"
        try:
            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(period="1y")
            if df is not None and not df.empty:
                df = df.reset_index()
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                # Check stale data
                last_date = df['Date'].iloc[-1].date()
                if (datetime.now().date() - last_date).days > 3:
                    data_freshness = "STALE"
        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}")
            data_freshness = "INSUFFICIENT"
            
        tech_data = StockTechnicalData(
            symbol=symbol,
            current_price=ltp,
            data_source="Upstox",
            data_freshness=data_freshness,
            last_updated=datetime.now()
        )
        
        if df is not None and not df.empty and len(df) > 200:
            close = df["Close"]
            high = df["High"]
            low = df["Low"]
            volume = df["Volume"]
            
            if not tech_data.current_price:
                tech_data.current_price = self._safe_float(close.iloc[-1])
                
            price = tech_data.current_price
            
            if prev_close is None:
                prev_close = self._safe_float(close.iloc[-2]) if len(close) > 1 else None
            
            if price and prev_close and prev_close > 0:
                tech_data.daily_return = (price - prev_close) / prev_close
                tech_data.absolute_change = price - prev_close
                tech_data.percentage_change = tech_data.daily_return * 100
                tech_data.previous_close = prev_close
            
            # SMA & EMA
            tech_data.sma_20 = self._safe_float(calc_sma(close, 20).iloc[-1])
            tech_data.sma_50 = self._safe_float(calc_sma(close, 50).iloc[-1])
            tech_data.sma_100 = self._safe_float(calc_sma(close, 100).iloc[-1])
            tech_data.sma_200 = self._safe_float(calc_sma(close, 200).iloc[-1])
            
            tech_data.ema_9 = self._safe_float(calc_ema(close, 9).iloc[-1])
            tech_data.ema_20 = self._safe_float(calc_ema(close, 20).iloc[-1])
            tech_data.ema_50 = self._safe_float(calc_ema(close, 50).iloc[-1])
            tech_data.ema_200 = self._safe_float(calc_ema(close, 200).iloc[-1])
            
            # RSI & MACD
            tech_data.rsi_14 = self._safe_float(calc_rsi(close, 14).iloc[-1])
            
            macd, signal, hist = calc_macd(close)
            tech_data.macd = self._safe_float(macd.iloc[-1])
            tech_data.macd_signal = self._safe_float(signal.iloc[-1])
            tech_data.macd_histogram = self._safe_float(hist.iloc[-1])
            
            # ATR, ADX, DI
            tech_data.atr = self._safe_float(calc_atr(high, low, close).iloc[-1])
            adx, pdi, mdi = calc_adx(high, low, close)
            tech_data.adx = self._safe_float(adx.iloc[-1])
            tech_data.plus_di = self._safe_float(pdi.iloc[-1])
            tech_data.minus_di = self._safe_float(mdi.iloc[-1])
            
            # Bollinger Bands
            bb_upper, bb_mid, bb_lower = calc_bollinger_bands(close)
            tech_data.bollinger_upper = self._safe_float(bb_upper.iloc[-1])
            tech_data.bollinger_middle = self._safe_float(bb_mid.iloc[-1])
            tech_data.bollinger_lower = self._safe_float(bb_lower.iloc[-1])
            
            # SuperTrend
            st = calc_supertrend(high, low, close)
            tech_data.supertrend = self._safe_float(st.iloc[-1])
            
            # Pivot Points
            if len(df) > 1:
                prev_high = high.iloc[-2]
                prev_low = low.iloc[-2]
                prev_c = close.iloc[-2]
                tech_data.pivot_points = calc_pivot_points(prev_high, prev_low, prev_c)
                
            # 52W High Low
            tech_data.high_52w = self._safe_float(high.rolling(252).max().iloc[-1])
            tech_data.low_52w = self._safe_float(low.rolling(252).min().iloc[-1])
            
            if tech_data.high_52w and price:
                tech_data.distance_high_52w = ((tech_data.high_52w - price) / price) * 100
            if tech_data.low_52w and price:
                tech_data.distance_low_52w = ((price - tech_data.low_52w) / tech_data.low_52w) * 100
                
            # Trend
            if price > tech_data.sma_50 and tech_data.sma_50 > tech_data.sma_200:
                tech_data.trend = "BULLISH"
            elif price < tech_data.sma_50 and tech_data.sma_50 < tech_data.sma_200:
                tech_data.trend = "BEARISH"
            else:
                tech_data.trend = "NEUTRAL"
                
            # Support/Resistance based on recent highs/lows and pivots
            if tech_data.pivot_points:
                tech_data.support = tech_data.pivot_points.get("s1")
                tech_data.secondary_support = tech_data.pivot_points.get("s2")
                tech_data.resistance = tech_data.pivot_points.get("r1")
                tech_data.secondary_resistance = tech_data.pivot_points.get("r2")
                
                # Risk/Reward calculations (analytical only)
                if tech_data.trend == "BULLISH":
                    tech_data.entry_zone = price
                    tech_data.stop_loss = tech_data.support
                    tech_data.target_1 = tech_data.resistance
                    tech_data.target_2 = tech_data.secondary_resistance
                elif tech_data.trend == "BEARISH":
                    tech_data.entry_zone = price
                    tech_data.stop_loss = tech_data.resistance
                    tech_data.target_1 = tech_data.support
                    tech_data.target_2 = tech_data.secondary_support
                    
                if tech_data.entry_zone and tech_data.stop_loss and tech_data.target_1:
                    risk = abs(tech_data.entry_zone - tech_data.stop_loss)
                    reward = abs(tech_data.target_1 - tech_data.entry_zone)
                    if risk > 0:
                        tech_data.risk_amount = self._safe_float(risk)
                        tech_data.reward_amount = self._safe_float(reward)
                        tech_data.risk_reward_ratio = self._safe_float(reward / risk)
                        
            # Volume 
            tech_data.volume = int(volume.iloc[-1])
            vol_sma_20 = volume.rolling(20).mean().iloc[-1]
            if vol_sma_20 > 0:
                # Store relative volume in a field, we can just attach it directly if available, or just use volume.
                pass
                
        elif df is not None and not df.empty:
            if not tech_data.current_price:
                tech_data.current_price = self._safe_float(df["Close"].iloc[-1])
        
        return tech_data

def get_market_data_provider() -> IMarketDataProvider:
    from backend.config.app_config import get_app_config
    cfg = get_app_config()
    if cfg.market_data_provider == "upstox":
        return UpstoxMarketDataProvider()
    return UpstoxMarketDataProvider()
