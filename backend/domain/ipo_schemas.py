from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, model_validator
from datetime import datetime, date

class IPOStatus(str, Enum):
    UPCOMING = "UPCOMING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ALLOTMENT = "ALLOTMENT"
    LISTED = "LISTED"
    UNKNOWN = "UNKNOWN"

class IPOType(str, Enum):
    MAINBOARD = "MAINBOARD"
    SME = "SME"

class IPOMaster(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    company_name: str
    symbol: Optional[str] = None
    isin: Optional[str] = None
    exchange: str
    segment: IPOType
    status: IPOStatus
    
    open_date: Optional[date] = None
    close_date: Optional[date] = None
    allotment_date: Optional[date] = None
    refund_date: Optional[date] = None
    demat_credit_date: Optional[date] = None
    listing_date: Optional[date] = None
    
    price_band_low: Optional[float] = None
    price_band_high: Optional[float] = None
    issue_price: Optional[float] = None
    face_value: Optional[float] = None
    
    lot_size: Optional[int] = Field(None, alias="market_lot")
    minimum_investment: Optional[float] = None
    
    issue_size_crore: Optional[float] = None
    fresh_issue_crore: Optional[float] = None
    offer_for_sale_crore: Optional[float] = None
    total_shares: Optional[int] = Field(None, alias="total_issue_shares")
    fresh_issue_shares: Optional[int] = None
    ofs_shares: Optional[int] = None
    
    qib_subscription: Optional[float] = None
    nii_subscription: Optional[float] = None
    retail_subscription: Optional[float] = None
    employee_subscription: Optional[float] = None
    total_subscription: Optional[float] = None
    subscription_timestamp: Optional[datetime] = None
    
    gmp: Optional[float] = None
    gmp_timestamp: Optional[datetime] = None
    gmp_source: Optional[str] = None
    gmp_is_official: bool = False
    gmp_history: List[Dict[str, Any]] = Field(default_factory=list)
    subscription_history: List[Dict[str, Any]] = Field(default_factory=list)
    
    estimated_listing_price: Optional[float] = None
    estimated_listing_gain_pct: Optional[float] = None
    
    listing_price: Optional[float] = None
    listing_gain_pct: Optional[float] = None
    current_price: Optional[float] = None
    current_return_pct: Optional[float] = None
    
    book_running_lead_managers: List[str] = Field(default_factory=list)
    registrar: Optional[str] = None
    promoters: List[str] = Field(default_factory=list)
    industry: Optional[str] = None
    business_description: Optional[str] = None
    use_of_proceeds: Optional[str] = None
    
    revenue: Optional[float] = None
    ebitda: Optional[float] = None
    ebitda_margin: Optional[float] = None
    pat: Optional[float] = None
    pat_margin: Optional[float] = None
    eps: Optional[float] = None
    pe: Optional[float] = None
    roce: Optional[float] = None
    roe: Optional[float] = None
    debt: Optional[float] = None
    debt_equity: Optional[float] = None
    financial_period: Optional[str] = None
    financial_source: Optional[str] = None
    
    anchor_investment: Optional[float] = None
    anchor_date: Optional[date] = None
    
    risk_flags: List[str] = Field(default_factory=list)
    red_flags: List[str] = Field(default_factory=list)
    strengths: List[str] = Field(default_factory=list)
    
    ai_score: Optional[float] = None
    ai_verdict: Optional[str] = None
    ai_confidence: Optional[float] = None
    
    data_sources: List[str] = Field(default_factory=list)
    last_updated: Optional[datetime] = None
    data_quality: Optional[str] = None

    @model_validator(mode='after')
    def compute_fields(self):
        if self.minimum_investment is None and self.issue_price and self.lot_size:
            self.minimum_investment = self.issue_price * self.lot_size
        return self

    @property
    def total_issue_size(self):
        if self.issue_price and self.total_shares:
            return self.issue_price * self.total_shares
        return None

    @property
    def fresh_issue_size(self):
        if self.issue_price and self.fresh_issue_shares:
            return self.issue_price * self.fresh_issue_shares
        return None

    @property
    def ofs_size(self):
        if self.issue_price and self.ofs_shares:
            return self.issue_price * self.ofs_shares
        return None

    @property
    def latest_gmp(self):
        class _GMPObj:
            def __init__(self, ipo):
                self.ipo = ipo
            @property
            def gmp_percentage(self):
                if self.ipo.gmp and self.ipo.issue_price:
                    return (self.ipo.gmp / self.ipo.issue_price) * 100
                return None
            @property
            def estimated_listing_price(self):
                if self.ipo.gmp and self.ipo.issue_price:
                    return self.ipo.issue_price + self.ipo.gmp
                return None
        return _GMPObj(self)

class IPOScoreVerdict(str, Enum):
    STRONG = "STRONG"
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    WEAK = "WEAK"
    AVOID = "AVOID"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class IPOAnalysis(BaseModel):
    ipo_id: str
    overall_score: float
    fundamental_score: float = 0.0
    valuation_score: float = 0.0
    subscription_score: float = 0.0
    gmp_score: float = 0.0
    risk_score: float = 0.0
    confidence: float = 0.0
    verdict: IPOScoreVerdict
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    red_flags: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    analyzed_at: datetime

# --- LEGACY FIXTURES FOR TESTS ---
class GMPObservation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    ipo_id: str = Field(..., alias="id")
    gmp_value: float
    source: str = ''
    observed_at: datetime
    gmp_percentage: Optional[float] = None
    estimated_listing_price: Optional[float] = None

class IPOSubscriptionObservation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    ipo_id: str = Field(..., alias="id")
    observation_date: date
    total: float
    source: str = ''
    observed_at: datetime

''
