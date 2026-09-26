from enum import Enum
from typing import List, Dict, Any, Union, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from backend.domain.schemas import DataQualityStatus

class ScreenerOperator(str, Enum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"

class LogicalOperator(str, Enum):
    AND = "AND"
    OR = "OR"

class FilterCriterion(BaseModel):
    field: str  # e.g., "current_price", "technical.rsi_14", "fundamental.pe_ratio"
    operator: ScreenerOperator
    value: Any

class FilterGroup(BaseModel):
    logical_operator: LogicalOperator = LogicalOperator.AND
    criteria: List[Union['FilterCriterion', 'FilterGroup']] = Field(default_factory=list)

class MatchedCriterionDetail(BaseModel):
    field: str
    operator: str
    target_value: Any
    actual_value: Any

class FailedCriterionDetail(BaseModel):
    field: str
    operator: str
    target_value: Any
    actual_value: Any

class UnavailableCriterionDetail(BaseModel):
    field: str
    reason: str = "Metric unavailable"

class ScreenerMatchResult(BaseModel):
    symbol: str
    is_match: bool
    matched_criteria: List[MatchedCriterionDetail] = Field(default_factory=list)
    failed_criteria: List[FailedCriterionDetail] = Field(default_factory=list)
    unavailable_criteria: List[UnavailableCriterionDetail] = Field(default_factory=list)
    data_quality: DataQualityStatus = DataQualityStatus.OK
    rank_score: float = 0.0
    evidence_ids: List[str] = Field(default_factory=list)
    context_id: str = "UNKNOWN"

class ScreenerRequest(BaseModel):
    universe_type: str = "NIFTY_50"  # Supported by StockUniverse
    filters: FilterGroup
    limit: int = 100
    sort_by: Optional[str] = None
    sort_descending: bool = True

class ScreenerResponse(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    universe_type: str
    total_evaluated: int
    total_matches: int
    matches: List[ScreenerMatchResult] = Field(default_factory=list)

FilterGroup.model_rebuild()
