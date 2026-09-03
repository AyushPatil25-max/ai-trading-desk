import unittest
from datetime import datetime, timezone
import uuid

from backend.execution.system_dry_run import global_dry_run_engine
from backend.domain.certification_schemas import CertificationScenario, CertificationStatus
from backend.execution.safety_engine import global_kill_switch
from backend.execution.live_arming_store import global_live_arming_store

class TestPhase33Adversarial(unittest.TestCase):
    def setUp(self):
        global_kill_switch.deactivate()
        global_live_arming_store.disarm()

    def test_kill_switch_permanently_blocks(self):
        res = global_dry_run_engine.run_scenario(CertificationScenario.KILL_SWITCH_ACTIVE)
        self.assertTrue(res.passed)
        self.assertEqual(res.final_execution_state, "REJECTED")

    def test_live_execution_permanently_blocked_when_disarmed(self):
        res = global_dry_run_engine.run_scenario(CertificationScenario.LIVE_NOT_ARMED)
        self.assertTrue(res.passed)
        self.assertEqual(res.final_execution_state, "REJECTED")
        
    def test_strategy_quarantine_blocks(self):
        res = global_dry_run_engine.run_scenario(CertificationScenario.STRATEGY_REJECTION)
        self.assertTrue(res.passed)
        self.assertEqual(res.final_execution_state, "REJECTED")
        
if __name__ == "__main__":
    unittest.main()
