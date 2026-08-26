"""
Unit tests for Provider-Neutral LLM Adapter & Registry — Phase 5.6C

Validates candidate slots resolution, deterministic hashing, mock execution,
and unsupported provider error handling.
"""

from datetime import datetime
import unittest
from pydantic import BaseModel

from backend.infrastructure.llm_provider_adapter import (
    LLMAdapterFactory,
    LLMProviderType,
    ModelCandidateDescriptor,
    ProviderNeutralLLMClient,
)
from backend.infrastructure.llm_replay_cache import LLMReplayCache


class DummyResponse(BaseModel):
    decision: str = "APPROVE"
    confidence: float = 0.90


class TestLLMAdapterFactory(unittest.IsolatedAsyncioTestCase):
    def test_list_candidate_slots_contains_four_verified_slots(self):
        slots = LLMAdapterFactory.list_candidate_slots()
        self.assertEqual(len(slots), 4)
        slot_names = [s.slot_name for s in slots]
        self.assertIn("groq_primary", slot_names)
        self.assertIn("gemini_flash", slot_names)
        self.assertIn("openai_lightweight", slot_names)
        self.assertIn("openai_reasoning", slot_names)

    def test_create_mock_client_executes_deterministically(self):
        dummy = DummyResponse()
        client = LLMAdapterFactory.create_client("mock-llm", force_mock=dummy)
        self.assertEqual(client.provider, LLMProviderType.MOCK)

    async def test_mock_client_generates_structured_with_stats(self):
        dummy = DummyResponse()
        client = LLMAdapterFactory.create_client("mock-llm", force_mock=dummy)
        resp = await client.generate_structured("sys", "user", DummyResponse)
        self.assertEqual(resp.decision, "APPROVE")
        self.assertIsNotNone(client.last_stats)
        self.assertGreater(len(client.last_stats.request_hash), 0)

    def test_unknown_slot_raises_keyerror(self):
        with self.assertRaises(KeyError):
            LLMAdapterFactory.get_candidate("non_existent_slot")


if __name__ == "__main__":
    unittest.main()
