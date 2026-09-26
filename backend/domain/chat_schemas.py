from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"

class ChatMessage(BaseModel):
    message_id: str = Field(..., description="UUID4 identifier for the message")
    role: ChatRole = Field(..., description="Message sender role")
    content: str = Field(..., description="Message text")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Message creation time")
    evidence_refs: Optional[List[str]] = Field(default=None, description="List of evidence identifiers referenced")
    quality_result: Optional[dict] = Field(default=None, description="AI Quality / Hallucination validation result")

class ChatSession(BaseModel):
    session_id: str = Field(..., description="UUID4 identifier for the chat session")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Session creation time")
    metadata: Optional[dict] = Field(default_factory=dict, description="Optional session metadata")

class ChatMessageCreate(BaseModel):
    content: str = Field(..., description="User message content")

class ChatResponse(BaseModel):
    message: ChatMessage = Field(..., description="Assistant reply message")
    evidence_refs: Optional[List[str]] = Field(default=None, description="Evidence references included in the answer")
    quality_result: Optional[dict] = Field(default=None, description="AI Quality / Hallucination validation result")
