from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class WorkspaceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"

class ResearchWorkspace(BaseModel):
    workspace_id: str = Field(description="UUID4 identifier for the workspace")
    name: str
    description: Optional[str] = None
    status: WorkspaceStatus = WorkspaceStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    metadata: Optional[Dict[str, Any]] = None

class ResearchItemType(str, Enum):
    SECURITY = "SECURITY"
    SCREENER_RESULT = "SCREENER_RESULT"
    COMPARISON = "COMPARISON"
    PORTFOLIO = "PORTFOLIO"
    NEWS = "NEWS"
    EARNINGS = "EARNINGS"
    RESEARCH_SYNTHESIS = "RESEARCH_SYNTHESIS"

class ResearchItem(BaseModel):
    item_id: str = Field(description="UUID4 identifier for the research item")
    workspace_id: str
    item_type: ResearchItemType
    title: str
    symbol: Optional[str] = None
    source_reference: Optional[str] = None  # e.g., URL or internal ID
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    metadata: Optional[Dict[str, Any]] = None
    evidence_refs: List[str] = Field(default_factory=list)  # IDs of EvidenceRecord
    provenance_refs: List[str] = Field(default_factory=list)  # IDs of ProvenanceRecord

class ResearchNote(BaseModel):
    note_id: str = Field(description="UUID4 identifier for the note")
    workspace_id: str
    title: str
    content: str
    associated_item_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    metadata: Optional[Dict[str, Any]] = None
    evidence_refs: List[str] = Field(default_factory=list)
    provenance_refs: List[str] = Field(default_factory=list)
