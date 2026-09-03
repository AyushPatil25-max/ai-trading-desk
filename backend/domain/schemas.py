import uuid
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from enum import Enum



class SnapshotFreshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    INVALID = "INVALID"
    MISSING = "MISSING"

class HistoricalWindow(str, Enum):
    RECENT = "5D"
    SHORT = "20D"
    MEDIUM = "60D"
    LONG = "252D"

    @classmethod
    def get_days(cls, window: "HistoricalWindow") -> int:
        mapping = {
            cls.RECENT: 5,
            cls.SHORT: 20,
            cls.MEDIUM: 60,
            cls.LONG: 252
        }
        return mapping[window]


class AgentState(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    DEGRADED = "DEGRADED"


class DataQualityStatus(str, Enum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    CRITICAL_FAILURE = "CRITICAL_FAILURE"


class DataQualityTier(str, Enum):
    TIER_1_PRIMARY_OFFICIAL = "TIER_1_PRIMARY_OFFICIAL"
    TIER_2_REGULATORY = "TIER_2_REGULATORY"
    TIER_3_PREMIUM_AGGREGATOR = "TIER_3_PREMIUM_AGGREGATOR"
    TIER_4_STANDARD_AGGREGATOR = "TIER_4_STANDARD_AGGREGATOR"
    TIER_5_UNVERIFIED_SECONDARY = "TIER_5_UNVERIFIED_SECONDARY"


class ProviderType(str, Enum):
    EXCHANGE = "EXCHANGE"
    REGULATORY = "REGULATORY"
    PREMIUM_DATA_VENDOR = "PREMIUM_DATA_VENDOR"
    STANDARD_DATA_VENDOR = "STANDARD_DATA_VENDOR"
    PUBLIC_SCRAPER = "PUBLIC_SCRAPER"
    SYNTHETIC = "SYNTHETIC"


class TrustLevel(str, Enum):
    VERIFIED_HIGH_TRUST = "VERIFIED_HIGH_TRUST"
    VERIFIED_MODERATE_TRUST = "VERIFIED_MODERATE_TRUST"
    UNVERIFIED_ACCEPTABLE = "UNVERIFIED_ACCEPTABLE"
    UNVERIFIED_LOW_TRUST = "UNVERIFIED_LOW_TRUST"
    UNTRUSTED = "UNTRUSTED"


class ConflictSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SourceTier(str, Enum):
    TIER_1_PRIMARY_OFFICIAL = "TIER_1_PRIMARY_OFFICIAL"
    TIER_2_REGULATORY = "TIER_2_REGULATORY"
    TIER_3_LICENSED = "TIER_3_LICENSED"
    TIER_4_SECONDARY = "TIER_4_SECONDARY"
    TIER_5_UNVERIFIED = "TIER_5_UNVERIFIED"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PROVISIONAL = "PROVISIONAL"
    UNVERIFIED = "UNVERIFIED"
    CONFLICTED = "CONFLICTED"


class DataQuality(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INVALID = "INVALID"


class DataSource(BaseModel):
    provider_name: str
    source_tier: SourceTier
    authority: str
    subscription_required: bool
    authentication_required: bool
    provider_version: str


class ProvenanceRecord(BaseModel):
    metric: str
    symbol: str
    value: float
    unit: str
    currency: str
    source: DataSource
    verification_status: VerificationStatus
    quality: DataQuality
    observed_at: datetime
    retrieved_at: datetime
    publication_time: datetime
    effective_time: datetime
    period: str
    context_id: str
    adjusted: bool


class DataConflict(BaseModel):
    metric: str
    symbol: str
    source_a: str
    value_a: float
    source_b: str
    value_b: float
    timestamp_a: datetime
    timestamp_b: datetime
    absolute_difference: float
    percentage_difference: float
    resolution: str
    resolution_reason: str


class SourceAttribution(BaseModel):
    provider_name: str
    provider_type: ProviderType
    quality_tier: DataQualityTier
    trust_level: TrustLevel
    attribution_notes: Optional[str] = None


class MetricProvenance(BaseModel):
    metric_name: str
    metric_value: Any
    provider: str
    provider_timestamp: datetime
    ingestion_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    quality_tier: DataQualityTier
    trust_score: float = Field(ge=0.0, le=1.0)
    source_attribution: Optional[SourceAttribution] = None


class DocumentType(str, Enum):
    ANNUAL_REPORT = "ANNUAL_REPORT"
    QUARTERLY_RESULT = "QUARTERLY_RESULT"
    EARNINGS_RELEASE = "EARNINGS_RELEASE"
    INVESTOR_PRESENTATION = "INVESTOR_PRESENTATION"
    CORPORATE_ANNOUNCEMENT = "CORPORATE_ANNOUNCEMENT"
    REGULATORY_FILING = "REGULATORY_FILING"
    OTHER = "OTHER"

class PeriodType(str, Enum):
    FY = "FY"
    QUARTER = "QUARTER"
    TTM = "TTM"
    MRQ = "MRQ"

class DataFreshness(str, Enum):
    FRESH = "FRESH"
    RECENT = "RECENT"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"

class FinancialObservation(BaseModel):
    symbol: str
    metric: str
    value: float
    unit: str
    currency: str
    period: str
    period_type: PeriodType
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    report_date: Optional[datetime] = None
    publication_time: Optional[datetime] = None
    effective_time: Optional[datetime] = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str
    source_tier: SourceTier
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    quality: DataQuality = DataQuality.LOW
    context_id: str
    document_id: Optional[str] = None
    document_reference: Optional[str] = None
    calculation_method: str = "DIRECT"

class QuarterlyStatement(BaseModel):
    """
    Structured multi-quarter financial statement record.
    Supports 4-8 quarters of historical disclosures with explicit nullability and PIT timestamps.
    """
    symbol: str
    period_end_date: datetime
    fiscal_period: str = "Q1"  # Q1, Q2, Q3, Q4
    fiscal_year: int = 2024
    filing_date: Optional[datetime] = None
    publication_time: Optional[datetime] = None

    # Income Statement
    revenue: Optional[float] = None
    operating_profit: Optional[float] = None
    operating_margin: Optional[float] = None
    ebitda: Optional[float] = None
    net_income: Optional[float] = None
    eps: Optional[float] = None

    # Balance Sheet
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    total_equity: Optional[float] = None
    cash: Optional[float] = None
    total_debt: Optional[float] = None

    # Cash Flow
    operating_cash_flow: Optional[float] = None
    investing_cash_flow: Optional[float] = None
    financing_cash_flow: Optional[float] = None
    free_cash_flow: Optional[float] = None

    # Provenance
    source: str = "yfinance"
    source_tier: SourceTier = SourceTier.TIER_4_SECONDARY
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class CorporateDocument(BaseModel):
    document_id: str
    symbol: str
    company_name: str
    document_type: DocumentType
    title: str
    source: str
    source_tier: SourceTier
    publication_time: Optional[datetime] = None
    period: str
    period_end: Optional[datetime] = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reference: Optional[str] = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    quality: DataQuality = DataQuality.LOW
    context_id: Optional[str] = None
    file_path: Optional[str] = None
    file_hash: Optional[str] = None

class DataConflictRecord(BaseModel):
    field_name: str
    conflict_severity: ConflictSeverity
    conflicting_values: List[Any]
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolution_strategy: str
    resolved_value: Any


class CorporateActionType(str, Enum):
    DIVIDEND = "DIVIDEND"
    SPLIT = "SPLIT"
    BONUS = "BONUS"
    RIGHTS_ISSUE = "RIGHTS_ISSUE"
    BUYBACK = "BUYBACK"
    MERGER = "MERGER"
    DEMERGER = "DEMERGER"
    DELISTING = "DELISTING"
    OTHER = "OTHER"

class CorporateAction(BaseModel):
    """
    Canonical corporate action model for dividends, splits, bonus issues, buybacks, rights, etc.
    Supports precise PIT dates, ratio/amount, provenance, and source tiering.
    """
    symbol: str
    isin: Optional[str] = None
    event_type: CorporateActionType
    announcement_date: Optional[datetime] = None
    ex_date: Optional[datetime] = None
    record_date: Optional[datetime] = None
    effective_date: Optional[datetime] = None
    payment_date: Optional[datetime] = None
    ratio_or_amount: Optional[float] = None
    ratio_text: Optional[str] = None
    currency: str = "INR"
    description: Optional[str] = None
    source: str = "yfinance"
    source_tier: SourceTier = SourceTier.TIER_4_SECONDARY
    publication_time: Optional[datetime] = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    quality: DataQuality = DataQuality.MEDIUM
    context_id: Optional[str] = None
    document_reference: Optional[str] = None
    raw_data: Dict[str, Any] = Field(default_factory=dict)

class InvestorType(str, Enum):
    FII = "FII"
    FPI = "FPI"
    DII = "DII"
    MUTUAL_FUND = "MUTUAL_FUND"
    INSURANCE = "INSURANCE"
    BANK = "BANK"
    OTHER_INSTITUTION = "OTHER_INSTITUTION"
    UNKNOWN = "UNKNOWN"

class HolderType(str, Enum):
    PROMOTER = "PROMOTER"
    PROMOTER_GROUP = "PROMOTER_GROUP"
    FII = "FII"
    DII = "DII"
    MUTUAL_FUND = "MUTUAL_FUND"
    PUBLIC = "PUBLIC"
    OTHER_INSTITUTION = "OTHER_INSTITUTION"
    UNKNOWN = "UNKNOWN"

class DealType(str, Enum):
    BULK = "BULK"
    BLOCK = "BLOCK"
    OTHER = "OTHER"

class InstitutionalFlowObservation(BaseModel):
    symbol: str
    investor_type: InvestorType
    buy_value: float
    sell_value: float
    net_value: float
    buy_quantity: Optional[float] = None
    sell_quantity: Optional[float] = None
    net_quantity: Optional[float] = None
    currency: str
    exchange: str
    period: str
    observed_at: datetime
    publication_time: Optional[datetime] = None
    effective_time: Optional[datetime] = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str
    source_tier: SourceTier
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    quality: DataQuality = DataQuality.LOW
    context_id: str
    document_reference: Optional[str] = None

class OwnershipObservation(BaseModel):
    symbol: str
    holder_type: HolderType
    ownership_percentage: float = Field(ge=0.0, le=100.0)
    shares_held: Optional[float] = None
    pledged_percentage: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    period: str
    report_date: Optional[datetime] = None
    publication_time: Optional[datetime] = None
    effective_time: Optional[datetime] = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str
    source_tier: SourceTier
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    quality: DataQuality = DataQuality.LOW
    context_id: str
    document_reference: Optional[str] = None

class InstitutionalDeal(BaseModel):
    symbol: str
    exchange: str
    deal_type: DealType
    participant: str
    buy_sell: str
    quantity: float
    price: float
    value: float
    trade_date: datetime
    publication_time: Optional[datetime] = None
    source: str
    source_tier: SourceTier
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    quality: DataQuality = DataQuality.LOW
    context_id: str
    document_reference: Optional[str] = None

class DeliveryObservation(BaseModel):
    symbol: str
    trade_date: datetime
    traded_quantity: float = Field(ge=0.0)
    delivery_quantity: float = Field(ge=0.0)
    delivery_percentage: float = Field(ge=0.0, le=100.0)
    source: str
    source_tier: SourceTier
    observed_at: datetime
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    quality: DataQuality = DataQuality.LOW
    context_id: str

class MarketContext(BaseModel):
    model_config = {"frozen": True}


    context_id: str
    symbol: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data_timestamp: datetime
    provider: str
    is_cached: bool = False

    # Phase 20 - Snapshot Integrity
    snapshot_id: str = Field(default="")
    freshness_status: SnapshotFreshness = Field(default=SnapshotFreshness.MISSING)
    completeness_status: str = Field(default="UNKNOWN")
    cache_hit: bool = Field(default=False)
    
    historical_window: HistoricalWindow = HistoricalWindow.RECENT

    # Data Provenance fields
    source_provider: str = Field(default="UNKNOWN")
    source_timestamp: Optional[datetime] = None
    provider_priority: int = Field(default=99)
    data_quality_tier: Optional[DataQualityTier] = None
    trust_score: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    conflicts: List[Any] = Field(default_factory=list) # Relaxed to Any to support both old and new DataConflict
    provenance_records: Dict[str, Any] = Field(default_factory=dict) # Relaxed to Any to support both MetricProvenance and ProvenanceRecord
    provenance: List[Any] = Field(default_factory=list)
    quality_summary: Dict[str, Any] = Field(default_factory=dict)

    current_price: float
    ohlcv_historical: List[Dict[str, Any]] = Field(default_factory=list)
    technical_indicators: Dict[str, Any] = Field(default_factory=dict)
    fundamental_data: Dict[str, Any] = Field(default_factory=dict)
    quarterly_fundamentals: List[QuarterlyStatement] = Field(default_factory=list)
    corporate_actions: List[CorporateAction] = Field(default_factory=list)
    corporate_documents: List[Any] = Field(default_factory=list) # List of CorporateDocument
    sector_data: Dict[str, Any] = Field(default_factory=dict)
    macro_data: Dict[str, Any] = Field(default_factory=dict)
    news_data: Dict[str, Any] = Field(default_factory=dict)
    institutional_data: List[InstitutionalFlowObservation] = Field(default_factory=list)
    ownership_data: List[OwnershipObservation] = Field(default_factory=list)
    deal_data: List[InstitutionalDeal] = Field(default_factory=list)
    delivery_data: List[DeliveryObservation] = Field(default_factory=list)

    quality_status: DataQualityStatus = DataQualityStatus.OK
    warnings: List[str] = Field(default_factory=list)



# ── Technical Specialist Schemas ─────────────────────────────────────────────

class TrendDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class SetupType(str, Enum):
    BREAKOUT = "BREAKOUT"
    PULLBACK = "PULLBACK"
    REVERSAL = "REVERSAL"
    CONSOLIDATION = "CONSOLIDATION"
    NONE = "NONE"


class TechnicalIndicatorEvidence(BaseModel):
    """Single deterministic indicator snapshot used as LLM evidence."""
    name: str = Field(description="Indicator name, e.g. 'EMA20'")
    value: float = Field(description="Exact numeric value from MarketContext")
    interpretation: str = Field(
        description="AI-supplied qualitative interpretation (not the numeric value)"
    )


class TechnicalPayload(BaseModel):
    """
    Strongly-typed specialist output embedded in AgentOutput.raw_data.

    Deterministic fields (trend, score, confirmation) are populated by
    the specialist from LLM-parsed JSON.

    Indicator evidence values MUST originate from MarketContext —
    the LLM interprets them; it does not calculate or replace them.
    """
    trend: TrendDirection = Field(description="Overall price trend direction")
    setup: SetupType = Field(description="Identified technical trading setup")
    technical_score: float = Field(
        ge=1.0, le=10.0,
        description="Conviction score 1–10 based on technical alignment",
    )
    confirmation: bool = Field(
        description="True when indicators collectively confirm a tradeable setup"
    )
    evidence: List[TechnicalIndicatorEvidence] = Field(
        default_factory=list,
        description="Deterministic indicator snapshots used as LLM evidence",
    )
    invalidation_conditions: List[str] = Field(
        default_factory=list,
        description="Conditions that would invalidate this technical thesis",
    )
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)


# ── LLM-parsed response model (internal to TechnicalSpecialist) ──────────────

class _TechnicalLLMResponse(BaseModel):
    """
    The exact JSON structure the LLM must return.
    Only contains interpretation/judgment — no computed numbers.
    """
    trend: TrendDirection
    setup: SetupType
    technical_score: float = Field(ge=1.0, le=10.0)
    confirmation: bool
    conclusion: str = Field(description="One-sentence technical thesis")
    invalidation_conditions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Model self-assessed confidence (0.0–1.0)",
    )


# ── Momentum Specialist Schemas ─────────────────────────────────────────────

class MomentumDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class MomentumStrength(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"


class MomentumIndicatorEvidence(BaseModel):
    """Single deterministic momentum indicator snapshot used as LLM evidence."""
    name: str = Field(description="Indicator name, e.g. 'RSI14', 'EMA_Spread'")
    value: Optional[float] = Field(
        default=None,
        description="Exact numeric value from MarketContext (None if unavailable)"
    )
    available: bool = Field(
        default=True,
        description="True if the indicator was present in MarketContext"
    )
    interpretation: str = Field(
        description="Deterministic factual interpretation based on exact numbers"
    )


class MomentumPayload(BaseModel):
    """
    Strongly-typed specialist output embedded in AgentOutput.raw_data for MomentumSpecialist.
    """
    momentum_direction: MomentumDirection = Field(
        description="Overall momentum direction"
    )
    momentum_strength: MomentumStrength = Field(
        description="Assessment of momentum velocity and strength"
    )
    confirmation: bool = Field(
        description="True when momentum indicators align with directional thesis"
    )
    evidence: List[MomentumIndicatorEvidence] = Field(
        default_factory=list,
        description="Deterministic momentum indicator snapshots"
    )
    invalidation_conditions: List[str] = Field(
        default_factory=list,
        description="Conditions that would invalidate this momentum thesis"
    )
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)


# ── LLM-parsed response model (internal to MomentumSpecialist) ──────────────

class _MomentumLLMResponse(BaseModel):
    """
    The exact JSON structure the LLM must return for Momentum analysis.
    Only contains interpretation/judgment — no computed numbers.
    """
    momentum_direction: MomentumDirection
    momentum_strength: MomentumStrength
    confirmation: bool
    conclusion: str = Field(description="One-sentence momentum thesis")
    invalidation_conditions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Model self-assessed confidence (0.0–1.0)"
    )




