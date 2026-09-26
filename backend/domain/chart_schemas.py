from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from enum import Enum
from datetime import datetime

class ChartDataState(str, Enum):
    LIVE = "LIVE"
    STALE = "STALE"
    HISTORICAL = "HISTORICAL"
    DISCONNECTED = "DISCONNECTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    ERROR = "ERROR"
    
class ChartDataQuality(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"
    ERROR = "ERROR"

class ChartCandle(BaseModel):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: Optional[float] = None

class ChartMultiTimeframeAlignment(str, Enum):
    ALIGNED_BULLISH = "ALIGNED_BULLISH"
    ALIGNED_BEARISH = "ALIGNED_BEARISH"
    MIXED = "MIXED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class ChartIndicatorData(BaseModel):
    sma20: Optional[float] = None
    sma50: Optional[float] = None
    sma200: Optional[float] = None
    ema20: Optional[float] = None
    ema50: Optional[float] = None
    ema200: Optional[float] = None
    rsi14: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    atr14: Optional[float] = None
    adx14: Optional[float] = None
    plus_di: Optional[float] = None
    minus_di: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    supertrend: Optional[float] = None
    pivot: Optional[float] = None
    r1: Optional[float] = None
    r2: Optional[float] = None
    r3: Optional[float] = None
    s1: Optional[float] = None
    s2: Optional[float] = None
    s3: Optional[float] = None

class ChartCandleWithIndicators(ChartCandle):
    indicators: ChartIndicatorData

class ChartResponse(BaseModel):
    symbol: str
    exchange: str
    timeframe: str
    data_state: ChartDataState
    data_quality: ChartDataQuality
    candles: List[ChartCandleWithIndicators]
    mtf_alignment: ChartMultiTimeframeAlignment
    historical_source: str
    live_source: Optional[str] = None
    generated_at: str
    last_market_update: Optional[str] = None

class TrendRegime(str, Enum):
    STRONG_UPTREND = 'STRONG_UPTREND'
    WEAK_UPTREND = 'WEAK_UPTREND'
    RANGING = 'RANGING'
    WEAK_DOWNTREND = 'WEAK_DOWNTREND'
    STRONG_DOWNTREND = 'STRONG_DOWNTREND'

class ChartPatternIntelligencePayload(BaseModel):
    symbol: str
    timeframe: str
    trend_regime: TrendRegime
    summary_claim: str

class VolatilityRegime(str, Enum):
    LOW = 'LOW'
    NORMAL = 'NORMAL'
    HIGH = 'HIGH'
    EXTREME = 'EXTREME'

class PatternStatus(str, Enum):
    FORMING = 'FORMING'
    CONFIRMED = 'CONFIRMED'
    INVALIDATED = 'INVALIDATED'

class BreakoutType(str, Enum):
    BULLISH = 'BULLISH'
    BEARISH = 'BEARISH'
    FALSE_BULLISH = 'FALSE_BULLISH'
    FALSE_BEARISH = 'FALSE_BEARISH'

class BreakoutSignal(BaseModel):
    breakout_type: BreakoutType
    confidence: float
    price_level: float
