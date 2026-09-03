"""
Phase 30 — Unit & Integration Tests for Paper vs Live Execution Paths

Covers:
- Strict architectural separation between PAPER and LIVE execution paths
- PAPER path: Strategy -> Governance -> Risk -> Preflight -> Paper Authorization
- LIVE path: Strategy -> Governance -> Risk -> Preflight -> Readiness -> Arming -> Safety Gate -> Duplicate Check -> Confirmation -> Final Authorization
- Fail-closed behavior on missing live prerequisites
- Rejection of live execution without confirmation token
- Preservation of paper trading functionality
"""

from datetime import datetime, timezone
import unittest

from backend.domain.broker_schemas import (
    ExchangeSegment,
    OrderRequest as BrokerOrderRequestDomain,
    OrderSide as BrokerOrderSide,
    OrderType as BrokerOrderType,
    ProductType as BrokerProductType,
)
from backend.domain.execution_decision_schemas import (
    ExecutionMode,
    ExecutionPipelineRequest,
    ExecutionPipelineStatus,
    PipelineGateName,
)
from backend.domain.strategy_schemas import (
    StrategyDefinition,
    StrategyStatus,
)
from backend.execution.strategy_registry import global_strategy_registry
from backend.execution.strategy_governance import global_strategy_governance_engine
from backend.execution.execution_decision_pipeline import ExecutionDecisionEngine
from backend.execution.live_arming_store import global_live_arming_store
from backend.application.confirmation_store import (
    compute_order_fingerprint,
    global_confirmation_store,
)
from backend.execution.order_tracker import global_order_tracker


class TestExecutionPaperAndLivePaths(unittest.TestCase):

    def setUp(self):
        self.engine = ExecutionDecisionEngine()
        global_strategy_registry.clear()
        global_strategy_governance_engine.clear()
        global_live_arming_store.disarm()
        global_order_tracker.clear()

        # Register standard active strategy
        self.strat = StrategyDefinition(
            strategy_id="path_strat",
            name="Path Test Strategy",
            version="1.0.0",
            status=StrategyStatus.ACTIVE,
            allowed_instruments=["*"],
            allowed_exchanges=["NSE"],
            max_position_size=200.0,
            max_order_value=1000000.0,
        )
        global_strategy_registry.register(self.strat)

    def test_paper_path_authorizes_without_live_arming(self):
        # Live is disarmed
        self.assertFalse(global_live_arming_store.get_status().is_armed)

        now = datetime.now(timezone.utc)
        req = ExecutionPipelineRequest(
            strategy_id="path_strat",
            strategy_version="1.0.0",
            symbol="INFY.NS",
            exchange="NSE",
            direction="BUY",
            quantity=50.0,
            target_price=1500.0,
            execution_mode=ExecutionMode.PAPER,
            market_data_timestamp=now,
        )

        decision = self.engine.evaluate_pipeline(req, current_time=now)
        self.assertEqual(decision.pipeline_status, ExecutionPipelineStatus.APPROVED)
        self.assertTrue(decision.is_authorized)
        self.assertEqual(decision.execution_mode, ExecutionMode.PAPER)

    def test_live_path_blocks_when_disarmed(self):
        now = datetime.now(timezone.utc)
        req = ExecutionPipelineRequest(
            strategy_id="path_strat",
            strategy_version="1.0.0",
            symbol="INFY.NS",
            exchange="NSE",
            direction="BUY",
            quantity=50.0,
            target_price=1500.0,
            execution_mode=ExecutionMode.LIVE,
            market_data_timestamp=now,
        )

        decision = self.engine.evaluate_pipeline(req, current_time=now)
        self.assertFalse(decision.is_authorized)
        self.assertIn(decision.pipeline_status, (ExecutionPipelineStatus.BLOCKED, ExecutionPipelineStatus.NOT_READY))

    def test_live_path_blocks_when_confirmation_token_missing(self):
        # Arm live trading
        global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)
        self.assertTrue(global_live_arming_store.get_status().is_armed)

        now = datetime.now(timezone.utc)
        req = ExecutionPipelineRequest(
            strategy_id="path_strat",
            strategy_version="1.0.0",
            symbol="INFY.NS",
            exchange="NSE",
            direction="BUY",
            quantity=50.0,
            target_price=1500.0,
            execution_mode=ExecutionMode.LIVE,
            confirmation_token=None,  # Missing confirmation token
            market_data_timestamp=now,
        )

        decision = self.engine.evaluate_pipeline(req, current_time=now)
        self.assertFalse(decision.is_authorized)
        self.assertIn(decision.pipeline_status, (ExecutionPipelineStatus.BLOCKED, ExecutionPipelineStatus.NOT_READY))

    def test_live_path_blocks_on_duplicate_order(self):
        now = datetime.now(timezone.utc)
        # Seed duplicate in order tracker
        broker_order = BrokerOrderRequestDomain(
            symbol="INFY.NS",
            side=BrokerOrderSide.BUY,
            quantity=50,
            order_type=BrokerOrderType.LIMIT,
            price=1500.0,
            exchange_segment=ExchangeSegment.NSE,
            product_type=BrokerProductType.CNC,
            request_id="dup-req-1",
        )
        fp = compute_order_fingerprint(broker_order)
        global_order_tracker.record_submission(fp, "dup-req-1", order=broker_order)

        # Arm live trading
        global_live_arming_store.arm(acknowledgement=True, duration_seconds=300)

        # Generate confirmation token
        tok_rec = global_confirmation_store.create_confirmation(
            order_request=broker_order,
            estimated_order_value=75000.0,
        )

        req = ExecutionPipelineRequest(
            strategy_id="path_strat",
            strategy_version="1.0.0",
            symbol="INFY.NS",
            exchange="NSE",
            direction="BUY",
            quantity=50.0,
            target_price=1500.0,
            execution_mode=ExecutionMode.LIVE,
            confirmation_token=tok_rec.confirmation_id,
            market_data_timestamp=now,
        )

        decision = self.engine.evaluate_pipeline(req, current_time=now)
        self.assertFalse(decision.is_authorized)
        self.assertIn(decision.pipeline_status, (ExecutionPipelineStatus.BLOCKED, ExecutionPipelineStatus.NOT_READY))


if __name__ == "__main__":
    unittest.main()
