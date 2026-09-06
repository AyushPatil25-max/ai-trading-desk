import logging
import asyncio
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from typing import List, Optional

from backend.infrastructure.security_master import get_security_master
from backend.application.market_data_gateway import get_market_data_gateway
from backend.infrastructure.providers.technical_indicators import (
    calc_sma, calc_ema, calc_rsi, calc_macd, calc_atr, calc_adx,
    calc_bollinger_bands, calc_supertrend, calc_pivot_points
)
from backend.domain.chart_schemas import (
    ChartResponse, ChartCandleWithIndicators, ChartIndicatorData,
    ChartDataState, ChartDataQuality, ChartMultiTimeframeAlignment
)

try:
    from backend.application.market_data_integrity_engine import get_market_data_integrity_engine
except ImportError:
    from backend.execution.live_execution_gate import global_live_execution_gate
    def get_market_data_integrity_engine():
        return global_live_execution_gate.market_data_engine

logger = logging.getLogger(__name__)

class ChartService:
    def __init__(self):
        self.gateway = get_market_data_gateway()
        self.integrity_engine = get_market_data_integrity_engine()
        self.sm = get_security_master()

    def _get_yf_symbol(self, symbol: str) -> str:
        sec = self.sm.resolve_symbol(symbol)
        if sec:
            s = sec.canonical_symbol
            return f"{s}.NS" if sec.exchange == "NSE" and not s.endswith(".NS") else s
        return symbol

    async def get_chart_data(self, symbol: str, timeframe: str) -> ChartResponse:
        valid_timeframes = {"1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d", "1h": "730d", "1D": "1y", "1W": "5y"}
        if timeframe not in valid_timeframes:
            return self._build_empty_response(symbol, timeframe, ChartDataState.INSUFFICIENT_DATA, ChartDataQuality.INSUFFICIENT)

        yf_sym = self._get_yf_symbol(symbol)
        period = valid_timeframes[timeframe]
        
        # 1. Fetch OHLCV
        try:
            ticker = yf.Ticker(yf_sym)
            df = ticker.history(period=period, interval=timeframe.replace("1D", "1d").replace("1W", "1wk"))
        except Exception as e:
            logger.error(f"Chart fetch error for {symbol} {timeframe}: {e}")
            return self._build_empty_response(symbol, timeframe, ChartDataState.ERROR, ChartDataQuality.ERROR)

        if df is None or df.empty or len(df) < 5:
            return self._build_empty_response(symbol, timeframe, ChartDataState.INSUFFICIENT_DATA, ChartDataQuality.INSUFFICIENT)

        # Ensure correct column names
        df = df.rename(columns=str.capitalize)
        if 'Datetime' in df.columns:
            df = df.set_index('Datetime')
        elif 'Date' in df.columns:
            df = df.set_index('Date')
            
        original_len = len(df)
        
        # Validation: Sort chronologically, drop duplicates, enforce bounds
        df = df.sort_index()
        df = df[~df.index.duplicated(keep='last')]
        df = df[
            (df['Open'] > 0) & 
            (df['High'] > 0) & 
            (df['Low'] > 0) & 
            (df['Close'] > 0) & 
            (df['Volume'] >= 0) & 
            (df['High'] >= df['Low']) &
            (df['Low'] <= df['Open']) & (df['Open'] <= df['High']) &
            (df['Low'] <= df['Close']) & (df['Close'] <= df['High'])
        ].dropna(subset=['Close', 'High', 'Low', 'Open'])
        
        data_quality = ChartDataQuality.PARTIAL if len(df) < original_len else ChartDataQuality.COMPLETE
        
        if len(df) < 5:
            return self._build_empty_response(symbol, timeframe, ChartDataState.INSUFFICIENT_DATA, ChartDataQuality.INSUFFICIENT)

        # 2. Live Data Overwrite (If applicable)
        quote = self.gateway.get_latest_quote(symbol)
        is_valid = self.integrity_engine.fail_closed_check(symbol)
        
        data_state = ChartDataState.HISTORICAL
        last_market_update = None
        
        if quote:
            if is_valid:
                data_state = ChartDataState.LIVE
                ts = quote.get("timestamp") or quote.get("last_traded_time") or quote.get("exchange_timestamp")
                if isinstance(ts, (int, float)):
                    # handle ms vs s
                    ts_val = ts / 1000.0 if ts > 10000000000 else ts
                    try:
                        last_market_update = datetime.fromtimestamp(ts_val, tz=timezone.utc).isoformat()
                    except:
                        pass
                elif isinstance(ts, str):
                    last_market_update = ts
                
                # Update the last candle ONLY if it is LIVE and matches the current session
                if timeframe in ["1m", "5m", "15m", "30m", "1h", "1D"]:
                    last_date = df.index[-1].date()
                    today = datetime.now(timezone.utc).date()
                    
                    if last_date == today:
                        ltp = float(quote.get("last_traded_price") or quote.get("ltp") or df['Close'].iloc[-1])
                        vol = float(quote.get("volume") or df['Volume'].iloc[-1])
                        
                        df.iloc[-1, df.columns.get_loc('Close')] = ltp
                        if ltp > df['High'].iloc[-1]:
                            df.iloc[-1, df.columns.get_loc('High')] = ltp
                        if ltp < df['Low'].iloc[-1]:
                            df.iloc[-1, df.columns.get_loc('Low')] = ltp
                        if vol > 0:
                            df.iloc[-1, df.columns.get_loc('Volume')] = vol
            else:
                data_state = ChartDataState.STALE
                
        # 3. Calculate Indicators
        c = df['Close']
        h = df['High']
        l = df['Low']
        v = df['Volume']
        
        def safe_series(calc_func, *args, **kwargs):
            try:
                res = calc_func(*args, **kwargs)
                if isinstance(res, tuple):
                    return res
                return res
            except Exception:
                return pd.Series(index=df.index, dtype=float)
                
        sma20 = safe_series(calc_sma, c, 20)
        sma50 = safe_series(calc_sma, c, 50)
        sma200 = safe_series(calc_sma, c, 200)
        ema20 = safe_series(calc_ema, c, 20)
        ema50 = safe_series(calc_ema, c, 50)
        ema200 = safe_series(calc_ema, c, 200)
        rsi14 = safe_series(calc_rsi, c, 14)
        
        try:
            macd, macd_sig, macd_h = calc_macd(c)
        except Exception:
            macd, macd_sig, macd_h = pd.Series(), pd.Series(), pd.Series()
            
        atr14 = safe_series(calc_atr, h, l, c, 14)
        
        try:
            adx, pdi, mdi = calc_adx(h, l, c, 14)
        except Exception:
            adx, pdi, mdi = pd.Series(), pd.Series(), pd.Series()
            
        try:
            bbu, bbm, bbl = calc_bollinger_bands(c, 20, 2)
        except Exception:
            bbu, bbm, bbl = pd.Series(), pd.Series(), pd.Series()
            
        st = safe_series(calc_supertrend, h, l, c, 10, 3.0)
        
        # Session VWAP correction
        if timeframe in ["1m", "5m", "15m", "30m", "1h"]:
            df_temp = df.copy()
            df_temp['DateStr'] = df_temp.index.date
            vwap = pd.Series(index=df.index, dtype=float)
            for date, group in df_temp.groupby('DateStr'):
                cv = group['Close'] * group['Volume']
                v_sum = group['Volume'].cumsum()
                vwap.loc[group.index] = cv.cumsum() / v_sum.where(v_sum > 0, 1)
        else:
            vwap = (c * v).cumsum() / v.cumsum() if v.sum() > 0 else pd.Series(index=df.index, dtype=float)
        
        # 4. Multi-Timeframe Alignment
        mtf = ChartMultiTimeframeAlignment.INSUFFICIENT_DATA
        if timeframe == "1D" and len(df) >= 100 and isinstance(df.index, pd.DatetimeIndex):
            try:
                w_df = df.resample('W').agg({'Open':'first', 'High':'max', 'Low':'min', 'Close':'last'}).dropna()
                if len(w_df) > 20:
                    w_sma = calc_sma(w_df['Close'], 20)
                    w_trend = w_df['Close'].iloc[-1] > w_sma.iloc[-1]
                    d_trend = c.iloc[-1] > sma20.iloc[-1]
                    if w_trend and d_trend:
                        mtf = ChartMultiTimeframeAlignment.ALIGNED_BULLISH
                    elif not w_trend and not d_trend:
                        mtf = ChartMultiTimeframeAlignment.ALIGNED_BEARISH
                    else:
                        mtf = ChartMultiTimeframeAlignment.MIXED
            except Exception:
                pass
                
        # Calculate pivots on previous completed candle
        pivots = {}
        if len(df) > 1:
            prev_h, prev_l, prev_c = float(h.iloc[-2]), float(l.iloc[-2]), float(c.iloc[-2])
            pivots = calc_pivot_points(prev_h, prev_l, prev_c)
            
        # 5. Build Candles
        candles = []
        for i in range(len(df)):
            idx = df.index[i]
            
            def sf(series):
                if series is None or len(series) <= i: return None
                val = series.iloc[i]
                return float(val) if pd.notna(val) else None

            # Base properties
            p = pivots if i == len(df) - 1 else {}
            
            ind = ChartIndicatorData(
                sma20=sf(sma20), sma50=sf(sma50), sma200=sf(sma200),
                ema20=sf(ema20), ema50=sf(ema50), ema200=sf(ema200),
                rsi14=sf(rsi14), macd=sf(macd), macd_signal=sf(macd_sig), macd_hist=sf(macd_h),
                atr14=sf(atr14), adx14=sf(adx), plus_di=sf(pdi), minus_di=sf(mdi),
                bb_upper=sf(bbu), bb_middle=sf(bbm), bb_lower=sf(bbl),
                supertrend=sf(st),
                pivot=p.get('pivot'), r1=p.get('r1'), r2=p.get('r2'), r3=p.get('r3'),
                s1=p.get('s1'), s2=p.get('s2'), s3=p.get('s3')
            )
            
            candles.append(ChartCandleWithIndicators(
                timestamp=str(idx),
                open=float(df['Open'].iloc[i]),
                high=float(h.iloc[i]),
                low=float(l.iloc[i]),
                close=float(c.iloc[i]),
                volume=float(v.iloc[i]),
                vwap=sf(vwap),
                indicators=ind
            ))
            
        return ChartResponse(
            symbol=symbol,
            exchange=self.sm.resolve_symbol(symbol).exchange if self.sm.resolve_symbol(symbol) else "NSE",
            timeframe=timeframe,
            data_state=data_state,
            data_quality=data_quality,
            candles=candles,
            mtf_alignment=mtf,
            historical_source="yfinance",
            live_source="Upstox" if quote else None,
            generated_at=datetime.now(timezone.utc).isoformat(),
            last_market_update=last_market_update
        )

    def _build_empty_response(self, symbol: str, timeframe: str, state: ChartDataState, quality: ChartDataQuality) -> ChartResponse:
        return ChartResponse(
            symbol=symbol,
            exchange="NSE",
            timeframe=timeframe,
            data_state=state,
            data_quality=quality,
            candles=[],
            mtf_alignment=ChartMultiTimeframeAlignment.INSUFFICIENT_DATA,
            historical_source="yfinance",
            live_source=None,
            generated_at=datetime.now(timezone.utc).isoformat()
        )
