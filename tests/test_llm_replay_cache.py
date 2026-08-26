"""
Unit tests for LLM Replay Cache — Phase 5.6

Validates deterministic key computation, payload recording, cache hit retrieval, and disk persistence.
"""

import os
import tempfile
import unittest

from backend.infrastructure.llm_replay_cache import LLMReplayCache


class TestLLMReplayCache(unittest.TestCase):
    def setUp(self):
        self.cache = LLMReplayCache()

    def test_deterministic_key_computation(self):
        k1 = LLMReplayCache.compute_key("sys", "user", "SchemaA", "llama-3.3", 0.1, "ctx-1")
        k2 = LLMReplayCache.compute_key("sys", "user", "SchemaA", "llama-3.3", 0.1, "ctx-1")
        k3 = LLMReplayCache.compute_key("sys_diff", "user", "SchemaA", "llama-3.3", 0.1, "ctx-1")

        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)

    def test_set_get_and_persistence(self):
        k = LLMReplayCache.compute_key("sys", "user", "SchemaA", "llama-3.3", 0.1, "ctx-1")
        self.cache.set(
            key=k,
            model="llama-3.3",
            temperature=0.1,
            system_prompt="sys",
            user_prompt="user",
            schema_name="SchemaA",
            context_id="ctx-1",
            response_payload={"verdict": "APPROVE"},
        )

        entry = self.cache.get(k)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.response_payload["verdict"], "APPROVE")

        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as tf:
            temp_path = tf.name

        try:
            self.cache.save_to_file(temp_path)
            new_cache = LLMReplayCache(cache_file_path=temp_path)
            loaded_entry = new_cache.get(k)
            self.assertIsNotNone(loaded_entry)
            self.assertEqual(loaded_entry.response_payload["verdict"], "APPROVE")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
