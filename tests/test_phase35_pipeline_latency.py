import unittest
from datetime import datetime, timezone, timedelta
import time
from unittest.mock import patch, MagicMock

from backend.domain.execution_decision_schemas import ExecutionMode, ExecutionPipelineRequest
from backend.domain.execution_orchestration_schemas import ExecutionLifecycleState
from backend.execution.execution_decision_pipeline import ExecutionDecisionEngine
from backend.domain.strategy_schemas import StrategyDefinition, StrategySignal, SignalDirection
from backend.execution.strategy_registry import global_strategy_registry

class TestPipelineLatency(unittest.TestCase):
    def test_pipeline_latency(self):
        global_strategy_registry._strategies.clear()
        
        strat_def = StrategyDefinition(
            strategy_id="strat-phase35",
            name="Phase 35 test strategy",
            version="1.0.0",
            allowed_instruments=["INFY.NS"],
            max_order_value=500000.0,
        )
        global_strategy_registry.register(strat_def)
        
        engine = ExecutionDecisionEngine()
        
        req = ExecutionPipelineRequest(
            strategy_id="strat-phase35",
            strategy_version="1.0.0",
            symbol="INFY.NS",
            direction="BUY",
            quantity=10,
            target_price=1500.0,
            confidence_score=0.95,
            execution_mode=ExecutionMode.PAPER
        )
        
        with patch("backend.execution.execution_decision_pipeline.global_live_readiness_engine") as mock_read, \
             patch("backend.execution.execution_decision_pipeline.global_live_arming_store") as mock_arm:
            mock_read.evaluate_readiness.return_value = MagicMock(is_ready=True)
            mock_arm.get_status.return_value = MagicMock(is_armed=True)
            
            # Warm up
            engine.evaluate_pipeline(req)
            
            start = time.perf_counter_ns()
            res = engine.evaluate_pipeline(req)
            end = time.perf_counter_ns()
            
            latency = (end - start) / 1_000_000.0
            print(f"\nPipeline Latency: {latency:.2f} ms")

if __name__ == "__main__":
    unittest.main()
