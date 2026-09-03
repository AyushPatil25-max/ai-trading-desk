import os
import unittest
from unittest.mock import patch, MagicMock

from backend.config.app_config import AppConfig, get_app_config, reload_app_config
from backend.application.lifecycle_manager import LifecycleManager
from backend.execution.live_arming_store import global_live_arming_store
from backend.domain.certification_schemas import CertificationScenario
from backend.execution.system_dry_run import global_dry_run_engine

class TestPhase34ProductionHardening(unittest.TestCase):
    
    def test_live_execution_flag_strict_parsing(self):
        # Must only parse exactly "true" (case-insensitive) as True
        
        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "true"}, clear=True):
            config = reload_app_config()
            self.assertTrue(config.live_execution_enabled)
            
        with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": "True"}, clear=True):
            config = reload_app_config()
            self.assertTrue(config.live_execution_enabled)
            
        # These should all fail closed (eval to False)
        bad_flags = ["1", "yes", "on", "t", ""]
        for flag in bad_flags:
            with patch.dict(os.environ, {"LIVE_EXECUTION_ENABLED": flag}, clear=True):
                config = reload_app_config()
                self.assertFalse(config.live_execution_enabled, f"Failed closed for flag '{flag}'")
                
    def test_lifecycle_startup_clears_live_arm(self):
        # Manually arm it
        global_live_arming_store.arm(True, 300, "test_reason", "test_operator")
        self.assertTrue(global_live_arming_store.is_currently_armed())
        
        # Run startup sequence
        LifecycleManager.startup_sequence()
        
        # Should be disarmed
        self.assertFalse(global_live_arming_store.is_currently_armed())
        
    def test_dry_run_certification_new_scenarios(self):
        scenarios = [
            CertificationScenario.CORRUPTED_CONFIGURATION,
            CertificationScenario.BROKER_AUTH_FAILURE,
            CertificationScenario.STALE_MARKET_DATA,
            CertificationScenario.RESTART_LIVE_ARM_CLEARED,
            CertificationScenario.DUPLICATE_WORKER
        ]
        
        for scenario in scenarios:
            res = global_dry_run_engine.run_scenario(scenario)
            self.assertTrue(res.passed, f"Scenario {scenario.value} failed: {res.error_message}")
            for assertion in res.assertions:
                self.assertTrue(assertion.passed, f"Assertion {assertion.assertion_name} failed in {scenario.value}")

if __name__ == '__main__':
    unittest.main()