# ── Quant Specialist Schemas ──────────────────────────────────────────────────

class QuantStatisticalRegime(str, Enum):
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    NORMAL_VOLATILITY = "NORMAL_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    TREND_CONSISTENT = "TREND_CONSISTENT"
    TRENDING_NOISY = "TRENDING_NOISY"
    MEAN_REVERTING = "MEAN_REVERTING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class QuantRiskCharacterization(str, Enum):
    ELEVATED = "ELEVATED"
    MODERATE = "MODERATE"
    SUBDUED = "SUBDUED"
    INDETERMINATE = "INDETERMINATE"


class QuantMetricRecord(BaseModel):
    """
    Typed record for a single quantitative metric with full provenance.

    Values originate exclusively from Python calculation against MarketContext.
    The LLM may never alter the `value` field.
    """
    metric_name: str = Field(description="Canonical metric identifier")
    value: Optional[float] = Field(
        default=None,
        description="Calculated value (None if unavailable)"
    )
    unit: str = Field(description="Unit of measurement, e.g. 'annualized_%', 'ratio'")
    window: str = Field(description="Observation window, e.g. '5D', 'N/A'")
    available: bool = Field(description="True if metric was successfully computed")
    unavailable_reason: str = Field(
        default="",
        description="Explanation when available=False"
    )
    source: str = Field(description="Data source used for calculation")
    calculation_method: str = Field(description="Formula description")
    data_timestamp: str = Field(description="ISO timestamp of latest observation used")


