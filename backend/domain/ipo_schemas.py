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

class GMPStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    UNVERIFIED = "UNVERIFIED"

class ValuationVerdict(str, Enum):
    UNDERVALUED = "UNDERVALUED"
    FAIRLY_VALUED = "FAIRLY_VALUED"
    OVERVALUED = "OVERVALUED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class DataQuality(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    INSUFFICIENT = "INSUFFICIENT"
    ERROR = "ERROR"

class ListingScenario(BaseModel):
    scenario_name: str
    estimated_listing_price: Optional[float] = None
    estimated_gain_percent: Optional[float] = None
    methodology: str = "Analytical Estimate"
    is_analytical_estimate: bool = True

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
    minimum_application_shares: Optional[int] = None
    minimum_application_lots: Optional[int] = None
    maximum_retail_investment: Optional[float] = None
    
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
    
    gmp_status: Optional[GMPStatus] = None
    gmp_disclaimer: str = "GMP is UNOFFICIAL and can change rapidly. It does not guarantee listing gains."
    listing_scenarios: List[ListingScenario] = Field(default_factory=list)
    
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
    peer_pe_median: Optional[float] = None
    sector_pe: Optional[float] = None
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
    
    fundamental_score: Optional[float] = None
    valuation_score: Optional[float] = None
    subscription_score: Optional[float] = None
    gmp_score: Optional[float] = None
    risk_score: Optional[float] = None
    listing_score: Optional[float] = None
    long_term_score: Optional[float] = None
    
    data_sources: List[str] = Field(default_factory=list)
    source_name: Optional[str] = None
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    last_updated: Optional[datetime] = None
    data_quality: Optional[str] = None
    data_quality_status: Optional[DataQuality] = None
    data_quality_reasons: List[str] = Field(default_factory=list)

    gmp_age_days: Optional[float] = None
    calculation_price_used: Optional[str] = None

    @model_validator(mode='after')
    def compute_fields(self):
        # We DO NOT default minimum_application_lots to 1 anymore.
        # It must be provided by the source, or remain None.
        if self.lot_size and self.minimum_application_lots is not None:
            self.minimum_application_shares = self.lot_size * self.minimum_application_lots
            
        # Document which price is used
        price = None
        if self.issue_price:
            price = self.issue_price
            self.calculation_price_used = "issue_price"
        elif self.price_band_low:
            price = self.price_band_low
            self.calculation_price_used = "price_band_low"
        elif self.price_band_high:
            price = self.price_band_high
            self.calculation_price_used = "price_band_high"
            
        # Minimum investment must use explicitly verified shares if available
        if self.minimum_application_shares is not None and price is not None:
            self.minimum_investment = self.minimum_application_shares * price
            
        # Retail max limit logic: explicitly for mainboard. 
        if self.segment == IPOType.MAINBOARD and price and self.lot_size:
            max_lots = int(200000 // (self.lot_size * price))
            if max_lots > 0:
                self.maximum_retail_investment = max_lots * self.lot_size * price
        
        # SME logic: explicitly rely on application_shares/lots provided by source.
        # We do not guess "> 1,00,000". If source doesn't provide it, we leave it null.
        
        # GMP status and age
        if self.gmp is not None:
            if not self.gmp_status:
                self.gmp_status = GMPStatus.AVAILABLE
            if self.gmp_timestamp:
                now = datetime.now(self.gmp_timestamp.tzinfo) if self.gmp_timestamp.tzinfo else datetime.now()
                age_seconds = (now - self.gmp_timestamp).total_seconds()
                self.gmp_age_days = age_seconds / 86400.0
                if self.gmp_age_days > 2.0:  # Configurable threshold conceptually
                    self.gmp_status = GMPStatus.STALE
        else:
            self.gmp_status = GMPStatus.UNAVAILABLE
            
        # Listing scenarios - explicitly marked as analytical estimates
        if self.gmp is not None and price and not self.listing_scenarios:
            self.listing_scenarios = [
                ListingScenario(
                    scenario_name="BEAR", 
                    estimated_listing_price=price + (self.gmp * 0.5), 
                    estimated_gain_percent=((self.gmp * 0.5) / price) * 100,
                ),
                ListingScenario(
                    scenario_name="BASE", 
                    estimated_listing_price=price + self.gmp, 
                    estimated_gain_percent=(self.gmp / price) * 100,
                ),
                ListingScenario(
                    scenario_name="BULL", 
                    estimated_listing_price=price + (self.gmp * 1.5), 
                    estimated_gain_percent=((self.gmp * 1.5) / price) * 100,
                )
            ]

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
    STRONG_POSITIVE = "STRONG_POSITIVE"
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"
    AVOID = "AVOID"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    STRONG = "STRONG" # legacy mapping
    WEAK = "WEAK" # legacy mapping

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
    valuation_verdict: Optional[ValuationVerdict] = None
    is_analytical_estimate: bool = True
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    red_flags: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    analyzed_at: datetime
    data_quality_status: Optional[DataQuality] = None
    data_quality_reasons: List[str] = Field(default_factory=list)

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
