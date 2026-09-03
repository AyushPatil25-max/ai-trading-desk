"""
Phase 32 — REST API Tests for Execution Telemetry & Observability Endpoints

Covers:
- GET /api/execution/telemetry/status
- GET /api/execution/telemetry/metrics
- GET /api/execution/telemetry/latency
- GET /api/execution/telemetry/drift
- GET /api/execution/telemetry/history
- GET /api/execution/telemetry/history/{execution_id}
"""

from datetime import datetime, timezone
import unittest
from fastapi.testclient import TestClient

from backend.main import app
from backend.domain.execution_decision_schemas import ExecutionMode
from backend.domain.execution_telemetry_schemas import ExecutionTelemetrySample
from backend.execution.execution_telemetry import global_execution_telemetry_collector


class TestExecutionTelemetryAPI(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        global_execution_telemetry_collector.clear()

        # Seed 3 samples
        for i in range(3):
            global_execution_telemetry_collector.record_sample(
                ExecutionTelemetrySample(
                    execution_id=f"api-exec-{i}",
                    decision_id=f"api-dec-{i}",
                    strategy_id="api_strat",
                    strategy_version="1.0.0",
                    symbol="TCS.NS",
                    execution_mode=ExecutionMode.PAPER,
                    outcome="SUCCESS",
                    total_orchestration_latency_ms=15.0 + i,
                    total_end_to_end_latency_ms=15.0 + i,
                )
            )

    def test_get_telemetry_status(self):
        res = self.client.get("/api/execution/telemetry/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["health_state"], "HEALTHY")
        self.assertEqual(data["total_executions"], 3)
        self.assertIn("active_configuration", data)

    def test_get_telemetry_metrics(self):
        res = self.client.get("/api/execution/telemetry/metrics")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total_executions"], 3)
        self.assertEqual(data["success_count"], 3)
        self.assertEqual(data["failure_count"], 0)

    def test_get_latency_profile_api(self):
        res = self.client.get("/api/execution/telemetry/latency")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total_samples"], 3)
        self.assertIn("end_to_end_latency", data)
        self.assertEqual(data["end_to_end_latency"]["count"], 3)

    def test_get_drift_report_api(self):
        res = self.client.get("/api/execution/telemetry/drift")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("is_drift_detected", data)

    def test_get_history_and_by_id_api(self):
        res = self.client.get("/api/execution/telemetry/history")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()), 3)

        res_id = self.client.get("/api/execution/telemetry/history/api-exec-0")
        self.assertEqual(res_id.status_code, 200)
        self.assertEqual(len(res_id.json()), 1)

        res_404 = self.client.get("/api/execution/telemetry/history/non-existent")
        self.assertEqual(res_404.status_code, 404)


if __name__ == "__main__":
    unittest.main()
