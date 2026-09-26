from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from backend.execution.persistent_state_store import global_persistent_state_store
from backend.domain.chat_schemas import ChatSession, ChatMessage, ChatMessageCreate, ChatResponse, ChatRole
from backend.infrastructure.llm_provider_adapter import LLMAdapterFactory, LLMProviderType
from pydantic import BaseModel
class ResearchChatService:
    """Service layer for AI Research Chat.

    Stores sessions and messages using PersistentStateStore with flat keys:
        chat:session:{session_id}
        chat:session:{session_id}:msg:{message_id}
    """

    # Key helpers
    @staticmethod
    def _session_key(session_id: str) -> str:
        return f"chat:session:{session_id}"

    @staticmethod
    def _message_key(session_id: str, message_id: str) -> str:
        return f"chat:session:{session_id}:msg:{message_id}"

    # Session CRUD
    def create_session(self) -> ChatSession:
        session_id = uuid4().hex
        now = datetime.utcnow()
        session = ChatSession(session_id=session_id, created_at=now, metadata={})
        global_persistent_state_store.set(self._session_key(session_id), session.dict())
        return session

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        data = global_persistent_state_store.get(self._session_key(session_id))
        if data is None:
            return None
        return ChatSession(**data)

    def list_sessions(self) -> List[ChatSession]:
        prefix = "chat:session:"
        keys = [k for k in global_persistent_state_store._data.keys() if k.startswith(prefix) and ":msg:" not in k]
        return [ChatSession(**global_persistent_state_store.get(k)) for k in keys]

    # Message handling
    def add_user_message(self, session_id: str, content: str) -> Optional[ChatMessage]:
        session = self.get_session(session_id)
        if session is None:
            return None
        message_id = uuid4().hex
        now = datetime.utcnow()
        msg = ChatMessage(
            message_id=message_id,
            role=ChatRole.USER,
            content=content,
            timestamp=now,
            evidence_refs=None,
        )
        global_persistent_state_store.set(self._message_key(session_id, message_id), msg.dict())
        return msg

    def add_assistant_message(self, session_id: str, content: str, evidence_refs: Optional[List[str]] = None, quality_result: Optional[dict] = None) -> Optional[ChatMessage]:
        session = self.get_session(session_id)
        if session is None:
            return None
        message_id = uuid4().hex
        now = datetime.utcnow()
        msg = ChatMessage(
            message_id=message_id,
            role=ChatRole.ASSISTANT,
            content=content,
            timestamp=now,
            evidence_refs=evidence_refs,
            quality_result=quality_result,
        )
        global_persistent_state_store.set(self._message_key(session_id, message_id), msg.dict())
        return msg

    def list_messages(self, session_id: str) -> List[ChatMessage]:
        prefix = f"chat:session:{session_id}:msg:"
        keys = [k for k in global_persistent_state_store._data.keys() if k.startswith(prefix)]
        # sort by timestamp using stored data
        msgs = [ChatMessage(**global_persistent_state_store.get(k)) for k in keys]
        msgs.sort(key=lambda m: m.timestamp)
        return msgs

    # Core chat flow
    async def generate_response(self, session_id: str, user_prompt: str) -> Optional[ChatResponse]:
        # Store user message
        user_msg = self.add_user_message(session_id, user_prompt)
        if user_msg is None:
            return None
        # Build grounding context
        from backend.application.research_workspace_service import global_research_workspace_service
        workspaces = global_research_workspace_service.list_workspaces()
        
        from backend.application.ai_quality_engine import global_ai_quality_engine, EvidenceItem
        evidence_pool = []
        workspace_context_texts = []
        
        for ws in workspaces[:5]:
            items = global_research_workspace_service.list_items(ws.workspace_id)
            for item in items:
                evidence_pool.append(EvidenceItem(
                    evidence_id=item.item_id,
                    content=f"{item.title} (Symbol: {item.symbol})",
                    source_reference=item.source_reference
                ))
                workspace_context_texts.append(f"- ID: {item.item_id} | {item.title} (Symbol: {item.symbol})")
                
        workspace_summary = "\\n".join(workspace_context_texts) if workspace_context_texts else "none"
        
        system_prompt = (
            "You are an AI research assistant. Answer the user's question using only the information "
            f"available in the research workspaces. Available items:\\n{workspace_summary}\\n"
            "Do not fabricate data or evidence. When you reference a piece of evidence, include its ID in the list."
        )
        # LLM client
        llm_client = LLMAdapterFactory.create_client("gemini_flash", temperature=0.1)
        # Define response model
        class AssistantResult(BaseModel):
            content: str
            evidence_refs: Optional[List[str]] = None
        # Call LLM
        try:
            result = await llm_client.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=AssistantResult,
            )
        except Exception as e:
            # Log and return error message as assistant reply
            from backend.infrastructure.llm import LLMClientError
            if isinstance(e, LLMClientError):
                content = f"[Error] Language model failed: {e}"
            else:
                content = f"[Error] Unexpected failure: {e}"
            assistant_msg = self.add_assistant_message(session_id, content, evidence_refs=None)
            return ChatResponse(message=assistant_msg, evidence_refs=None)
            
        # Quality Validation
        quality_response = await global_ai_quality_engine.validate_response(
            ai_text=result.content,
            evidence_pool=evidence_pool
        )
        
        # Persist assistant message
        assistant_msg = self.add_assistant_message(
            session_id, 
            result.content, 
            result.evidence_refs,
            quality_result=quality_response.quality_result.model_dump()
        )
        
        return ChatResponse(
            message=assistant_msg, 
            evidence_refs=result.evidence_refs,
            quality_result=quality_response.quality_result.model_dump()
        )
