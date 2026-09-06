from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class OpportunityType(str, Enum):
    MOMENTUM = "MOMENTUM"
    BREAKOUT = "BREAKOUT"
    BREAKDOWN = "BREAKDOWN"
    REVERSAL = "REVERSAL"
    VOLUME_SPIKE = "VOLUME_SPIKE"
    GAP_UP = "GAP_UP"
    GAP_DOWN = "GAP_DOWN"
    TREND_CONTINUATION = "TREND_CONTINUATION"
    FIFTY_TWO_W_HIGH_BREAKOUT = "52W_HIGH_BREAKOUT"
    FIFTY_TWO_W_LOW_BREAKDOWN = "52W_LOW_BREAKDOWN"
    MEAN_REVERSION = "MEAN_REVERSION"
    STRONG_FUNDAMENTAL = "STRONG_FUNDAMENTAL"
    VALUE_OPPORTUNITY = "VALUE_OPPORTUNITY"

class OpportunityDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"

class MarketDataState(str, Enum):
    LIVE = "LIVE"
    STALE = "STALE"
    NO_TICKS = "NO_TICKS"
    DISCONNECTED = "DISCONNECTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    ERROR = "ERROR"
    HISTORICAL = "HISTORICAL"
    PAPER_REPLAY = "PAPER_REPLAY"

class TrendClassification(str, Enum):
    STRONG_UPTREND = "STRONG_UPTREND"
    UPTREND = "UPTREND"
    SIDEWAYS = "SIDEWAYS"
    DOWNTREND = "DOWNTREND"
    STRONG_DOWNTREND = "STRONG_DOWNTREND"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class BreakoutStatus(str, Enum):
    POTENTIAL_BREAKOUT = "POTENTIAL_BREAKOUT"
    CONFIRMED_BREAKOUT = "CONFIRMED_BREAKOUT"
    FAILED_BREAKOUT = "FAILED_BREAKOUT"
    POTENTIAL_BREAKDOWN = "POTENTIAL_BREAKDOWN"
    CONFIRMED_BREAKDOWN = "CONFIRMED_BREAKDOWN"
    FAILED_BREAKDOWN = "FAILED_BREAKDOWN"
    INTRADAY_SIGNAL = "INTRADAY_SIGNAL"
    NONE = "NONE"

class ReversalStatus(str, Enum):
    POTENTIAL_BULLISH_REVERSAL = "POTENTIAL_BULLISH_REVERSAL"
    POTENTIAL_BEARISH_REVERSAL = "POTENTIAL_BEARISH_REVERSAL"
    NONE = "NONE"

class VolumeStatus(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    VOLUME_SPIKE = "VOLUME_SPIKE"
    EXTREME = "EXTREME"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class GapStatus(str, Enum):
    SMALL_GAP = "SMALL_GAP"
    MEANINGFUL_GAP = "MEANINGFUL_GAP"
    LARGE_GAP = "LARGE_GAP"
    NONE = "NONE"

class MultiTimeframeAlignment(str, Enum):
    ALIGNED_BULLISH = "ALIGNED_BULLISH"
    ALIGNED_BEARISH = "ALIGNED_BEARISH"
    MIXED = "MIXED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class ScannerIdentity(BaseModel):
    symbol: str
    company_name: Optional[str] = None
    exchange: Optional[str] = "NSE"
    isin: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None

class ScannerMarketData(BaseModel):
    ltp: Optional[float] = None
    previous_close: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[int] = None
    average_volume: Optional[float] = None
    average_traded_value: Optional[float] = None
    liquidity_classification: Optional[str] = None
    volume_ratio: Optional[float] = None
    vwap: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    spread: Optional[float] = None
    timestamp: Optional[datetime] = None
    tick_age: Optional[float] = None
    data_quality: MarketDataState

class ScannerTechnicalData(BaseModel):
    trend: TrendClassification = TrendClassification.INSUFFICIENT_DATA
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    rsi_14: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    atr: Optional[float] = None
    adx: Optional[float] = None
    plus_di: Optional[float] = None
    minus_di: Optional[float] = None
    bollinger_upper: Optional[float] = None
    bollinger_lower: Optional[float] = None
    supertrend: Optional[float] = None
    pivot_level: Optional[float] = None
    support: Optional[float] = None
    resistance: Optional[float] = None

class ScannerSignals(BaseModel):
    momentum_signal: bool = False
    breakout_signal: BreakoutStatus = BreakoutStatus.NONE
    breakdown_signal: BreakoutStatus = BreakoutStatus.NONE
    reversal_signal: ReversalStatus = ReversalStatus.NONE
    volume_spike_signal: VolumeStatus = VolumeStatus.NORMAL
    gap_signal: GapStatus = GapStatus.NONE
    gap_direction: Optional[OpportunityDirection] = None
    gap_percent: Optional[float] = None
    trend_signal: TrendClassification = TrendClassification.INSUFFICIENT_DATA
    multi_timeframe_alignment: MultiTimeframeAlignment = MultiTimeframeAlignment.INSUFFICIENT_DATA
    fifty_two_week_high_signal: bool = False
    fifty_two_week_low_signal: bool = False

class ScannerFundamentalData(BaseModel):
    fundamental_score: Optional[float] = None
    valuation_score: Optional[float] = None
    growth_score: Optional[float] = None
    profitability_score: Optional[float] = None
    quality_score: Optional[float] = None

class ScannerRiskData(BaseModel):
    entry_reference: Optional[float] = None
    stop_loss_reference: Optional[float] = None
    target_reference: Optional[float] = None
    risk_reward: Optional[float] = None
    atr_risk: Optional[float] = None
    liquidity_risk: Optional[str] = None
    data_risk: Optional[str] = None

class ScannerOpportunity(BaseModel):
    opportunity_score: float = 0.0
    confidence: float = 0.0
    opportunity_type: OpportunityType
    direction: OpportunityDirection
    rationale: str
    risk_flags: List[str] = Field(default_factory=list)

class OpportunityScannerResult(BaseModel):
    identity: ScannerIdentity
    market: ScannerMarketData
    technical: ScannerTechnicalData
    signals: ScannerSignals
    fundamental: ScannerFundamentalData
    opportunity: ScannerOpportunity
    risk: ScannerRiskData
    
    analysis_timestamp: datetime = Field(default_factory=datetime.now)

class ScannerBatchResult(BaseModel):
    opportunities: List[OpportunityScannerResult]
    scan_timestamp: datetime = Field(default_factory=datetime.now)
    total_scanned: int = 0
    total_opportunities: int = 0
    unavailable_symbols: List[str] = Field(default_factory=list)
