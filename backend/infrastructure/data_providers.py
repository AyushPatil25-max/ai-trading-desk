from abc import ABC, abstractmethod
from typing import Dict, Any
from datetime import datetime
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
        
        generated_at = datetime.utcnow()
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
            
        # Data Quality Check: missing/NaN values
        if df['Close'].isnull().any():
            warnings.append("NaN values detected in Close prices. Forward filling applied.")
            df['Close'] = df['Close'].ffill()
            
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
        
        # Calculate Technicals (Standardized to use indicators.py logic eventually)
        df = self._calculate_technicals(df)
        
        latest = df.iloc[-1]
        current_price = float(latest['Close'])
        
        if np.isnan(current_price) or current_price <= 0:
            quality_status = DataQualityStatus.CRITICAL_FAILURE
            warnings.append("Invalid current price.")
            
        technical_indicators = {
            "ema20": round(float(latest.get('EMA20', 0.0)), 2),
            "ema50": round(float(latest.get('EMA50', 0.0)), 2),
            "rsi": round(float(latest.get('RSI', 0.0)), 2),
            "20_day_high": round(float(latest.get('20_day_high', 0.0)), 2)
        }
        
        # Format OHLCV for context based on requested window
        ohlcv = []
        target_rows = HistoricalWindow.get_days(window)
        for index, row in df.tail(target_rows).iterrows():
            ohlcv.append({
                "date": index.isoformat(),
                "open": row["Open"],
                "high": row["High"],
                "low": row["Low"],
                "close": row["Close"],
                "volume": row["Volume"]
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
        # We will import the common indicators.py logic here.
        # For now, implementing the exact exact logic from indicators.py
        from backend.indicators import calculate_indicators
        df = calculate_indicators(df)
        
        # 20-Day High (required by technical_agent, currently in market_data.py)
        df['20_day_high'] = df['High'].rolling(window=20).max()
        return df
