"""
Unit tests for Proxy Pattern & Parametric Approximation Detector — Phase 5.5

Validates regex detection of hardcoded multipliers and code scanning capabilities.
"""

import os
import tempfile
import unittest

from backend.validation.proxy_detector import ProxyDetector


class TestProxyDetector(unittest.TestCase):
    def test_proxy_detector_detects_proportional_multiplier(self):
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".py", delete=False) as tf:
            tf.write("return round(bench_ret * 1.15, 2)\n")
            temp_path = tf.name

        try:
            findings = ProxyDetector.scan_file(temp_path)
            self.assertEqual(len(findings), 1)
            self.assertIn("bench_ret", findings[0].line_content)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_proxy_detector_ignores_clean_file(self):
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".py", delete=False) as tf:
            tf.write("total_return = (final_cap / init_cap - 1.0) * 100.0\n")
            temp_path = tf.name

        try:
            findings = ProxyDetector.scan_file(temp_path)
            self.assertEqual(len(findings), 0)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
