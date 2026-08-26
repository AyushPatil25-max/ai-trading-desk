"""
Unit tests for LLM Execution Mode & Determinism Auditor — Phase 5.5

Validates disclosure of LLM execution mode (Mock LLM, Real API, Cached) and determinism rules.
"""

import unittest

from pydantic import BaseModel
from backend.infrastructure.llm import MockLLMClient


class DummyModel(BaseModel):
    key: str = "value"


class TestLLMExecutionAudit(unittest.IsolatedAsyncioTestCase):
    async def test_mock_llm_client_discloses_offline_mode(self):
        dummy = DummyModel()
        client = MockLLMClient(fixed_response=dummy)
        self.assertEqual(client.model_name, "mock-llm")
        resp = await client.generate_structured("sys", "user", DummyModel)
        self.assertEqual(resp, dummy)
        self.assertEqual(client.call_count, 1)


if __name__ == "__main__":
    unittest.main()
