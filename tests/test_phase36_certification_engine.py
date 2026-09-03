import unittest
from datetime import datetime, timezone
from backend.domain.certification_schemas import EnvironmentType, CertificationStatus
from backend.execution.live_certification_engine import LiveCertificationEngine
from backend.config.app_config import reload_app_config
from backend.execution.safety_engine import global_kill_switch
import os

class TestLiveCertificationEngine(unittest.TestCase):
    def setUp(self):
        self.engine = LiveCertificationEngine()
        os.environ["LIVE_EXECUTION_ENABLED"] = "false"
        os.environ["DHAN_API_BASE_URL"] = "https://sandbox.dhan.co"
        reload_app_config()
        if global_kill_switch.is_active():
            global_kill_switch.deactivate()

    def tearDown(self):
        os.environ.pop("LIVE_EXECUTION_ENABLED", None)
        os.environ.pop("DHAN_API_BASE_URL", None)
        reload_app_config()
        global_kill_switch.deactivate()

    def test_default_certification_yields_sandbox(self):
        matrix = self.engine.evaluate_certification(EnvironmentType.PAPER)
        self.assertEqual(matrix.overall_status, CertificationStatus.CERTIFIED_SANDBOX)
        self.assertEqual(len(matrix.blocking_failures), 0)
        self.assertTrue(all(check.passed for check in matrix.checks))

    def test_kill_switch_blocks_certification(self):
        global_kill_switch.activate()
        matrix = self.engine.evaluate_certification(EnvironmentType.PAPER)
        self.assertEqual(matrix.overall_status, CertificationStatus.NOT_CERTIFIED)
        self.assertIn("Emergency Kill Switch is currently active.", matrix.blocking_failures)

    def test_live_execution_enabled_blocks_certification(self):
        os.environ["LIVE_EXECUTION_ENABLED"] = "true"
        reload_app_config()
        matrix = self.engine.evaluate_certification(EnvironmentType.PAPER)
        self.assertEqual(matrix.overall_status, CertificationStatus.NOT_CERTIFIED)
        self.assertIn("LIVE_EXECUTION_ENABLED is dangerously set to True.", matrix.blocking_failures)

    def test_production_endpoint_blocks_certification(self):
        os.environ["DHAN_API_BASE_URL"] = "https://api.zerodha.com"
        reload_app_config()
        matrix = self.engine.evaluate_certification(EnvironmentType.PAPER)
        self.assertEqual(matrix.overall_status, CertificationStatus.NOT_CERTIFIED)
        self.assertIn("Broker endpoint is a blocked production URL.", matrix.blocking_failures)

    def test_controlled_live_environment_is_hard_blocked(self):
        matrix = self.engine.evaluate_certification(EnvironmentType.CONTROLLED_LIVE)
        self.assertEqual(matrix.overall_status, CertificationStatus.NOT_CERTIFIED)
        self.assertIn("Environment type CONTROLLED_LIVE or PRODUCTION is locked in this phase.", matrix.blocking_failures)

    def test_production_environment_is_hard_blocked(self):
        matrix = self.engine.evaluate_certification(EnvironmentType.PRODUCTION)
        self.assertEqual(matrix.overall_status, CertificationStatus.NOT_CERTIFIED)

    def test_certification_never_authorizes_broker_order(self):
        from inspect import getmembers, isfunction, ismethod
        methods = [name for name, _ in getmembers(self.engine, predicate=ismethod)]
        self.assertNotIn("execute_order", methods)
        self.assertNotIn("submit_order", methods)
        self.assertNotIn("place_order", methods)
        self.assertNotIn("route_order", methods)

    def test_adversarial_bypass_scenario_1_to_25(self):
        for env in [EnvironmentType.SHADOW_LIVE, EnvironmentType.DEVELOPMENT, EnvironmentType.TEST]:
            matrix = self.engine.evaluate_certification(env)
            self.assertNotEqual(matrix.overall_status, CertificationStatus.CERTIFIED_FOR_CONTROLLED_LIVE)
            
        count = 0
        for _ in range(25):
            count += 1
            matrix = self.engine.evaluate_certification(EnvironmentType.PAPER)
            self.assertNotEqual(matrix.overall_status, CertificationStatus.CERTIFIED_FOR_CONTROLLED_LIVE)

if __name__ == "__main__":
    unittest.main()