class QuantPayload(BaseModel):
    """
    Strongly-typed specialist output for QuantSpecialist embedded in AgentOutput.raw_data.

    Numeric metrics are sourced entirely from Python calculation.
    The LLM contributes only qualitative classification fields.
    """
    statistical_regime: QuantStatisticalRegime = Field(
        description="LLM-assigned quantitative regime classification"
    )
    risk_characterization: QuantRiskCharacterization = Field(
        description="LLM-assigned risk profile"
    )
    anomaly_detected: bool = Field(
        description="True if statistical evidence suggests anomalous behavior"
    )
    statistical_strength: float = Field(
        ge=0.0, le=1.0,
        description="LLM-assigned strength of statistical evidence (0.0–1.0)"
    )
    metrics: List[QuantMetricRecord] = Field(
        default_factory=list,
        description="Deterministic quantitative metric records with provenance"
    )
    invalidation_conditions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)


# ── LLM-parsed response model (internal to QuantSpecialist) ──────────────────

class _QuantLLMResponse(BaseModel):
    """
    The exact JSON structure the LLM must return for Quant analysis.

    Contains ONLY interpretation and classification — no computed numbers.
    All numeric values are supplied via the prompt from Python calculations.
    """
    statistical_regime: QuantStatisticalRegime
    risk_characterization: QuantRiskCharacterization
    anomaly_detected: bool
    statistical_strength: float = Field(ge=0.0, le=1.0)
    conclusion: str = Field(description="One-sentence quantitative thesis")
    invalidation_conditions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Model self-assessed confidence (0.0–1.0)"
    )
# ── Fundamental Specialist Schemas ───────────────────────────────────────────

