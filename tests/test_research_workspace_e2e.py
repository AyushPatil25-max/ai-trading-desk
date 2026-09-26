import unittest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

class TestResearchWorkspaceE2E(unittest.TestCase):
    def setUp(self):
        # Ensure a clean state for each test run by clearing the in‑memory store if possible
        # The PersistentStateStore used in the service is in‑memory; we reset it via the global singleton.
        from backend.execution.persistent_state_store import global_persistent_state_store
        global_persistent_state_store._data.clear()

    def test_workspace_crud_and_item_note_flow(self):
        # 1. Create a workspace
        ws_resp = client.post(
            "/api/research-workspace/workspaces",
            params={"name": "Test WS", "description": "A workspace for testing"},
        )
        self.assertEqual(ws_resp.status_code, 200)
        ws_data = ws_resp.json()
        workspace_id = ws_data["workspace_id"]
        self.assertIsNotNone(workspace_id)
        self.assertEqual(ws_data["name"], "Test WS")

        # 2. List workspaces (default hides deleted)
        list_resp = client.get("/api/research-workspace/workspaces")
        self.assertEqual(list_resp.status_code, 200)
        workspaces = list_resp.json()
        self.assertTrue(any(w["workspace_id"] == workspace_id for w in workspaces))

        # 3. Retrieve the created workspace
        get_resp = client.get(f"/api/research-workspace/workspaces/{workspace_id}")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["workspace_id"], workspace_id)

        # 4. Create a research item with source/evidence/provenance fields
        item_params = {
            "item_type": "SECURITY",
            "title": "Test Item",
            "symbol": "AAPL",
            "source_reference": "https://example.com/item",
            "evidence_refs": "ev1",  # repeated param will be interpreted as list by FastAPI
            "provenance_refs": "prov1",
        }
        # FastAPI parses repeated keys as list; we provide them as separate entries
        item_resp = client.post(
            f"/api/research-workspace/workspaces/{workspace_id}/items",
            params=item_params,
        )
        self.assertEqual(item_resp.status_code, 200)
        item = item_resp.json()
        item_id = item["item_id"]
        self.assertEqual(item["title"], "Test Item")
        self.assertEqual(item["symbol"], "AAPL")
        self.assertEqual(item["source_reference"], "https://example.com/item")
        # evidence_refs and provenance_refs are stored as list in the model
        self.assertIn("ev1", item["evidence_refs"])
        self.assertIn("prov1", item["provenance_refs"])

        # 5. List items for the workspace
        list_items_resp = client.get(f"/api/research-workspace/workspaces/{workspace_id}/items")
        self.assertEqual(list_items_resp.status_code, 200)
        items = list_items_resp.json()
        self.assertTrue(any(i["item_id"] == item_id for i in items))

        # 6. Retrieve the created item
        get_item_resp = client.get(f"/api/research-workspace/workspaces/{workspace_id}/items/{item_id}")
        self.assertEqual(get_item_resp.status_code, 200)
        fetched_item = get_item_resp.json()
        self.assertEqual(fetched_item["item_id"], item_id)
        self.assertEqual(fetched_item["title"], "Test Item")

        # 7. Create a note linked to the item
        note_params = {
            "title": "Test Note",
            "content": "Some content",
            "associated_item_id": item_id,
        }
        note_resp = client.post(
            f"/api/research-workspace/workspaces/{workspace_id}/notes",
            params=note_params,
        )
        self.assertEqual(note_resp.status_code, 200)
        note = note_resp.json()
        note_id = note["note_id"]
        self.assertEqual(note["associated_item_id"], item_id)

        # 8. List notes for the workspace
        list_notes_resp = client.get(f"/api/research-workspace/workspaces/{workspace_id}/notes")
        self.assertEqual(list_notes_resp.status_code, 200)
        notes = list_notes_resp.json()
        self.assertTrue(any(n["note_id"] == note_id for n in notes))

        # 9. Retrieve the created note
        get_note_resp = client.get(f"/api/research-workspace/workspaces/{workspace_id}/notes/{note_id}")
        self.assertEqual(get_note_resp.status_code, 200)
        fetched_note = get_note_resp.json()
        self.assertEqual(fetched_note["note_id"], note_id)
        self.assertEqual(fetched_note["title"], "Test Note")

        # 10. Soft‑delete the workspace
        delete_resp = client.delete(f"/api/research-workspace/workspaces/{workspace_id}")
        self.assertEqual(delete_resp.status_code, 200)
        self.assertTrue(delete_resp.json()["deleted"])

        # 11. Verify the workspace is hidden from default list
        list_after_del = client.get("/api/research-workspace/workspaces")
        self.assertEqual(list_after_del.status_code, 200)
        self.assertFalse(any(w["workspace_id"] == workspace_id for w in list_after_del.json()))

        # 12. Verify it appears when include_deleted=True
        list_inc_deleted = client.get("/api/research-workspace/workspaces", params={"include_deleted": "true"})
        self.assertEqual(list_inc_deleted.status_code, 200)
        self.assertTrue(any(w["workspace_id"] == workspace_id for w in list_inc_deleted.json()))

        # 13. Invalid workspace references return 404
        bad_ws_resp = client.get("/api/research-workspace/workspaces/invalid-id")
        self.assertEqual(bad_ws_resp.status_code, 404)
        bad_item_resp = client.get(f"/api/research-workspace/workspaces/invalid-id/items/invalid-item")
        self.assertEqual(bad_item_resp.status_code, 404)

        # 14. Ensure no broker/execution behavior is invoked (simply verify that the app is still responsive)
        health_resp = client.get("/api/analyze")  # a lightweight endpoint defined in main
        self.assertEqual(health_resp.status_code, 200)

if __name__ == "__main__":
    unittest.main()
