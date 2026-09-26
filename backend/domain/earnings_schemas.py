from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

class EarningsEventStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    INVALID = "INVALID"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    CONFIRMED = "CONFIRMED"
    ESTIMATED = "ESTIMATED"
    INCOMPARABLE = "INCOMPARABLE"
    PARTIAL = "PARTIAL"

class EarningsProvenance(BaseModel):
    provenance_id: str
    source_name: str
    source_type: str
    fetched_at: str
    authority_level: Optional[str] = None
    data_hash: Optional[str] = None

class EarningsMetric(BaseModel):
    actual: Optional[float] = None
    expected: Optional[float] = None
    surprise_pct: Optional[float] = None
    yoy_change_pct: Optional[float] = None
    qoq_change_pct: Optional[float] = None

class EarningsEvent(BaseModel):
    event_id: str
    symbol: str
    fiscal_period: Optional[str] = None
    fiscal_year: Optional[int] = None
    reporting_period: Optional[str] = None
    expected_report_date: Optional[str] = None
    actual_report_date: Optional[str] = None
    status: EarningsEventStatus = EarningsEventStatus.UNAVAILABLE
    source: str
    published_at: Optional[str] = None
    retrieved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    provenance: Optional[EarningsProvenance] = None
    evidence_references: List[str] = []

class GuidanceRecord(BaseModel):
    metric: str
    period: str
    expected_value_low: Optional[float] = None
    expected_value_high: Optional[float] = None
    currency: Optional[str] = None
    source: str

class EarningsResult(BaseModel):
    symbol: str
    reporting_period: str
    
    revenue: Optional[EarningsMetric] = None
    operating_profit: Optional[EarningsMetric] = None
    ebitda: Optional[EarningsMetric] = None
    net_income: Optional[EarningsMetric] = None
    eps: Optional[EarningsMetric] = None
    
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    
    guidance: List[GuidanceRecord] = []
    
    data_quality: EarningsEventStatus = EarningsEventStatus.AVAILABLE
    provenance: Optional[EarningsProvenance] = None

class EarningsResponse(BaseModel):
    symbol: str
    events: List[EarningsEvent] = []
    latest_result: Optional[EarningsResult] = None
    historical_results: List[EarningsResult] = []
    status: EarningsEventStatus = EarningsEventStatus.AVAILABLE
    error_message: Optional[str] = None
