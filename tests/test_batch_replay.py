"""
Unit tests for Batch Replay Engine & Scanner API — Phase 5.3

Validates multi-timestamp batch replay across universes and FastAPI endpoint routes.
"""

from datetime import datetime, timedelta, timezone
import unittest

from backend.scanner.batch_replay import BatchReplayEngine
from backend.scanner.scanner_config import ScannerConfig
from backend.scanner.universe import StockUniverse, UniverseConstituent, UniverseType
from backend.simulation.simulation_config import SimulationConfig


class TestBatchReplay(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.t0 = datetime(2024, 1, 1, 10, 0, 0)
        self.t1 = datetime(2024, 1, 2, 10, 0, 0)
        self.t2 = datetime(2024, 1, 3, 10, 0, 0)

        self.custom_constituents = [
            UniverseConstituent(symbol="TCS.NS", company_name="TCS", sector="Technology", effective_from=self.t0),
            UniverseConstituent(symbol="INFY.NS", company_name="Infosys", sector="Technology", effective_from=self.t0),
            UniverseConstituent(symbol="HDFCBANK.NS", company_name="HDFC Bank", sector="Financials", effective_from=self.t0),
        ]
        self.universe = StockUniverse(UniverseType.CUSTOM, constituents=self.custom_constituents)

        self.scanner_config = ScannerConfig(top_k=2, min_opportunity_score=20.0, min_data_quality_score=20.0)
        self.sim_config = SimulationConfig(initial_cash=100000.0, commission_rate=0.0003, slippage_rate=0.0005)

        self.batch_engine = BatchReplayEngine(
            universe=self.universe,
            scanner_config=self.scanner_config,
            simulation_config=self.sim_config,
        )

        self.dataset = {
            "TCS.NS": {
                "current_price": 3000.0,
                "ohlcv_historical": [
                    {"timestamp": self.t0.isoformat(), "close": 3000.0},
                    {"timestamp": self.t1.isoformat(), "close": 3050.0},
                    {"timestamp": self.t2.isoformat(), "close": 3100.0},
                ] * 10,
                "fundamental_data": {"pe_ratio": 22.0, "net_profit": 5000.0},
                "news_data": {},
                "institutional_data": [],
            },
            "INFY.NS": {
                "current_price": 1500.0,
                "ohlcv_historical": [
                    {"timestamp": self.t0.isoformat(), "close": 1500.0},
                    {"timestamp": self.t1.isoformat(), "close": 1520.0},
                    {"timestamp": self.t2.isoformat(), "close": 1540.0},
                ] * 10,
                "fundamental_data": {"pe_ratio": 20.0, "net_profit": 4000.0},
                "news_data": {},
                "institutional_data": [],
            },
            "HDFCBANK.NS": {
                "current_price": 1600.0,
                "ohlcv_historical": [
                    {"timestamp": self.t0.isoformat(), "close": 1600.0},
                    {"timestamp": self.t1.isoformat(), "close": 1610.0},
                    {"timestamp": self.t2.isoformat(), "close": 1620.0},
                ] * 10,
                "fundamental_data": {"pe_ratio": 18.0, "net_profit": 8000.0},
                "news_data": {},
                "institutional_data": [],
            },
        }

    async def test_batch_replay_executes_two_stage_pipeline(self):
        res = await self.batch_engine.run_batch_replay(
            self.dataset,
            start_date=self.t0,
            end_date=self.t2,
        )
        self.assertIsNotNone(res.batch_run_id)
        self.assertEqual(len(res.scan_results), 3)  # 3 timestamps evaluated

        eff = res.batch_efficiency
        self.assertEqual(eff.total_replays_count, 3)
        self.assertGreater(eff.total_screened_universe_size, 0)
        self.assertGreater(eff.total_specialist_executions_avoided, 0)

        # Simulation report produced
        self.assertIsNotNone(res.simulation_report)
        self.assertGreater(res.simulation_report.final_capital, 0.0)

    async def test_scanner_api_routes(self):
        from backend.scanner.routes import run_scanner, get_scanner_result, get_scanner_candidates, get_scanner_efficiency, run_batch_replay_endpoint, ScanRequest

        scan_out = await run_scanner(ScanRequest(universe_type=UniverseType.NIFTY_50))
        self.assertIsNotNone(scan_out.run_id)

        queried = await get_scanner_result(scan_out.run_id)
        self.assertEqual(queried.run_id, scan_out.run_id)

        candidates = await get_scanner_candidates(scan_out.run_id)
        self.assertIsInstance(candidates, list)

        eff = await get_scanner_efficiency(scan_out.run_id)
        self.assertEqual(eff.universe_size, len(StockUniverse().get_snapshot(datetime.now(timezone.utc)).constituents))

        batch_out = await run_batch_replay_endpoint()
        self.assertIsNotNone(batch_out.batch_run_id)


if __name__ == "__main__":
    unittest.main()
