from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from backend.domain.schemas import DataQualityStatus

class ComparisonMetricValue(BaseModel):
    value: Any = None
    is_available: bool = False
    unit: Optional[str] = None
    freshness_status: str = "AVAILABLE"

class StockComparisonValues(BaseModel):
    symbol: str
    metrics: Dict[str, ComparisonMetricValue] = Field(default_factory=dict)
    data_quality: DataQualityStatus = DataQualityStatus.OK
    context_id: str = "UNKNOWN"

class ComparisonRelativeObservation(BaseModel):
    metric: str
    observation: str
    winner_symbol: Optional[str] = None
    is_comparable: bool = True

class StockComparisonResult(BaseModel):
    comparison_id: str
    symbols: List[str]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    comparisons: List[StockComparisonValues] = Field(default_factory=list)
    relative_observations: List[ComparisonRelativeObservation] = Field(default_factory=list)

class StockComparisonRequest(BaseModel):
    symbols: List[str]
    metrics: List[str] = Field(default_factory=list) # e.g. "current_price", "fundamental.pe_ratio"
