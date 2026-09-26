from fastapi import APIRouter, HTTPException
from typing import List

from backend.application.research_chat_service import ResearchChatService
from backend.domain.chat_schemas import ChatMessage, ChatSession, ChatResponse

router = APIRouter(prefix="/api/research-chat", tags=["research_chat"])

service = ResearchChatService()

@router.post("/sessions", response_model=ChatSession)
async def create_session():
    """Create a new chat session and return its metadata."""
    return service.create_session()

@router.get("/sessions", response_model=List[ChatSession])
async def list_sessions():
    """Return a list of all chat sessions."""
    return service.list_sessions()

@router.get("/sessions/{session_id}", response_model=ChatSession)
async def get_session(session_id: str):
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

@router.get("/sessions/{session_id}/messages", response_model=List[ChatMessage])
async def list_messages(session_id: str):
    if service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return service.list_messages(session_id)

@router.post("/sessions/{session_id}/messages", response_model=ChatResponse)
async def submit_message(session_id: str, payload: dict):
    """Submit a user message and get assistant response.
    Expected JSON body: {"content": "your question"}
    """
    user_content = payload.get("content")
    if not user_content:
        raise HTTPException(status_code=400, detail="Message content cannot be empty")
    response = await service.generate_response(session_id, user_content)
    if response is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return response
