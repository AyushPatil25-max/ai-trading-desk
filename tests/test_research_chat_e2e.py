import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.execution.persistent_state_store import global_persistent_state_store

client = TestClient(app)

@pytest.fixture(autouse=True)
def clear_state():
    # Ensure a clean persistent store before each test
    global_persistent_state_store.clear()
    yield
    global_persistent_state_store.clear()

# Helper to mock LLM client
class MockLLMClient:
    async def generate_structured(self, system_prompt: str, user_prompt: str, response_model):
        # Return a simple response with no evidence
        return response_model(content="Mocked answer", evidence_refs=None)

def mock_create_client(*args, **kwargs):
    return MockLLMClient()

def test_create_and_get_session():
    # Create a new chat session
    resp = client.post("/api/research-chat/sessions")
    assert resp.status_code == 200
    session = resp.json()
    assert "session_id" in session
    session_id = session["session_id"]

    # Retrieve the same session
    get_resp = client.get(f"/api/research-chat/sessions/{session_id}")
    assert get_resp.status_code == 200
    fetched = get_resp.json()
    assert fetched["session_id"] == session_id

def test_list_sessions():
    # Initially empty list
    list_resp = client.get("/api/research-chat/sessions")
    assert list_resp.status_code == 200
    assert list_resp.json() == []

    # Create two sessions
    ids = []
    for _ in range(2):
        r = client.post("/api/research-chat/sessions")
        ids.append(r.json()["session_id"])
    list_resp = client.get("/api/research-chat/sessions")
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert len(data) == 2
    returned_ids = {s["session_id"] for s in data}
    assert set(ids) == returned_ids

@patch("backend.application.research_chat_service.LLMAdapterFactory.create_client", side_effect=mock_create_client)
def test_message_flow(mock_factory):
    # Create session
    sess = client.post("/api/research-chat/sessions").json()
    sid = sess["session_id"]

    # Submit a user message
    payload = {"content": "What is the status?"}
    resp = client.post(f"/api/research-chat/sessions/{sid}/messages", json=payload)
    assert resp.status_code == 200
    chat_resp = resp.json()
    # Verify assistant response structure
    assert "message" in chat_resp
    assert chat_resp["message"]["role"] == "assistant"
    assert chat_resp["message"]["content"] == "Mocked answer"
    # Verify that a user message was also stored (list messages)
    msgs = client.get(f"/api/research-chat/sessions/{sid}/messages").json()
    roles = [m["role"] for m in msgs]
    assert roles == ["user", "assistant"]
    assert msgs[0]["content"] == "What is the status?"

def test_invalid_session():
    resp = client.get("/api/research-chat/sessions/invalid-id")
    assert resp.status_code == 404

def test_empty_message():
    sid = client.post("/api/research-chat/sessions").json()["session_id"]
    resp = client.post(f"/api/research-chat/sessions/{sid}/messages", json={})
    assert resp.status_code == 400