class FundamentalQuality(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    DISTRESSED = "DISTRESSED"
    INDETERMINATE = "INDETERMINATE"


class GrowthAssessment(str, Enum):
    HIGH_GROWTH = "HIGH_GROWTH"
    MODERATE_GROWTH = "MODERATE_GROWTH"
    STAGNANT = "STAGNANT"
    CONTRACTING = "CONTRACTING"
    INDETERMINATE = "INDETERMINATE"


class ProfitabilityAssessment(str, Enum):
    HIGHLY_PROFITABLE = "HIGHLY_PROFITABLE"
    MODERATE_PROFITABILITY = "MODERATE_PROFITABILITY"
    LOW_PROFITABILITY = "LOW_PROFITABILITY"
    UNPROFITABLE = "UNPROFITABLE"
    INDETERMINATE = "INDETERMINATE"


class BalanceSheetAssessment(str, Enum):
    PRISTINE = "PRISTINE"
    HEALTHY = "HEALTHY"
    LEVERAGED = "LEVERAGED"
    DISTRESSED = "DISTRESSED"
    INDETERMINATE = "INDETERMINATE"


class FundamentalMetricRecord(BaseModel):
    """
    Typed record for a single fundamental financial metric with full provenance.
    Values originate exclusively from verified structured data and Python calculations.
    """
    metric_name: str = Field(description="Canonical metric identifier, e.g. 'net_margin', 'revenue'")
    value: Optional[float] = Field(
        default=None,
        description="Calculated or reported numeric value (None if unavailable)"
    )
    unit: str = Field(description="Unit of measurement, e.g. '%', 'currency', 'ratio', 'shares'")
    period: str = Field(
        default="TTM",
        description="Reporting period, e.g. 'TTM', 'FY2023', 'Q3-2023', 'N/A'"
    )
    report_date: Optional[str] = Field(
        default=None,
        description="Filing or reporting date of the financial observation (ISO formatted)"
    )
    available: bool = Field(description="True if metric was successfully computed or retrieved")
    unavailable_reason: str = Field(
        default="",
        description="Explanation when available=False"
    )
    source: str = Field(description="Data source used, e.g. 'income_statement', 'balance_sheet'")
    calculation_method: str = Field(description="Formula or retrieval method description")
    data_timestamp: str = Field(description="ISO timestamp of observation")


class FundamentalPayload(BaseModel):
    """
    Strongly-typed specialist output for FundamentalSpecialist embedded in AgentOutput.raw_data.
    Numeric metrics are sourced entirely from structured fundamental data or Python calculations.
    The LLM contributes only qualitative assessments and thesis synthesis.
    """
    fundamental_quality: FundamentalQuality = Field(
        description="Overall fundamental business quality assessment"
    )
    growth_assessment: GrowthAssessment = Field(
        description="Top-line and bottom-line expansion assessment"
    )
    profitability_assessment: ProfitabilityAssessment = Field(
        description="Margin and earnings efficiency assessment"
    )
    balance_sheet_assessment: BalanceSheetAssessment = Field(
        description="Solvency, leverage, and liquidity assessment"
    )
    financial_strength: float = Field(
        ge=0.0, le=1.0,
        description="Overall financial health score (0.0–1.0)"
    )
    reporting_period: str = Field(
        default="TTM",
        description="Dominant financial reporting period represented"
    )
    data_freshness_status: str = Field(
        default="FRESH",
        description="Data freshness flag ('FRESH', 'STALE', 'UNAVAILABLE')"
    )
    metrics: List[FundamentalMetricRecord] = Field(
        default_factory=list,
        description="Deterministic fundamental metric records with complete provenance"
    )
    invalidation_conditions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)


class _FundamentalLLMResponse(BaseModel):
    """
    The exact JSON structure the LLM must return for Fundamental analysis.
    Contains ONLY interpretation and classification — no computed numbers.
    All numeric values are supplied via the prompt from verified data / Python calculations.
    """
    fundamental_quality: FundamentalQuality
    growth_assessment: GrowthAssessment
    profitability_assessment: ProfitabilityAssessment
    balance_sheet_assessment: BalanceSheetAssessment
    financial_strength: float = Field(ge=0.0, le=1.0)
    conclusion: str = Field(description="One-sentence fundamental investment thesis")
    invalidation_conditions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Model self-assessed confidence (0.0–1.0)"
    )


# ── Valuation Specialist Schemas ─────────────────────────────────────────────

class ValuationStatus(str, Enum):
    UNDERVALUED = "UNDERVALUED"
    FAIRLY_VALUED = "FAIRLY_VALUED"
    OVERVALUED = "OVERVALUED"
    INDETERMINATE = "INDETERMINATE"


class ValuationPremiumDiscount(str, Enum):
    SIGNIFICANT_PREMIUM = "SIGNIFICANT_PREMIUM"
    MODERATE_PREMIUM = "MODERATE_PREMIUM"
    FAIR_VALUE = "FAIR_VALUE"
    MODERATE_DISCOUNT = "MODERATE_DISCOUNT"
    SIGNIFICANT_DISCOUNT = "SIGNIFICANT_DISCOUNT"
    INDETERMINATE = "INDETERMINATE"


class ValuationConfidence(str, Enum):
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    INDETERMINATE = "INDETERMINATE"


class ValuationMetricRecord(BaseModel):
    """
    Typed record for a single valuation metric with full provenance.
    All values originate exclusively from Python calculations against MarketContext data.
    The LLM never computes, alters, or invents any value in this record.
    """
    metric_name: str = Field(
        description="Canonical metric identifier, e.g. 'pe_ratio', 'ev_ebitda'"
    )
    value: Optional[float] = Field(
        default=None,
        description="Calculated numeric value (None if unavailable)"
    )
    unit: str = Field(
        description="Unit of measurement, e.g. 'x' (multiple), '%' (yield), 'ratio'"
    )
    method: str = Field(
        description="Valuation method name, e.g. 'Price-to-Earnings (P/E)'"
    )
    formula: str = Field(
        description="Exact formula used to compute the value"
    )
    inputs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Named inputs used in the formula with their exact values"
    )
    available: bool = Field(
        description="True if the metric was successfully computed"
    )
    unavailable_reason: str = Field(
        default="",
        description="Explanation when available=False"
    )
    assumptions: List[str] = Field(
        default_factory=list,
        description="Explicit assumptions made during this calculation"
    )
    context_id: str = Field(
        description="MarketContext context_id this metric was derived from"
    )
    data_timestamp: str = Field(
        description="ISO timestamp of the MarketContext data observation"
    )


class ValuationPayload(BaseModel):
    """
    Strongly-typed specialist output for ValuationSpecialist embedded in AgentOutput.raw_data.
    Numeric multiples are computed entirely in Python from MarketContext.
    The LLM contributes only qualitative valuation assessment and thesis synthesis.
    """
    valuation_status: ValuationStatus = Field(
        description="Overall valuation status assessment"
    )
    premium_discount_assessment: ValuationPremiumDiscount = Field(
        description="Premium or discount relative to intrinsic or sector value"
    )
    valuation_strength: float = Field(
        ge=0.0, le=1.0,
        description="Composite score supporting the thesis (0.0–1.0)"
    )
    methods_used: List[str] = Field(
        default_factory=list,
        description="List of valuation method names that produced available results"
    )
    relative_valuation: Dict[str, Any] = Field(
        default_factory=dict,
        description="Per-method relative valuation multiples (P/E, P/S, P/B, EV/EBITDA, PEG)"
    )
    absolute_valuation: Dict[str, Any] = Field(
        default_factory=dict,
        description="Absolute valuation estimates (FCF Yield, any yield-based measures)"
    )
    evidence: List[ValuationMetricRecord] = Field(
        default_factory=list,
        description="Deterministic valuation metric records with complete provenance"
    )
    invalidation_conditions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    conclusion: str = Field(
        default="",
        description="One-sentence valuation thesis"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        default=0.0,
        description="Model self-assessed confidence in valuation conclusion (0.0–1.0)"
    )


