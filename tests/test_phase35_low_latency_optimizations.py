import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from backend.domain.execution_decision_schemas import (
    ExecutionPipelineDecision,
    ExecutionPipelineStatus,
    ExecutionMode,
)
from backend.domain.execution_orchestration_schemas import ExecutionOrchestrationRequest, ExecutionLifecycleState
from backend.domain.broker_schemas import ExchangeSegment, OrderSide
from backend.execution.execution_orchestrator import ExecutionOrchestrator

class TestPhase35LowLatency(unittest.TestCase):
    def setUp(self):
        self.orchestrator = ExecutionOrchestrator()
        
        from backend.domain.strategy_schemas import StrategyDefinition
        from backend.execution.strategy_registry import global_strategy_registry
        
        global_strategy_registry._strategies.clear()
        
        self.strat_def = StrategyDefinition(
            strategy_id="strat-phase35",
            name="Phase 35 test strategy",
            version="1.0.0",
            allowed_instruments=["INFY.NS"],
            max_order_value=500000.0
        )
        global_strategy_registry.register(self.strat_def)
        
    def test_stale_decision_rejection_at_orchestrator(self):
        old_time = datetime.now(timezone.utc) - timedelta(seconds=6)
        
        decision = ExecutionPipelineDecision(
            decision_id="dec-stale-001",
            decision_fingerprint="fp-stale-001",
            signal_fingerprint="sig-001",
            strategy_id="strat-phase35",
            strategy_version="1.0.0",
            symbol="INFY.NS",
            exchange=ExchangeSegment.NSE,
            direction="SELL",
            quantity=50,
            estimated_value=75000.0,
            execution_mode=ExecutionMode.PAPER,
            is_authorized=True,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            audit_correlation_id="corr-stale",
            timestamp=old_time,
            gate_results=[]
        )
        
        request = ExecutionOrchestrationRequest(decision=decision, confirmation_token=None)
        
        result = self.orchestrator.submit_execution(request)
        self.assertEqual(result.state, ExecutionLifecycleState.REJECTED)
        self.assertIn("STALE", result.rejection_reason)
        
    def test_ai_authorization_cannot_bypass_safety(self):
        decision = ExecutionPipelineDecision(
            decision_id="dec-ai-001",
            decision_fingerprint="fp-ai-001",
            signal_fingerprint="sig-001",
            strategy_id="strat-phase35",
            strategy_version="1.0.0",
            symbol="INFY.NS",
            exchange=ExchangeSegment.NSE,
            direction="BUY",
            quantity=10,
            estimated_value=15000.0,
            execution_mode=ExecutionMode.PAPER,
            is_authorized=True,
            pipeline_status=ExecutionPipelineStatus.APPROVED,
            audit_correlation_id="corr-ai",
            timestamp=datetime.now(timezone.utc),
            gate_results=[]
        )
        
        request = ExecutionOrchestrationRequest(decision=decision, confirmation_token=None)
        
        start = datetime.now()
        result = self.orchestrator.submit_execution(request)
        end = datetime.now()
        
        latency_ms = (end - start).total_seconds() * 1000
        print(f"\nExecution Latency: {latency_ms:.2f} ms")
        
        self.assertEqual(result.state, ExecutionLifecycleState.COMPLETED)

if __name__ == "__main__":
    unittest.main()
