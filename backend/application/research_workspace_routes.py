from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional

from backend.application.research_workspace_service import global_research_workspace_service
from backend.domain.research_workspace_schemas import (
    ResearchWorkspace,
    ResearchItem,
    ResearchNote,
    WorkspaceStatus,
    ResearchItemType,
)

router = APIRouter(prefix="/api/research-workspace", tags=["research-workspace"])

# Workspace endpoints
@router.post("/workspaces", response_model=ResearchWorkspace)
def create_workspace(name: str = Query(..., description="Workspace name"), description: Optional[str] = Query(None), metadata: Optional[str] = Query(None)):
    return global_research_workspace_service.create_workspace(name=name, description=description, metadata=metadata)

@router.get("/workspaces", response_model=List[ResearchWorkspace])
def list_workspaces(include_deleted: bool = Query(False)):
    return global_research_workspace_service.list_workspaces(include_deleted=include_deleted)

@router.get("/workspaces/{workspace_id}", response_model=ResearchWorkspace)
def get_workspace(workspace_id: str):
    ws = global_research_workspace_service.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws

@router.patch("/workspaces/{workspace_id}", response_model=ResearchWorkspace)
def update_workspace(workspace_id: str, name: Optional[str] = Query(None), description: Optional[str] = Query(None), status: Optional[WorkspaceStatus] = Query(None), metadata: Optional[str] = Query(None)):
    ws = global_research_workspace_service.update_workspace(workspace_id, name=name, description=description, status=status, metadata=metadata)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws

@router.delete("/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str):
    success = global_research_workspace_service.delete_workspace(workspace_id)
    if not success:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"deleted": True}

# Item endpoints
@router.post("/workspaces/{workspace_id}/items", response_model=ResearchItem)
def create_item(
    workspace_id: str,
    item_type: ResearchItemType = Query(...),
    title: str = Query(...),
    symbol: Optional[str] = Query(None),
    source_reference: Optional[str] = Query(None),
    metadata: Optional[str] = Query(None),
    evidence_refs: Optional[List[str]] = Query(None),
    provenance_refs: Optional[List[str]] = Query(None),
):
    item = global_research_workspace_service.create_item(
        workspace_id=workspace_id,
        item_type=item_type,
        title=title,
        symbol=symbol,
        source_reference=source_reference,
        metadata=metadata,
        evidence_refs=evidence_refs,
        provenance_refs=provenance_refs,
    )
    if not item:
        raise HTTPException(status_code=404, detail="Workspace not found or deleted")
    return item

@router.get("/workspaces/{workspace_id}/items", response_model=List[ResearchItem])
def list_items(workspace_id: str):
    return global_research_workspace_service.list_items(workspace_id)

@router.get("/workspaces/{workspace_id}/items/{item_id}", response_model=ResearchItem)
def get_item(workspace_id: str, item_id: str):
    item = global_research_workspace_service.get_item(workspace_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@router.delete("/workspaces/{workspace_id}/items/{item_id}")
def delete_item(workspace_id: str, item_id: str):
    success = global_research_workspace_service.delete_item(workspace_id, item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"deleted": True}

# Note endpoints
@router.post("/workspaces/{workspace_id}/notes", response_model=ResearchNote)
def create_note(
    workspace_id: str,
    title: str = Query(...),
    content: str = Query(...),
    associated_item_id: Optional[str] = Query(None),
    metadata: Optional[str] = Query(None),
    evidence_refs: Optional[List[str]] = Query(None),
    provenance_refs: Optional[List[str]] = Query(None),
):
    note = global_research_workspace_service.create_note(
        workspace_id=workspace_id,
        title=title,
        content=content,
        associated_item_id=associated_item_id,
        metadata=metadata,
        evidence_refs=evidence_refs,
        provenance_refs=provenance_refs,
    )
    if not note:
        raise HTTPException(status_code=404, detail="Workspace not found or deleted")
    return note

@router.get("/workspaces/{workspace_id}/notes", response_model=List[ResearchNote])
def list_notes(workspace_id: str):
    return global_research_workspace_service.list_notes(workspace_id)

@router.get("/workspaces/{workspace_id}/notes/{note_id}", response_model=ResearchNote)
def get_note(workspace_id: str, note_id: str):
    note = global_research_workspace_service.get_note(workspace_id, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note

@router.delete("/workspaces/{workspace_id}/notes/{note_id}")
def delete_note(workspace_id: str, note_id: str):
    success = global_research_workspace_service.delete_note(workspace_id, note_id)
    if not success:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"deleted": True}