class _ValuationLLMResponse(BaseModel):
    """
    The exact JSON structure the LLM must return for Valuation analysis.
    Contains ONLY interpretation and classification — no computed numbers.
    All numeric multiples are supplied via the prompt from Python calculations.
    """
    valuation_status: ValuationStatus = Field(
        description="Overall valuation classification based on available multiples"
    )
    premium_discount_assessment: ValuationPremiumDiscount = Field(
        description="Qualitative premium/discount assessment vs fair value"
    )
    valuation_strength: float = Field(
        ge=0.0, le=1.0,
        description="Composite conviction score for the valuation conclusion (0.0–1.0)"
    )
    conclusion: str = Field(
        description="One-sentence valuation investment thesis"
    )
    invalidation_conditions: List[str] = Field(
        default_factory=list,
        description="Conditions that would invalidate this valuation thesis"
    )
    risks: List[str] = Field(
        default_factory=list,
        description="Key valuation risks (e.g., multiple expansion/compression, earnings miss)"
    )
    assumptions: List[str] = Field(
        default_factory=list,
        description="Assumptions underlying the valuation assessment"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Model self-assessed confidence in this valuation analysis (0.0–1.0)"
    )


# ── Sector Specialist Schemas ───────────────────────────────────────────────

class SectorRegime(str, Enum):
    STRONG_OUTPERFORMING = "STRONG_OUTPERFORMING"
    MODERATE_OUTPERFORMING = "MODERATE_OUTPERFORMING"
    NEUTRAL = "NEUTRAL"
    UNDERPERFORMING = "UNDERPERFORMING"
    LAGGING = "LAGGING"
    INDETERMINATE = "INDETERMINATE"


class SectorAttractiveness(str, Enum):
    HIGHLY_ATTRACTIVE = "HIGHLY_ATTRACTIVE"
    ATTRACTIVE = "ATTRACTIVE"
    NEUTRAL = "NEUTRAL"
    UNATTRACTIVE = "UNATTRACTIVE"
    HIGHLY_UNATTRACTIVE = "HIGHLY_UNATTRACTIVE"
    INDETERMINATE = "INDETERMINATE"


class CyclicalityCategory(str, Enum):
    CYCLICAL = "CYCLICAL"
    DEFENSIVE = "DEFENSIVE"
    GROWTH = "GROWTH"
    SENSITIVE = "SENSITIVE"
    INDETERMINATE = "INDETERMINATE"


class RelativeStrengthRank(str, Enum):
    LEADER = "LEADER"
    OUTPERFORMER = "OUTPERFORMER"
    IN_LINE = "IN_LINE"
    UNDERPERFORMER = "UNDERPERFORMER"
    LAGGARD = "LAGGARD"
    INDETERMINATE = "INDETERMINATE"


class SectorMetricRecord(BaseModel):
    """
    Typed record for a single sector or relative performance metric with full provenance.
    Values originate exclusively from Python calculations and verified data.
    The LLM never calculates or alters numeric values in this record.
    """
    metric_name: str = Field(
        description="Canonical metric identifier, e.g. 'company_return', 'sector_return', 'relative_to_sector'"
    )
    value: Optional[float] = Field(
        default=None,
        description="Calculated or observed numeric percentage return/spread (None if unavailable)"
    )
    unit: str = Field(
        default="%",
        description="Unit of measurement, e.g. '%', 'bps', 'rank'"
    )
    period: str = Field(
        default="RECENT",
        description="Observation window or reporting period, e.g. 'RECENT', '5D', '60D'"
    )
    source: str = Field(
        description="Data source used, e.g. 'ohlcv_historical', 'sector_data'"
    )
    calculation_method: str = Field(
        description="Formula or extraction method description"
    )
    inputs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Named inputs with exact numeric values used in calculation"
    )
    available: bool = Field(
        description="True if metric was successfully computed or retrieved"
    )
    unavailable_reason: str = Field(
        default="",
        description="Explanation when available=False"
    )
    context_id: str = Field(
        description="MarketContext context_id this metric was derived from"
    )
    data_timestamp: str = Field(
        description="ISO timestamp of observation"
    )


class SectorPayload(BaseModel):
    """
    Strongly-typed specialist output for SectorSpecialist embedded in AgentOutput.raw_data.
    Numeric performance metrics and spreads are computed entirely in Python.
    The LLM contributes only qualitative classification, headwinds/tailwinds, and thesis synthesis.
    """
    sector: str = Field(
        default="UNKNOWN",
        description="Broad economic sector classification"
    )
    industry: str = Field(
        default="UNKNOWN",
        description="Specific industry group classification"
    )
    sector_regime: SectorRegime = Field(
        description="Overall sector performance regime vs benchmark"
    )
    sector_attractiveness: SectorAttractiveness = Field(
        description="Qualitative sector environment attractiveness"
    )
    cyclicality: CyclicalityCategory = Field(
        description="Sector economic sensitivity classification"
    )
    relative_strength_rank: RelativeStrengthRank = Field(
        description="Company relative strength positioning vs sector"
    )
    sector_score: float = Field(
        ge=0.0, le=1.0,
        description="Composite sector favorability score (0.0–1.0)"
    )
    relative_performance: Dict[str, Any] = Field(
        default_factory=dict,
        description="Deterministic relative performance spreads (e.g., vs sector, vs benchmark)"
    )
    tailwinds: List[str] = Field(
        default_factory=list,
        description="Sector-wide tailwinds supported by evidence or clear assumptions"
    )
    headwinds: List[str] = Field(
        default_factory=list,
        description="Sector-wide headwinds supported by evidence or clear assumptions"
    )
    evidence: List[SectorMetricRecord] = Field(
        default_factory=list,
        description="Deterministic sector metric records with complete provenance"
    )
    invalidation_conditions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    conclusion: str = Field(
        default="",
        description="One-sentence sector thesis"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        default=0.0,
        description="Model self-assessed confidence in sector analysis (0.0–1.0)"
    )


class _SectorLLMResponse(BaseModel):
    """
    The exact JSON structure the LLM must return for Sector analysis.
    Contains ONLY interpretation and classification — no computed numbers.
    All numeric returns and spreads are supplied via the prompt from Python calculations.
    """
    sector_regime: SectorRegime = Field(
        description="Sector performance regime classification"
    )
    sector_attractiveness: SectorAttractiveness = Field(
        description="Sector favorability / attractiveness classification"
    )
    cyclicality: CyclicalityCategory = Field(
        description="Economic cyclicality classification"
    )
    relative_strength_rank: RelativeStrengthRank = Field(
        description="Company positioning rank relative to its sector"
    )
    sector_score: float = Field(
        ge=0.0, le=1.0,
        description="Composite sector score (0.0–1.0)"
    )
    conclusion: str = Field(
        description="One-sentence sector investment thesis"
    )
    tailwinds: List[str] = Field(
        default_factory=list,
        description="Key sector tailwinds"
    )
    headwinds: List[str] = Field(
        default_factory=list,
        description="Key sector headwinds"
    )
    invalidation_conditions: List[str] = Field(
        default_factory=list,
        description="Conditions that would invalidate this sector thesis"
    )
    risks: List[str] = Field(
        default_factory=list,
        description="Key sector-specific risks"
    )
    assumptions: List[str] = Field(
        default_factory=list,
        description="Assumptions underlying this sector assessment"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Model self-assessed confidence (0.0–1.0)"
    )


