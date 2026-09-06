from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime, date
from enum import Enum

class StockDecision(str, Enum):
    STRONG_BULLISH = "STRONG_BULLISH"
    BULLISH = "BULLISH"
    HOLD = "HOLD"
    BEARISH = "BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"
    REJECT = "REJECT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class StockFundamentalData(BaseModel):
    symbol: str
    company_name: Optional[str] = None
    exchange: Optional[str] = None
    nse_symbol: Optional[str] = None
    bse_symbol: Optional[str] = None
    isin: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    
    revenue: Optional[float] = None
    revenue_growth: Optional[float] = None
    ebitda: Optional[float] = None
    ebitda_margin: Optional[float] = None
    operating_profit: Optional[float] = None
    ebit: Optional[float] = None
    pat: Optional[float] = None
    pat_growth: Optional[float] = None
    eps: Optional[float] = None
    
    pe: Optional[float] = None
    pe_ratio: Optional[float] = None
    pb: Optional[float] = None
    pb_ratio: Optional[float] = None
    roe: Optional[float] = None
    roce: Optional[float] = None
    
    total_debt: Optional[float] = None
    debt: Optional[float] = None
    debt_equity: Optional[float] = None
    debt_to_equity: Optional[float] = None
    cash: Optional[float] = None
    free_cash_flow: Optional[float] = None
    operating_cash_flow: Optional[float] = None
    
    dividend: Optional[float] = None
    dividend_yield: Optional[float] = None
    
    promoter_holding: Optional[float] = None
    promoter_pledge: Optional[float] = None
    institutional_holding: Optional[float] = None
    fii_holding: Optional[float] = None
    dii_holding: Optional[float] = None
    retail_holding: Optional[float] = None
    
    data_source: Optional[str] = None
    last_updated: datetime = Field(default_factory=datetime.now)

class OHLCV(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

class StockTechnicalData(BaseModel):
    symbol: str
    current_price: Optional[float] = None
    previous_close: Optional[float] = None
    absolute_change: Optional[float] = None
    percentage_change: Optional[float] = None
    daily_return: Optional[float] = None
    
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[int] = None
    average_traded_price: Optional[float] = None
    vwap: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    spread: Optional[float] = None
    timestamp: Optional[datetime] = None
    
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    distance_high_52w: Optional[float] = None
    distance_low_52w: Optional[float] = None
    
    trend: Optional[str] = None
    
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_100: Optional[float] = None
    sma_200: Optional[float] = None
    ema_9: Optional[float] = None
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None
    
    rsi_14: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    
    atr: Optional[float] = None
    adx: Optional[float] = None
    plus_di: Optional[float] = None
    minus_di: Optional[float] = None
    
    bollinger_upper: Optional[float] = None
    bollinger_middle: Optional[float] = None
    bollinger_lower: Optional[float] = None
    
    supertrend: Optional[float] = None
    pivot_points: Optional[Dict[str, float]] = None
    
    support: Optional[float] = None
    resistance: Optional[float] = None
    secondary_support: Optional[float] = None
    secondary_resistance: Optional[float] = None
    breakout_level: Optional[float] = None
    breakdown_level: Optional[float] = None
    
    entry_zone: Optional[float] = None
    stop_loss: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    target_3: Optional[float] = None
    risk_amount: Optional[float] = None
    reward_amount: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    
    daily_ohlcv: Optional[List[OHLCV]] = None
    weekly_ohlcv: Optional[List[OHLCV]] = None
    monthly_ohlcv: Optional[List[OHLCV]] = None

    data_source: Optional[str] = "Upstox"
    data_freshness: Optional[str] = None
    last_updated: datetime = Field(default_factory=datetime.now)

class StrategyScore(BaseModel):
    score: float
    confidence: float
    reasons: List[str]

class StockAnalysisResult(BaseModel):
    symbol: str
    company_name: Optional[str] = None
    exchange: Optional[str] = "NSE"
    
    overall_score: float
    technical_score: float
    fundamental_score: float
    momentum_score: float
    trend_score: float
    valuation_score: float
    risk_score: float
    quality_score: float
    data_quality_score: float
    
    confidence: float
    confidence_score: Optional[float] = None
    
    decision: StockDecision
    verdict: Optional[str] = None
    
    current_price: Optional[float] = None
    price_change: Optional[float] = None
    price_change_pct: Optional[float] = None
    volume: Optional[int] = None
    
    data_status: Optional[str] = None
    data_freshness: Optional[str] = None
    data_source: Optional[str] = "Upstox"
    
    reasons: List[str] = Field(default_factory=list)
    positive_factors: List[str] = Field(default_factory=list)
    negative_factors: List[str] = Field(default_factory=list)
    risk_warnings: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    
    fundamental_data: Optional[StockFundamentalData] = None
    technical_data: Optional[StockTechnicalData] = None
    
    analysis_timestamp: datetime = Field(default_factory=datetime.now)

class ScreenerCriteria(BaseModel):
    min_roe: Optional[float] = None
    min_roce: Optional[float] = None
    max_debt_equity: Optional[float] = None
    max_pe: Optional[float] = None
    min_revenue_growth: Optional[float] = None
    min_pat_growth: Optional[float] = None
    max_promoter_pledge: Optional[float] = None

class StockScreenerResult(BaseModel):
    symbol: str
    company_name: Optional[str] = None
    overall_score: Optional[float] = None
    decision: Optional[str] = None
    price: Optional[float] = None
    pe_ratio: Optional[float] = None
    roe: Optional[float] = None
    confidence: Optional[float] = None
    thesis: Optional[str] = None
    fundamental_reasons: List[str] = Field(default_factory=list)
    valuation_reasons: List[str] = Field(default_factory=list)
    trend_reasons: List[str] = Field(default_factory=list)
    risk_reasons: List[str] = Field(default_factory=list)
    data_source: Optional[str] = "Upstox"
    timestamp: Optional[datetime] = Field(default_factory=datetime.now)
