import uuid
from datetime import datetime
from typing import List, Optional

from backend.execution.persistent_state_store import global_persistent_state_store
from backend.domain.research_workspace_schemas import (
    ResearchWorkspace,
    ResearchItem,
    ResearchNote,
    WorkspaceStatus,
)

class ResearchWorkspaceService:
    """Service layer for managing research workspaces, items, and notes.

    Uses the flat key strategy on PersistentStateStore:
        workspace:{workspace_id}
        workspace:{workspace_id}:item:{item_id}
        workspace:{workspace_id}:note:{note_id}
    """

    # Workspace operations
    def _workspace_key(self, workspace_id: str) -> str:
        return f"workspace:{workspace_id}"

    def _item_key(self, workspace_id: str, item_id: str) -> str:
        return f"workspace:{workspace_id}:item:{item_id}"

    def _note_key(self, workspace_id: str, note_id: str) -> str:
        return f"workspace:{workspace_id}:note:{note_id}"

    # ---------- Workspace ----------
    def create_workspace(self, name: str, description: Optional[str] = None, metadata: Optional[dict] = None) -> ResearchWorkspace:
        workspace_id = uuid.uuid4().hex
        now = datetime.utcnow()
        ws = ResearchWorkspace(
            workspace_id=workspace_id,
            name=name,
            description=description,
            status=WorkspaceStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            metadata=metadata,
        )
        key = self._workspace_key(workspace_id)
        global_persistent_state_store.set(key, ws.dict())
        return ws

    def get_workspace(self, workspace_id: str) -> Optional[ResearchWorkspace]:
        data = global_persistent_state_store.get(self._workspace_key(workspace_id))
        if data is None:
            return None
        return ResearchWorkspace(**data)

    def list_workspaces(self, include_deleted: bool = False) -> List[ResearchWorkspace]:
        prefix = "workspace:"
        all_keys = [k for k in global_persistent_state_store._data.keys() if k.startswith(prefix) and ":item:" not in k and ":note:" not in k]
        workspaces = []
        for key in all_keys:
            ws = ResearchWorkspace(**global_persistent_state_store.get(key))
            if not include_deleted and ws.status == WorkspaceStatus.DELETED:
                continue
            workspaces.append(ws)
        return workspaces

    def update_workspace(self, workspace_id: str, name: Optional[str] = None, description: Optional[str] = None, status: Optional[WorkspaceStatus] = None, metadata: Optional[dict] = None) -> Optional[ResearchWorkspace]:
        ws = self.get_workspace(workspace_id)
        if not ws:
            return None
        if name is not None:
            ws.name = name
        if description is not None:
            ws.description = description
        if status is not None:
            ws.status = status
        if metadata is not None:
            ws.metadata = metadata
        ws.updated_at = datetime.utcnow()
        global_persistent_state_store.set(self._workspace_key(workspace_id), ws.dict())
        return ws

    def delete_workspace(self, workspace_id: str) -> bool:
        # Soft delete: set status to DELETED and hide items/notes from normal APIs
        ws = self.get_workspace(workspace_id)
        if not ws:
            return False
        ws.status = WorkspaceStatus.DELETED
        ws.updated_at = datetime.utcnow()
        global_persistent_state_store.set(self._workspace_key(workspace_id), ws.dict())
        return True

    # ---------- Items ----------
    def create_item(
        self,
        workspace_id: str,
        item_type: str,
        title: str,
        symbol: Optional[str] = None,
        source_reference: Optional[str] = None,
        metadata: Optional[dict] = None,
        evidence_refs: Optional[List[str]] = None,
        provenance_refs: Optional[List[str]] = None,
    ) -> Optional[ResearchItem]:
        ws = self.get_workspace(workspace_id)
        if not ws or ws.status == WorkspaceStatus.DELETED:
            return None
        item_id = uuid.uuid4().hex
        now = datetime.utcnow()
        item = ResearchItem(
            item_id=item_id,
            workspace_id=workspace_id,
            item_type=item_type,
            title=title,
            symbol=symbol,
            source_reference=source_reference,
            created_at=now,
            updated_at=now,
            metadata=metadata,
            evidence_refs=evidence_refs or [],
            provenance_refs=provenance_refs or [],
        )
        global_persistent_state_store.set(self._item_key(workspace_id, item_id), item.dict())
        return item

    def get_item(self, workspace_id: str, item_id: str) -> Optional[ResearchItem]:
        data = global_persistent_state_store.get(self._item_key(workspace_id, item_id))
        if data is None:
            return None
        ws = self.get_workspace(workspace_id)
        if ws and ws.status == WorkspaceStatus.DELETED:
            return None
        return ResearchItem(**data)

    def list_items(self, workspace_id: str) -> List[ResearchItem]:
        ws = self.get_workspace(workspace_id)
        if not ws or ws.status == WorkspaceStatus.DELETED:
            return []
        prefix = f"workspace:{workspace_id}:item:"
        keys = [k for k in global_persistent_state_store._data.keys() if k.startswith(prefix)]
        return [ResearchItem(**global_persistent_state_store.get(k)) for k in keys]

    def delete_item(self, workspace_id: str, item_id: str) -> bool:
        ws = self.get_workspace(workspace_id)
        if not ws or ws.status == WorkspaceStatus.DELETED:
            return False
        return global_persistent_state_store.delete(self._item_key(workspace_id, item_id))

    # ---------- Notes ----------
    def create_note(
        self,
        workspace_id: str,
        title: str,
        content: str,
        associated_item_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        evidence_refs: Optional[List[str]] = None,
        provenance_refs: Optional[List[str]] = None,
    ) -> Optional[ResearchNote]:
        ws = self.get_workspace(workspace_id)
        if not ws or ws.status == WorkspaceStatus.DELETED:
            return None
        note_id = uuid.uuid4().hex
        now = datetime.utcnow()
        note = ResearchNote(
            note_id=note_id,
            workspace_id=workspace_id,
            title=title,
            content=content,
            associated_item_id=associated_item_id,
            created_at=now,
            updated_at=now,
            metadata=metadata,
            evidence_refs=evidence_refs or [],
            provenance_refs=provenance_refs or [],
        )
        global_persistent_state_store.set(self._note_key(workspace_id, note_id), note.dict())
        return note

    def get_note(self, workspace_id: str, note_id: str) -> Optional[ResearchNote]:
        data = global_persistent_state_store.get(self._note_key(workspace_id, note_id))
        if data is None:
            return None
        ws = self.get_workspace(workspace_id)
        if ws and ws.status == WorkspaceStatus.DELETED:
            return None
        return ResearchNote(**data)

    def list_notes(self, workspace_id: str) -> List[ResearchNote]:
        ws = self.get_workspace(workspace_id)
        if not ws or ws.status == WorkspaceStatus.DELETED:
            return []
        prefix = f"workspace:{workspace_id}:note:"
        keys = [k for k in global_persistent_state_store._data.keys() if k.startswith(prefix)]
        return [ResearchNote(**global_persistent_state_store.get(k)) for k in keys]

    def delete_note(self, workspace_id: str, note_id: str) -> bool:
        ws = self.get_workspace(workspace_id)
        if not ws or ws.status == WorkspaceStatus.DELETED:
            return False
        return global_persistent_state_store.delete(self._note_key(workspace_id, note_id))

# Global singleton for DI usage
global_research_workspace_service = ResearchWorkspaceService()
