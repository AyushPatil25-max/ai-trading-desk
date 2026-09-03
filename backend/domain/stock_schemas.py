from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime, date
from enum import Enum

class StockDecision(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    WATCH = "WATCH"
    HOLD = "HOLD"
    AVOID = "AVOID"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class StockFundamentalData(BaseModel):
    symbol: str
    revenue: Optional[float] = None
    revenue_growth: Optional[float] = None
    ebitda: Optional[float] = None
    ebitda_margin: Optional[float] = None
    ebit: Optional[float] = None
    pat: Optional[float] = None
    pat_growth: Optional[float] = None
    eps: Optional[float] = None
    book_value: Optional[float] = None
    operating_cash_flow: Optional[float] = None
    free_cash_flow: Optional[float] = None
    total_debt: Optional[float] = None
    cash: Optional[float] = None
    debt_equity: Optional[float] = None
    roe: Optional[float] = None
    roce: Optional[float] = None
    current_ratio: Optional[float] = None
    promoter_holding: Optional[float] = None
    promoter_pledge: Optional[float] = None
    institutional_holding: Optional[float] = None
    fii_holding: Optional[float] = None
    dii_holding: Optional[float] = None
    retail_holding: Optional[float] = None
    dividend_yield: Optional[float] = None
    pe: Optional[float] = None
    pb: Optional[float] = None
    ps: Optional[float] = None
    ev_ebitda: Optional[float] = None
    peg: Optional[float] = None
    last_updated: datetime = Field(default_factory=datetime.now)

class StockTechnicalData(BaseModel):
    symbol: str
    current_price: Optional[float] = None
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    ema_20: Optional[float] = None
    rsi_14: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    adx: Optional[float] = None
    atr: Optional[float] = None
    bollinger_upper: Optional[float] = None
    bollinger_lower: Optional[float] = None
    vwap: Optional[float] = None
    volatility: Optional[float] = None
    volume_sma_20: Optional[float] = None
    last_updated: datetime = Field(default_factory=datetime.now)

class StrategyScore(BaseModel):
    score: float
    confidence: float
    reasons: List[str]

class StockAnalysisResult(BaseModel):
    symbol: str
    overall_score: float
    fundamental_score: float
    valuation_score: float
    technical_score: float
    momentum_score: float
    quality_score: float
    risk_score: float
    confidence: float
    data_quality_score: float
    decision: StockDecision
    positive_factors: List[str]
    negative_factors: List[str]
    risk_warnings: List[str]
    invalidation_conditions: List[str]
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
    fundamental_reasons: List[str]
    valuation_reasons: List[str]
    trend_reasons: List[str]
    risk_reasons: List[str]
