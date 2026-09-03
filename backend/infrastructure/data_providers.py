from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import math
import pandas as pd
import numpy as np

from backend.domain.schemas import MarketContext, DataQualityStatus, HistoricalWindow

class MarketDataProvider(ABC):
    """
    Abstract base class for market data providers.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass
        
    @abstractmethod
    def get_market_context(self, symbol: str, window: HistoricalWindow = HistoricalWindow.RECENT) -> MarketContext:
        """
        Fetch normalized market data as a Unified Market Context.
        This operation is intentionally blocking and should be isolated 
        using asyncio.to_thread in the application layer.
        
        Caching Note: Future caching should be implemented at this boundary
        or within the application orchestration layer. 
        - Historical OHLCV is highly cacheable.
        - Latest price / intraday requires freshness.
        """
        pass
        
    @abstractmethod
    def get_historical_data(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        """
        Fetch raw historical data for a symbol.
        """
        pass

class YFinanceProvider(MarketDataProvider):
    @property
    def name(self) -> str:
        return "yfinance"
        
    def get_historical_data(self, symbol: str, period: str = "60d") -> pd.DataFrame:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)
        return df

    def get_market_context(self, symbol: str, window: HistoricalWindow = HistoricalWindow.RECENT) -> MarketContext:
        # We need at least 60 days to calculate technicals like EMA50 reliably.
        # If requested window is longer, we fetch that.
        fetch_period_map = {
            HistoricalWindow.RECENT: "3mo",   # 5D needs 3mo for EMA50
            HistoricalWindow.SHORT: "3mo",    # 20D needs 3mo for EMA50
            HistoricalWindow.MEDIUM: "3mo",   # 60D needs 3mo for EMA50
            HistoricalWindow.LONG: "1y"       # 252D needs 1y
        }
        period_str = fetch_period_map[window]
        df = self.get_historical_data(symbol, period=period_str)
        
        generated_at = datetime.now(timezone.utc)
        warnings = []
        
        if df is None or df.empty:
            import uuid
            return MarketContext(
                context_id=str(uuid.uuid4()),
                symbol=symbol,
                generated_at=generated_at,
                data_timestamp=generated_at, # No real data
                provider=self.name,
                historical_window=window,
                current_price=0.0,
                quality_status=DataQualityStatus.CRITICAL_FAILURE,
                warnings=["Empty dataset returned from provider."]
            )

        # Drop trailing rows where price columns are all NaN (e.g. unclosed intraday placeholders)
        price_cols = [c for c in ['Open', 'High', 'Low', 'Close'] if c in df.columns]
        if price_cols:
            df = df.dropna(how='all', subset=price_cols)

        if df.empty:
            import uuid
            return MarketContext(
                context_id=str(uuid.uuid4()),
                symbol=symbol,
                generated_at=generated_at,
                data_timestamp=generated_at,
                provider=self.name,
                historical_window=window,
                current_price=0.0,
                quality_status=DataQualityStatus.CRITICAL_FAILURE,
                warnings=["Empty dataset after removing non-finite rows."]
            )

        # Data Quality Check: missing/NaN values across OHLCV
        for col in price_cols:
            if df[col].isnull().any():
                warnings.append(f"NaN values detected in {col} prices. Forward filling applied.")
                df[col] = df[col].ffill().bfill()
            
        # Ensure sufficient rows for EMA50
        if len(df) < 50:
            warnings.append(f"Insufficient historical rows: {len(df)} (needs 50+ for EMA50).")
            quality_status = DataQualityStatus.DEGRADED
        else:
            quality_status = DataQualityStatus.OK
            
        # Ensure time index is timezone aware / standard
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
            
        data_timestamp = df.index[-1].to_pydatetime()
        
        # Calculate Technicals (Standardized to use indicators.py logic)
        df = self._calculate_technicals(df)
        
        def _safe_float(val: Any) -> Optional[float]:
            if val is None:
                return None
            try:
                if pd.isna(val):
                    return None
                f = float(val)
                if math.isnan(f) or math.isinf(f):
                    return None
                return round(f, 2)
            except (ValueError, TypeError):
                return None

        latest = df.iloc[-1]
        current_price = _safe_float(latest.get('Close')) or 0.0
        
        if current_price <= 0:
            quality_status = DataQualityStatus.CRITICAL_FAILURE
            warnings.append("Invalid current price.")
            
        technical_indicators = {
            "ema20": _safe_float(latest.get('EMA20')),
            "ema50": _safe_float(latest.get('EMA50')),
            "rsi": _safe_float(latest.get('RSI')),
            "20_day_high": _safe_float(latest.get('20_day_high'))
        }
        
        # Format OHLCV for context based on requested window
        ohlcv = []
        target_rows = HistoricalWindow.get_days(window)
        for index, row in df.tail(target_rows).iterrows():
            ohlcv.append({
                "date": index.isoformat(),
                "open": _safe_float(row.get("Open")) or 0.0,
                "high": _safe_float(row.get("High")) or 0.0,
                "low": _safe_float(row.get("Low")) or 0.0,
                "close": _safe_float(row.get("Close")) or 0.0,
                "volume": _safe_float(row.get("Volume")) or 0.0
            })

        import uuid
        context_id = str(uuid.uuid4())
        
        return MarketContext(
            context_id=context_id,
            symbol=symbol,
            generated_at=generated_at,
            data_timestamp=data_timestamp,
            provider=self.name,
            is_cached=False,
            historical_window=window,
            current_price=current_price,
            ohlcv_historical=ohlcv,
            technical_indicators=technical_indicators,
            quality_status=quality_status,
            warnings=warnings
        )
        
    def _calculate_technicals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Internal normalization using the consolidated logic.
        """
        if df.empty:
            return df
        from backend.indicators import calculate_indicators
        df = calculate_indicators(df)
        
        # 20-Day High (required by technical_agent)
        if 'High' in df.columns and len(df) >= 20:
            df['20_day_high'] = df['High'].rolling(window=20, min_periods=20).max()
        else:
            df['20_day_high'] = None
        return df
