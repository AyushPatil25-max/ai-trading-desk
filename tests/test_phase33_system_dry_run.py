import unittest
from fastapi.testclient import TestClient

from backend.main import app
from backend.domain.certification_schemas import CertificationScenario, CertificationStatus
from backend.execution.system_dry_run import global_dry_run_engine

class TestPhase33SystemDryRun(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    def test_generate_certification_report(self):
        report = global_dry_run_engine.generate_certification_report()
        self.assertIsNotNone(report.report_id)
        self.assertGreater(report.scenarios_executed, 0)
        self.assertEqual(report.system_version, "Phase 33")
        self.assertTrue(report.safety_invariants_preserved)

    def test_certification_api_status(self):
        response = self.client.get("/api/system/certification/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("report_id", data)
        self.assertIn("scenarios_passed", data)
        
    def test_certification_api_dry_run(self):
        response = self.client.post("/api/system/certification/dry-run")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["system_version"], "Phase 33")
        self.assertIn("scenario_results", data)
        # Verify LIVE_EXECUTION_ENABLED is False
        self.assertFalse(data["live_execution_enabled"])

if __name__ == "__main__":
    unittest.main()
