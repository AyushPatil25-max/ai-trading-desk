"""
Unit tests for Historical Replay Engine — Phase 5.2

Tests chronological execution, deterministic replay guarantees, multi-symbol support,
and data quality statistics.
"""

import asyncio
from datetime import datetime
import unittest

from backend.domain.execution_schemas import (
    OrderSide,
    OrderStatus,
)
from backend.domain.investment_committee_schemas import (
    DecisionAudit,
    ExecutionPlan,
    InvestmentAction,
    InvestmentDecision,
    InvestmentDecisionState,
    InvestmentHorizon,
    InvestmentThesis,
    PositionSizing,
)
from backend.domain.schemas import MarketContext
from backend.simulation.replay_engine import HistoricalReplayEngine
from backend.simulation.report import SimulationReportBuilder
from backend.simulation.simulation_config import SimulationConfig


class TestReplayEngine(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = SimulationConfig(
            simulation_id="sim-test-1",
            initial_cash=100000.0,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 5),
            symbols=["TCS.NS", "INFY.NS"],
            commission_rate=0.0003,
            slippage_rate=0.0005,
        )
        self.engine = HistoricalReplayEngine(config=self.config)

        # Mock approved decision for TCS
        self.tcs_decision = InvestmentDecision(
            decision_id="dec-tcs-1",
            context_id="ctx-tcs-1",
            symbol="TCS.NS",
            state=InvestmentDecisionState.APPROVE,
            thesis=InvestmentThesis(synthesis="Bullish breakout"),
            execution_plan=ExecutionPlan(
                action=InvestmentAction.BUY,
                horizon=InvestmentHorizon.SWING,
                position_sizing=PositionSizing(is_available=True, recommended_size_pct=10.0),
            ),
            audit_trail=DecisionAudit(deterministic_state=InvestmentDecisionState.APPROVE),
            confidence=0.85,
        )

        self.dataset = {
            "TCS.NS": {
                "current_price": 3000.0,
                "ohlcv_historical": [
                    {"timestamp": "2024-01-01 10:00:00", "close": 3000.0},
                    {"timestamp": "2024-01-02 10:00:00", "close": 3050.0},
                    {"timestamp": "2024-01-03 10:00:00", "close": 3100.0},
                ],
                "fundamental_data": {},  # Missing fundamental data
                "news_data": {},         # Missing news data
                "institutional_data": [],# Missing institutional data
                "mock_decision": self.tcs_decision,
            },
            "INFY.NS": {
                "current_price": 1500.0,
                "ohlcv_historical": [
                    {"timestamp": "2024-01-01 10:00:00", "close": 1500.0},
                    {"timestamp": "2024-01-02 10:00:00", "close": 1520.0},
                    {"timestamp": "2024-01-03 10:00:00", "close": 1540.0},
                ],
            },
        }

    async def test_chronological_replay_generates_equity_curve_and_trades(self):
        report = await self.engine.run(self.dataset)
        self.assertEqual(report.simulation_id, "sim-test-1")
        self.assertEqual(len(report.equity_curve), 3)  # 3 unique timestamps (Jan 1, 2, 3)
        self.assertGreater(len(report.trade_journal), 0)

        # First trade should be TCS BUY
        t1 = report.trade_journal[0]
        self.assertEqual(t1.symbol, "TCS.NS")
        self.assertEqual(t1.side, OrderSide.BUY)
        self.assertEqual(t1.order_status, OrderStatus.FILLED)

        # Verify portfolio equity increased as TCS price rose from 3000 to 3100
        self.assertGreater(report.final_capital, 100000.0)
        self.assertGreater(report.metrics.total_return_pct, 0.0)

    async def test_data_quality_statistics_tracked_accurately(self):
        report = await self.engine.run(self.dataset)
        dq = report.data_quality
        self.assertEqual(dq.contexts_processed, 6)  # 2 symbols * 3 timestamps
        self.assertGreater(dq.missing_fundamentals_count, 0)
        self.assertGreater(dq.missing_news_count, 0)

    async def test_repeated_simulation_determinism(self):
        report1 = await self.engine.run(self.dataset)
        report2 = await self.engine.run(self.dataset)

        self.assertEqual(report1.final_capital, report2.final_capital)
        self.assertEqual(report1.metrics.total_return_pct, report2.metrics.total_return_pct)
        self.assertEqual(len(report1.trade_journal), len(report2.trade_journal))
        self.assertEqual(len(report1.equity_curve), len(report2.equity_curve))

    async def test_empty_dataset_handling(self):
        report = await self.engine.run({})
        self.assertEqual(report.final_capital, 100000.0)
        self.assertEqual(report.metrics.total_return_pct, 0.0)
        self.assertEqual(len(report.trade_journal), 0)

    async def test_markdown_report_formatting(self):
        report = await self.engine.run(self.dataset)
        md = SimulationReportBuilder.to_markdown(report)
        self.assertIn("# Simulation Report:", md)
        self.assertIn("Total Return", md)
        self.assertIn("TCS.NS", md)


if __name__ == "__main__":
    unittest.main()
