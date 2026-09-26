from enum import Enum
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field

class SpecialistView(BaseModel):
    specialist_name: str
    view: str
    evidence_ids: List[str] = Field(default_factory=list)
    confidence: float = 0.0

class ResearchConflict(BaseModel):
    conflict_type: str 
    description: str
    specialists_involved: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)

class ResearchSynthesisResult(BaseModel):
    symbol: str
    context_id: str
    run_id: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    overall_summary: str = ""
    
    fundamental_view: Optional[SpecialistView] = None
    technical_view: Optional[SpecialistView] = None
    momentum_view: Optional[SpecialistView] = None
    quantitative_view: Optional[SpecialistView] = None
    institutional_view: Optional[SpecialistView] = None
    chart_pattern_view: Optional[SpecialistView] = None
    
    bull_case_summary: str = ""
    bear_case_summary: str = ""
    risk_summary: str = ""
    
    key_supporting_evidence_ids: List[str] = Field(default_factory=list)
    contradictory_evidence_ids: List[str] = Field(default_factory=list)
    
    conflicts: List[ResearchConflict] = Field(default_factory=list)
    data_limitations: List[str] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)
    
    is_stale: bool = False
    is_unavailable: bool = False