# ── Macro Specialist Schemas ────────────────────────────────────────────────

class MacroRegime(str, Enum):
    EXPANSIONARY = "EXPANSIONARY"
    NEUTRAL = "NEUTRAL"
    CONTRACTIONARY = "CONTRACTIONARY"
    RESTRICTIVE = "RESTRICTIVE"
    TRANSITIONAL = "TRANSITIONAL"
    INDETERMINATE = "INDETERMINATE"


class MacroRisk(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"
    INDETERMINATE = "INDETERMINATE"


class RateRegime(str, Enum):
    HIKING = "HIKING"
    CUTTING = "CUTTING"
    HOLDING = "HOLDING"
    INDETERMINATE = "INDETERMINATE"


class InflationRegime(str, Enum):
    ACCELERATING = "ACCELERATING"
    DECELERATING = "DECELERATING"
    STABLE = "STABLE"
    DEFLATIONARY = "DEFLATIONARY"
    INDETERMINATE = "INDETERMINATE"


class MacroMetricRecord(BaseModel):
    """
    Typed record for a single deterministic macro metric (fact or pure calculation).
    """
    metric_name: str = Field(description="Canonical metric identifier, e.g. 'policy_rate', '10y_2y_spread'")
    value: Optional[float] = Field(default=None, description="Calculated or observed numeric value")
    unit: str = Field(description="Unit, e.g. '%', 'bps', 'USD'")
    period: str = Field(description="Observation frequency or reporting period (e.g. 'monthly', 'current')")
    source: str = Field(description="Data source, e.g. 'macro_data'")
    calculation_method: str = Field(description="Formula or extraction method")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Named inputs with exact values")
    available: bool = Field(description="True if successfully computed/retrieved")
    unavailable_reason: str = Field(default="", description="Reason when available=False")
    context_id: str = Field(description="Context ID")
    data_timestamp: str = Field(description="ISO timestamp of this macro observation")


class MacroPayload(BaseModel):
    """
    Specialist output for MacroSpecialist embedded in AgentOutput.raw_data.
    Numeric values are strictly from Python calculator.
    LLM contributes regime classification, headwinds/tailwinds, and thesis.
    """
    macro_regime: MacroRegime
    macro_risk: MacroRisk
    rate_regime: RateRegime
    inflation_regime: InflationRegime
    asset_impact: str = Field(description="How the macro environment impacts the target asset class/sector")
    company_sensitivity: str = Field(description="Specific sensitivity of this company to current macro factors")
    evidence: List[MacroMetricRecord] = Field(default_factory=list)
    tailwinds: List[str] = Field(default_factory=list)
    headwinds: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    conclusion: str = Field(description="One-sentence macro investment thesis")
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class _MacroLLMResponse(BaseModel):
    """
    JSON structure returned by the LLM for Macro analysis.
    NO computed numbers here.
    """
    macro_regime: MacroRegime
    macro_risk: MacroRisk
    rate_regime: RateRegime
    inflation_regime: InflationRegime
    asset_impact: str
    company_sensitivity: str
    conclusion: str
    tailwinds: List[str]
    headwinds: List[str]
    invalidation_conditions: List[str]
    risks: List[str]
    assumptions: List[str]
    confidence: float = Field(ge=0.0, le=1.0)


# ── News & Sentiment Specialist Schemas ─────────────────────────────────────

class NewsRegime(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"
    INDETERMINATE = "INDETERMINATE"


class NewsSentiment(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"
    UNCERTAIN = "UNCERTAIN"
    INDETERMINATE = "INDETERMINATE"


class NewsEventType(str, Enum):
    EARNINGS = "EARNINGS"
    GUIDANCE = "GUIDANCE"
    MANAGEMENT = "MANAGEMENT"
    REGULATORY = "REGULATORY"
    LEGAL = "LEGAL"
    M_AND_A = "M_AND_A"
    PRODUCT = "PRODUCT"
    CONTRACT = "CONTRACT"
    CAPEX = "CAPEX"
    FINANCING = "FINANCING"
    RATING = "RATING"
    MACRO = "MACRO"
    SECTOR = "SECTOR"
    GOVERNMENT = "GOVERNMENT"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class NewsRecency(str, Enum):
    VERY_RECENT = "VERY_RECENT"
    RECENT = "RECENT"
    OLDER = "OLDER"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class NewsImportance(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class NewsSourceQuality(str, Enum):
    OFFICIAL = "OFFICIAL"
    REGULATORY = "REGULATORY"
    REPUTABLE_MEDIA = "REPUTABLE_MEDIA"
    SECONDARY = "SECONDARY"
    UNKNOWN = "UNKNOWN"


class NewsArticleEvidence(BaseModel):
    """
    Typed record for a single normalized news article or corporate event.
    """
    headline: str = Field(description="Article headline or title")
    source: str = Field(description="Publisher or disclosure source")
    published_at: Optional[str] = Field(default=None, description="ISO timestamp of article publication")
    event_type: NewsEventType = Field(default=NewsEventType.UNKNOWN, description="Classified event category")
    importance: NewsImportance = Field(default=NewsImportance.UNKNOWN, description="Assessed importance level")
    summary: str = Field(default="", description="Concise article summary or key points")
    ticker_relevance: float = Field(default=1.0, ge=0.0, le=1.0, description="Relevance score to target ticker")
    source_quality: NewsSourceQuality = Field(default=NewsSourceQuality.UNKNOWN, description="Assessed credibility tier of source")
    recency: NewsRecency = Field(default=NewsRecency.UNKNOWN, description="Deterministic recency tier based on timestamp")
    is_duplicate: bool = Field(default=False, description="True if marked as duplicate of another event")
    duplicate_group_id: Optional[str] = Field(default=None, description="Group ID linking duplicate coverage of same event")
    data_timestamp: str = Field(description="ISO timestamp from MarketContext")
    context_id: str = Field(description="MarketContext ID for provenance tracking")


class NewsEvent(BaseModel):
    """
    Canonical news event model with explicit timestamps, source tiers, materiality,
    and deduplication metadata.
    """
    symbol: str
    isin: Optional[str] = None
    headline: str
    summary: str = ""
    publisher: str = "UNKNOWN"
    url: Optional[str] = None
    reference_id: Optional[str] = None
    publication_time: Optional[datetime] = None
    ingestion_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_category: NewsEventType = NewsEventType.OTHER
    materiality: NewsImportance = NewsImportance.MEDIUM
    materiality_score: float = 0.5
    source_tier: SourceTier = SourceTier.TIER_4_SECONDARY
    source: str = "yfinance"
    is_duplicate: bool = False
    duplicate_group_id: Optional[str] = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    quality: DataQuality = DataQuality.MEDIUM
    raw_data: Dict[str, Any] = Field(default_factory=dict)


class RegulatoryFiling(BaseModel):
    """
    Canonical regulatory disclosure/filing model (NSE/BSE/Corporate IR).
    """
    symbol: str
    isin: Optional[str] = None
    filing_type: DocumentType = DocumentType.REGULATORY_FILING
    title: str
    publication_time: datetime
    filing_id: Optional[str] = None
    source: str = "NSE_Official"
    source_tier: SourceTier = SourceTier.TIER_1_PRIMARY_OFFICIAL
    url: Optional[str] = None
    materiality: NewsImportance = NewsImportance.HIGH
    materiality_score: float = 0.8
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verification_status: VerificationStatus = VerificationStatus.VERIFIED
    quality: DataQuality = DataQuality.HIGH
    raw_data: Dict[str, Any] = Field(default_factory=dict)


class NewsPayload(BaseModel):
    """
    Specialist output for NewsSpecialist embedded in AgentOutput.raw_data.
    Numeric/count values are strictly from Python calculator.
    LLM contributes sentiment synthesis, catalysts, headwinds, and thesis.
    """
    news_regime: NewsRegime
    overall_sentiment: NewsSentiment
    total_articles: int = Field(ge=0, description="Total articles processed")
    unique_events_count: int = Field(ge=0, description="Count of distinct unique events after deduplication")
    high_importance_count: int = Field(ge=0, description="Count of high-importance non-duplicate events")
    recent_count: int = Field(ge=0, description="Count of recent (<= 72h) non-duplicate events")
    articles: List[NewsArticleEvidence] = Field(default_factory=list)
    catalysts: List[str] = Field(default_factory=list, description="Key positive catalysts identified")
    headwinds: List[str] = Field(default_factory=list, description="Key news-driven headwinds")
    risks: List[str] = Field(default_factory=list, description="Key news-specific risks")
    assumptions: List[str] = Field(default_factory=list, description="Assumptions underlying news analysis")
    invalidation_conditions: List[str] = Field(default_factory=list, description="Conditions that would invalidate thesis")
    conclusion: str = Field(description="One-sentence news/sentiment thesis")
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class _NewsLLMResponse(BaseModel):
    """
    JSON structure returned by the LLM for News & Sentiment analysis.
    NO computed or invented counts/dates here.
    """
    news_regime: NewsRegime
    overall_sentiment: NewsSentiment
    catalysts: List[str]
    headwinds: List[str]
    risks: List[str]
    assumptions: List[str]
    invalidation_conditions: List[str]
    conclusion: str
    confidence: float = Field(ge=0.0, le=1.0)


class AgentInput(BaseModel):
    symbol: str
    market_context: MarketContext
    additional_data: Dict[str, Any] = Field(default_factory=dict)


class FIIRegime(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"

class DIIRegime(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"

class InstitutionalRegime(str, Enum):
    ACCUMULATION = "ACCUMULATION"
    DISTRIBUTION = "DISTRIBUTION"
    MIXED = "MIXED"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"

class OwnershipRegime(str, Enum):
    IMPROVING = "IMPROVING"
    STABLE = "STABLE"
    DETERIORATING = "DETERIORATING"
    UNKNOWN = "UNKNOWN"

class PromoterRisk(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"

class InstitutionalStrength(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    UNKNOWN = "UNKNOWN"

class InstitutionalMetricRecord(BaseModel):
    metric_name: str
    value: Optional[float]
    unit: str
    period: str
    source: str
    source_tier: SourceTier
    verification_status: VerificationStatus
    calculation_method: str
    inputs: Dict[str, Any]
    context_id: str
    data_timestamp: str

class InstitutionalPayload(BaseModel):
    institutional_regime: InstitutionalRegime
    institutional_strength: InstitutionalStrength
    fii_regime: FIIRegime
    dii_regime: DIIRegime
    ownership_regime: OwnershipRegime
    promoter_risk: PromoterRisk

    fii_net_flow: Optional[float]
    dii_net_flow: Optional[float]
    combined_net_flow: Optional[float]

    promoter_ownership: Optional[float]
    promoter_ownership_change: Optional[float]
    promoter_pledge_percentage: Optional[float]

    delivery_percentage: Optional[float]
    delivery_trend: Optional[str]

    bulk_deal_count: int = 0
    block_deal_count: int = 0

    institutional_confirmation: bool = False

    evidence: List[InstitutionalMetricRecord] = Field(default_factory=list)

    catalysts: List[str] = Field(default_factory=list)
    headwinds: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)

    conclusion: str
    confidence: float = Field(ge=0.0, le=1.0)


class AgentEvidence(BaseModel):
    source: str
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentError(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


class AgentOutput(BaseModel):
    agent_name: str
    version: str
    model: str
    status: AgentState
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data_timestamp: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    conclusion: str
    evidence: List[AgentEvidence] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    error: Optional[AgentError] = None
    raw_data: Optional[Dict[str, Any]] = None


# ── Specialist Runtime Schemas ───────────────────────────────────────────────

class AgentExecutionRecord(BaseModel):
    """Per-agent execution trace attached to an aggregate run."""
    agent_name: str
    agent_version: str
    context_id: str
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    status: AgentState
    attempts: int = 1
    output: Optional[AgentOutput] = None
    error_message: Optional[str] = None


class SpecialistRunResult(BaseModel):
    """Structured aggregate result produced by SpecialistOrchestrator."""
    run_id: str
    context_id: str
    symbol: str
    started_at: datetime
    completed_at: datetime
    duration_seconds: float

    total_agents: int
    successful_agents: int
    failed_agents: int
    timed_out_agents: int
    degraded_agents: int

    records: List[AgentExecutionRecord] = Field(default_factory=list)
    outputs: List[AgentOutput] = Field(default_factory=list)


# ── Existing downstream schemas (unchanged) ──────────────────────────────────

class DebateInput(BaseModel):
    topic: str
    context: MarketContext
    agent_outputs: List[AgentOutput]


class DebateOutput(BaseModel):
    consensus: bool
    summary: str
    winning_argument: Optional[str]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TradeProposal(BaseModel):
    symbol: str
    action: str
    quantity: float
    target_price: float
    stop_loss: float
    rationale: str
    agent_outputs: List[AgentOutput]


class DecisionResult(BaseModel):
    approved: bool
    proposal: TradeProposal
    reasoning: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Phase 4.1: Evidence Aggregation Schemas ---

class EvidenceCategory(str, Enum):
    TECHNICAL = "TECHNICAL"
    MOMENTUM = "MOMENTUM"
    QUANT = "QUANT"
    FUNDAMENTAL = "FUNDAMENTAL"
    VALUATION = "VALUATION"
    SECTOR = "SECTOR"
    MACRO = "MACRO"
    NEWS = "NEWS"
    INSTITUTIONAL = "INSTITUTIONAL"
    UNKNOWN = "UNKNOWN"

class SignalDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"

class EvidenceType(str, Enum):
    DETERMINISTIC_FACT = "DETERMINISTIC_FACT"
    DETERMINISTIC_CALCULATION = "DETERMINISTIC_CALCULATION"
    LLM_INTERPRETATION = "LLM_INTERPRETATION"
    ASSUMPTION = "ASSUMPTION"
    UNAVAILABLE = "UNAVAILABLE"

class ConflictSeverity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# --- Phase 4.1A: New Enums ---

class MissingDataCategory(str, Enum):
    SPECIALIST_FAILED = "SPECIALIST_FAILED"
    SPECIALIST_TIMEOUT = "SPECIALIST_TIMEOUT"
    SPECIALIST_DEGRADED = "SPECIALIST_DEGRADED"
    METRIC_UNAVAILABLE = "METRIC_UNAVAILABLE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    DATA_CONFLICT = "DATA_CONFLICT"

class ConflictType(str, Enum):
    DIRECT_CONFLICT = "DIRECT_CONFLICT"
    DOMAIN_TENSION = "DOMAIN_TENSION"
    DATA_CONFLICT = "DATA_CONFLICT"

class AgreementLevel(str, Enum):
    METRIC_LEVEL = "METRIC_LEVEL"
    DOMAIN_LEVEL = "DOMAIN_LEVEL"

class PITStatus(str, Enum):
    CONSISTENT = "CONSISTENT"
    PIT_INCONSISTENT = "PIT_INCONSISTENT"
    UNKNOWN = "UNKNOWN"


class ResearchRegime(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    MIXED = "MIXED"
    NEUTRAL = "NEUTRAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

class NormalizedEvidence(BaseModel):
    evidence_id: str
    specialist_name: str
    metric_name: str
    category: EvidenceCategory
    direction: SignalDirection
    value: Optional[float] = None
    unit: str = ""
    confidence: float = 0.0
    importance: float = 0.0

    source: str = "UNKNOWN"
    source_tier: SourceTier = SourceTier.TIER_5_UNVERIFIED
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED

    context_id: str
    data_timestamp: datetime

    calculation_method: str = ""
    is_deterministic: bool = False
    is_llm_interpretation: bool = False
    evidence_type: EvidenceType = EvidenceType.UNAVAILABLE

    # Phase 4.1A extensions (backward-compatible defaults)
    source_evidence_id: Optional[str] = None
    pit_status: PITStatus = PITStatus.UNKNOWN

    @property
    def duplicate_key(self) -> str:
        """Deterministic key for duplicate detection."""
        ts_str = self.data_timestamp.isoformat() if self.data_timestamp else ""
        return f"{self.specialist_name}|{self.metric_name}|{self.context_id}|{ts_str}"

class EvidenceConflict(BaseModel):
    conflict_id: str
    category_a: EvidenceCategory
    category_b: EvidenceCategory
    signal_a: SignalDirection
    signal_b: SignalDirection
    specialist_a: str
    specialist_b: str
    severity: ConflictSeverity
    explanation: str
    context_id: str
    # Phase 4.1A extension
    conflict_type: ConflictType = ConflictType.DOMAIN_TENSION

class EvidenceAgreement(BaseModel):
    agreement_id: str
    categories: List[EvidenceCategory]
    direction: SignalDirection
    supporting_specialists: List[str]
    support_count: int
    weighted_strength: float
    explanation: str
    # Phase 4.1A extension
    level: AgreementLevel = AgreementLevel.DOMAIN_LEVEL

class MissingDataRecord(BaseModel):
    """Structured record for missing data with categorisation."""
    specialist_name: str
    category: MissingDataCategory
    detail: str
    metric_name: Optional[str] = None

class UnifiedEvidencePackage(BaseModel):
    run_id: str
    context_id: str
    symbol: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data_timestamp: datetime

    specialists_total: int = 0
    specialists_successful: int = 0
    specialists_degraded: int = 0
    specialists_failed: int = 0
    specialists_timed_out: int = 0

    evidence_items: List[NormalizedEvidence] = Field(default_factory=list)
    agreement_summary: List[EvidenceAgreement] = Field(default_factory=list)
    conflict_summary: List[EvidenceConflict] = Field(default_factory=list)

    bull_signals: List[str] = Field(default_factory=list)
    bear_signals: List[str] = Field(default_factory=list)
    neutral_signals: List[str] = Field(default_factory=list)

    high_confidence_signals: List[str] = Field(default_factory=list)
    low_confidence_signals: List[str] = Field(default_factory=list)

    missing_data: List[str] = Field(default_factory=list)
    data_quality_summary: str = ""

    specialist_contributions: Dict[str, float] = Field(default_factory=dict)

    overall_research_confidence: float = 0.0
    research_regime: ResearchRegime = ResearchRegime.INSUFFICIENT_DATA

    invalidation_conditions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)

    # Phase 4.1A extensions (backward-compatible defaults)
    missing_data_records: List[MissingDataRecord] = Field(default_factory=list)
    duplicates_detected: int = 0
    pit_inconsistent_count: int = 0
    total_evidence_extracted: int = 0


# ── Phase 6.1: Evidence Layer Foundation Schemas ───────────────────────────

class EvidenceRecord(BaseModel):
    """
    Phase 6.1: Strongly typed evidence record produced by EvidenceAggregator.
    Standardized boundary between Specialist Agents and the future Debate Engine.
    """
    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    context_id: str
    specialist_name: str
    specialist_version: str = "1.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data_timestamp: datetime
    evidence_type: EvidenceType = EvidenceType.DETERMINISTIC_CALCULATION
    claim: str
    value: Optional[Any] = None
    unit: Optional[str] = None
    source: Optional[str] = None
    provenance: Optional[List[ProvenanceRecord]] = Field(default_factory=list)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    status: AgentState = AgentState.SUCCESS
    risks: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)

    # Optional metadata
    category: Optional[EvidenceCategory] = None
    direction: Optional[SignalDirection] = None
    metric_name: Optional[str] = None
    invalidation_conditions: List[str] = Field(default_factory=list)
    is_deterministic: bool = False


class ContradictionRecord(BaseModel):
    """
    Phase 6.1: Material contradiction between two specialists.
    Explicitly recorded without resolution for downstream adversarial debate.
    """
    contradiction_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    subject: str
    specialist_a: str
    claim_a: str
    value_a: Optional[Any] = None
    direction_a: Optional[SignalDirection] = None
    specialist_b: str
    claim_b: str
    value_b: Optional[Any] = None
    direction_b: Optional[SignalDirection] = None
    severity: ConflictSeverity = ConflictSeverity.MODERATE
    explanation: str
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RejectedEvidenceRecord(BaseModel):
    """
    Phase 6.1: Record of an evidence item that was rejected due to
    malformed structure, missing fields, or forbidden content (e.g. CoT).
    """
    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    specialist_name: str
    reason: str
    raw_item: Optional[Any] = None
    rejected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvidenceSummary(BaseModel):
    """
    Phase 6.1: Normalized evidence package containing all validated evidence records,
    detected contradictions, degraded/failed specialist logs, and audit counts.
    Serves as the clean input boundary to the future Debate Engine.
    """
    run_id: str
    context_id: str
    symbol: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_evidence: int = 0
    valid_evidence: int = 0
    rejected_evidence: int = 0
    contradictions: List[ContradictionRecord] = Field(default_factory=list)
    degraded_specialists: List[str] = Field(default_factory=list)
    failed_specialists: List[str] = Field(default_factory=list)
    evidence_records: List[EvidenceRecord] = Field(default_factory=list)
    rejected_records: List[RejectedEvidenceRecord] = Field(default_factory=list)
    missing_data_records: List[MissingDataRecord] = Field(default_factory=list)

