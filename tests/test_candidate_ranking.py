"""
Unit tests for Candidate Ranking Engine — Phase 5.3

Validates individual domain scoring, evidence availability weighting,
data quality penalty, top-k selection, and sector concentration limits.
"""

import unittest

from backend.scanner.ranking import CandidateRankingEngine, CandidateScore
from backend.scanner.scanner_config import ScannerConfig


class TestCandidateRanking(unittest.TestCase):
    def setUp(self):
        self.config = ScannerConfig(
            top_k=3,
            min_opportunity_score=40.0,
            min_data_quality_score=30.0,
            max_candidates_per_sector=2,
            data_quality_penalty_weight=0.30,
        )
        self.engine = CandidateRankingEngine(self.config)

    def test_technical_score_calculation(self):
        # Bullish setup: price > EMA20 > EMA50, RSI = 60
        data = {
            "current_price": 1000.0,
            "ohlcv_historical": [{"close": 1000.0}] * 20,
            "technical_indicators": {
                "ema_20": 950.0,
                "ema_50": 900.0,
                "rsi_14": 60.0,
            },
        }
        score = self.engine.calculate_technical_score(data)
        self.assertIsNotNone(score)
        self.assertGreater(score, 70.0)

    def test_fundamental_score_calculation(self):
        data = {
            "fundamental_data": {
                "net_profit": 10000.0,
                "revenue_growth": 0.20,
                "roe": 0.22,
            }
        }
        score = self.engine.calculate_fundamental_score(data)
        self.assertIsNotNone(score)
        self.assertGreater(score, 75.0)

    def test_data_quality_penalty_reduces_effective_score(self):
        # Candidate with rich data
        data_rich = {
            "current_price": 500.0,
            "ohlcv_historical": [{"close": 500.0}] * 20,
            "technical_indicators": {"ema_20": 480.0, "ema_50": 460.0, "rsi_14": 55.0},
            "fundamental_data": {"pe_ratio": 20.0, "net_profit": 1000.0, "revenue_growth": 0.15, "roe": 0.18},
            "news_data": {"articles": [{"title": "Good News"}]},
            "institutional_data": [],
        }
        score_rich = self.engine.score_candidate("RICH.NS", "Technology", data_rich)

        # Candidate with only OHLCV (sparse data)
        data_sparse = {
            "current_price": 500.0,
            "ohlcv_historical": [{"close": 500.0}] * 20,
        }
        score_sparse = self.engine.score_candidate("SPARSE.NS", "Technology", data_sparse)

        self.assertGreater(score_rich.data_quality_score, score_sparse.data_quality_score)
        # Even with similar baseline signals, rich data should have higher effective opportunity score
        self.assertGreater(score_rich.effective_opportunity_score, score_sparse.effective_opportunity_score)

    def test_sector_concentration_limits_applied(self):
        candidates = [
            CandidateScore(symbol="TECH_1.NS", sector="Technology", effective_opportunity_score=90.0, data_quality_score=80.0),
            CandidateScore(symbol="TECH_2.NS", sector="Technology", effective_opportunity_score=85.0, data_quality_score=80.0),
            CandidateScore(symbol="TECH_3.NS", sector="Technology", effective_opportunity_score=80.0, data_quality_score=80.0),
            CandidateScore(symbol="FIN_1.NS", sector="Financials", effective_opportunity_score=75.0, data_quality_score=80.0),
        ]
        # max_candidates_per_sector = 2 -> TECH_3 must be rejected due to sector concentration limit
        res = self.engine.rank_and_select(candidates)
        selected_symbols = [c.symbol for c in res.selected_candidates]

        self.assertEqual(len(selected_symbols), 3)  # Top 3
        self.assertIn("TECH_1.NS", selected_symbols)
        self.assertIn("TECH_2.NS", selected_symbols)
        self.assertIn("FIN_1.NS", selected_symbols)
        self.assertNotIn("TECH_3.NS", selected_symbols)

        # TECH_3 status should reflect sector concentration rejection
        tech_3 = next(c for c in res.rejected_candidates if c.symbol == "TECH_3.NS")
        self.assertEqual(tech_3.selection_status, "REJECTED_SECTOR_CONCENTRATION")

    def test_top_k_selection_cap(self):
        candidates = [
            CandidateScore(symbol=f"STOCK_{i}.NS", sector=f"Sector_{i}", effective_opportunity_score=80.0 - i, data_quality_score=80.0)
            for i in range(10)
        ]
        # top_k = 3
        res = self.engine.rank_and_select(candidates)
        self.assertEqual(len(res.selected_candidates), 3)
        self.assertEqual(len(res.rejected_candidates), 7)


if __name__ == "__main__":
    unittest.main()
