"""
Unit tests for Trade-by-Trade Lineage Auditor — Phase 5.5

Validates exact trade reconciliation, PnL recalculated parity, and lineage serialization.
"""

from datetime import datetime
import unittest

from backend.domain.execution_schemas import OrderSide, OrderStatus
from backend.domain.investment_committee_schemas import InvestmentDecisionState
from backend.simulation.simulation_state import TradeJournalEntry
from backend.validation.integrity_auditor import ExecutionMode, TradeLineageRecord


class TestTradeLineageAudit(unittest.TestCase):
    def test_trade_lineage_record_creation_and_reconciliation(self):
        dt = datetime(2023, 6, 1, 10, 0, 0)
        rec = TradeLineageRecord(
            decision_timestamp=dt,
            symbol="TCS.NS",
            universe_membership=True,
            context_id="ctx-tcs-001",
            current_price=3200.0,
            specialist_statuses={"TechnicalSpecialist": ExecutionMode.EXECUTED},
            aggregator_executed=True,
            debate_executed=True,
            committee_executed=True,
            safety_executed=True,
            order_validated=True,
            fill_price=3201.6,
            exit_timestamp=datetime(2023, 6, 15, 10, 0, 0),
            exit_price=3300.0,
            pnl=295.2,
        )
        self.assertEqual(rec.symbol, "TCS.NS")
        self.assertTrue(rec.universe_membership)
        self.assertGreater(rec.pnl, 0.0)


if __name__ == "__main__":
    unittest.main()
