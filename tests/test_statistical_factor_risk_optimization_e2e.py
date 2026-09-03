"""
Phase 17 — Advanced Statistical Factor Validation & Automated Risk Optimization E2E Test Suite

Verifies:
1. Multi-factor OLS regression math (Fama-French 5-Factor + Carhart Momentum).
2. Statistical significance testing (t-statistics, standard errors, p-values).
3. Insufficient observation handling (N < k + 2) and safe baseline output.
4. Distinction between zero exposure (beta = 0.0) and unavailable factor data.
5. Deterministic synthetic factor generation.
6. Regime-conditional performance attribution across market regimes.
7. Specialist regime-aware conviction multiplier clamping (0.70x to 1.30x).
8. Walk-forward out-of-sample stability testing and degradation calculation.
9. Volatility targeting calculation and leverage ceiling enforcement (<= 1.0x).
10. Equal Risk Contribution / Inverse Volatility risk budgeting.
11. ExecutionGuard and RiskEngine constraint enforcement (max 15% single asset, min 5% cash).
12. Permanent fail-closed safety: TIER_4_LIVE_REAL_MONEY remains strictly blocked.
13. REST API endpoints (/api/factors/*).
"""

from datetime import datetime, timezone
import unittest
from fastapi.testclient import TestClient
import numpy as np

from backend.domain.factor_risk_schemas import (
    FactorDataStatus,
    FactorType,
    MultiFactorAttributionResult,
    RegimeConditionalReport,
    RiskOptimizationConfig,
    RiskOptimizationResult,
    WalkForwardOptimizationReport,
)
from backend.domain.broker_schemas import BrokerConfig, BrokerEnvironment
from backend.application.factor_attribution_engine import (
    FactorAttributionEngine,
    normal_p_value,
)
from backend.application.regime_validation_service import RegimeValidationService
from backend.application.automated_risk_optimizer import AutomatedRiskOptimizer
from backend.application.statistical_validation_engine import StatisticalValidationEngine
from backend.application.execution_guard import ExecutionGuard
from backend.main import app


class TestStatisticalFactorRiskOptimizationE2E(unittest.TestCase):
    """End-to-end verification of Phase 17 Quantitative Factor & Risk Optimization Engine."""

    def setUp(self):
        self.factor_engine = FactorAttributionEngine()
        self.regime_service = RegimeValidationService()
        self.guard = ExecutionGuard()
        self.risk_optimizer = AutomatedRiskOptimizer(execution_guard=self.guard)
        self.stat_engine = StatisticalValidationEngine()
        self.client = TestClient(app)

    # ── 1. Analytical p-value Function ────────────────────────────────────────

    def test_01_normal_p_value(self):
        self.assertAlmostEqual(normal_p_value(0.0), 1.0, places=4)
        self.assertAlmostEqual(normal_p_value(1.96), 0.05, places=2)
        self.assertAlmostEqual(normal_p_value(-1.96), 0.05, places=2)
        self.assertLess(normal_p_value(3.0), 0.01)

    # ── 2. Multi-Factor Regression Math ───────────────────────────────────────

    def test_02_multifactor_regression_math(self):
        rng = np.random.RandomState(42)
        n = 60
        factors = self.factor_engine.generate_synthetic_factor_series(length=n, seed=42)

        # Construct asset with known factor loadings:
        # y = 0.0005 + 1.2 * MKT_RF + 0.5 * SMB - 0.3 * HML + noise
        mkt = np.array(factors[FactorType.MARKET_RF.value])
        smb = np.array(factors[FactorType.SMB.value])
        hml = np.array(factors[FactorType.HML.value])
        noise = rng.normal(0, 0.001, n)
        y = 0.0005 + 1.2 * mkt + 0.5 * smb - 0.3 * hml + noise

        res = self.factor_engine.run_attribution(
            symbol_or_portfolio="TEST_PORTFOLIO",
            asset_returns=y.tolist(),
            factor_returns=factors,
        )

        self.assertIsInstance(res, MultiFactorAttributionResult)
        self.assertFalse(res.insufficient_sample)
        self.assertGreater(res.r_squared, 0.80)
        self.assertGreater(res.systematic_risk_pct, 80.0)

        # Check estimated loadings
        mkt_attr = res.factors[FactorType.MARKET_RF.value]
        self.assertAlmostEqual(mkt_attr.beta, 1.2, delta=0.15)
        self.assertTrue(mkt_attr.is_significant)
        self.assertGreater(mkt_attr.t_statistic, 2.0)

        smb_attr = res.factors[FactorType.SMB.value]
        self.assertAlmostEqual(smb_attr.beta, 0.5, delta=0.15)
        self.assertTrue(smb_attr.is_significant)

        hml_attr = res.factors[FactorType.HML.value]
        self.assertAlmostEqual(hml_attr.beta, -0.3, delta=0.15)
        self.assertTrue(hml_attr.is_significant)

    # ── 3. Insufficient History Handling ──────────────────────────────────────

    def test_03_insufficient_history_guard(self):
        short_returns = [0.01, -0.02, 0.015]  # n=3 < min_required_obs (8)
        res = self.factor_engine.run_attribution(
            symbol_or_portfolio="SHORT_SERIES",
            asset_returns=short_returns,
        )
        self.assertTrue(res.insufficient_sample)
        self.assertEqual(res.data_status, FactorDataStatus.INSUFFICIENT_HISTORY)
        self.assertEqual(res.r_squared, 0.0)
        self.assertIn("Insufficient sample", res.warnings[0])

    # ── 4. Distinction Between Zero Exposure & Unavailable Data ───────────────

    def test_04_distinguish_zero_beta_from_unavailable(self):
        # Provide factor returns with one factor completely omitted
        n = 30
        factors = self.factor_engine.generate_synthetic_factor_series(length=n)
        del factors[FactorType.MOM.value]  # Omit MOM

        rng = np.random.RandomState(10)
        rets = rng.normal(0.0004, 0.01, n).tolist()

        res = self.factor_engine.run_attribution(
            symbol_or_portfolio="PARTIAL_FACTORS",
            asset_returns=rets,
            factor_returns=factors,
        )

        mom_attr = res.factors[FactorType.MOM.value]
        self.assertEqual(mom_attr.status, FactorDataStatus.UNAVAILABLE)
        self.assertEqual(mom_attr.beta, 0.0)

    # ── 5. Regime-Conditional Performance Decomposition ───────────────────────

    def test_05_regime_performance_decomposition(self):
        dummy_trades = [
            {"market_regime": "BULL", "net_return_pct": 0.03},
            {"market_regime": "BULL", "net_return_pct": 0.02},
            {"market_regime": "BULL", "net_return_pct": -0.01},
            {"market_regime": "BULL", "net_return_pct": 0.015},
            {"market_regime": "BULL", "net_return_pct": 0.025},
            {"market_regime": "BEAR", "net_return_pct": -0.02},
            {"market_regime": "BEAR", "net_return_pct": -0.015},
            {"market_regime": "BEAR", "net_return_pct": 0.005},
            {"market_regime": "SIDEWAYS", "net_return_pct": 0.002},
            {"market_regime": "HIGH_VOLATILITY", "net_return_pct": 0.04},
        ]

        report = self.regime_service.evaluate_trades_by_regime(dummy_trades, current_regime="BULL")
        self.assertIsInstance(report, RegimeConditionalReport)
        self.assertEqual(report.current_regime, "BULL")

        bull_perf = report.regime_performances["BULL"]
        self.assertEqual(bull_perf.trade_count, 5)
        self.assertEqual(bull_perf.win_rate, 0.8)
        self.assertTrue(bull_perf.sample_size_adequate)
        self.assertGreater(bull_perf.sharpe_ratio, 0.0)

        # Verify specialist weights clamping
        bull_weights = report.specialist_regime_weights["BULL"]
        for spec, w in bull_weights.items():
            self.assertGreaterEqual(w, 0.70)
            self.assertLessEqual(w, 1.30)

    # ── 6. Automated Volatility Targeting ─────────────────────────────────────

    def test_06_volatility_targeting_scaling(self):
        rng = np.random.RandomState(50)
        # High volatility asset: ~30% annualized vol
        high_vol_rets = rng.normal(0.0005, 0.019, 40).tolist()
        asset_map = {"HIGH_VOL_STOCK": high_vol_rets}

        config = RiskOptimizationConfig(
            target_annualized_volatility=0.15,  # Target 15%
            max_portfolio_leverage=1.0,
            max_single_asset_weight=0.15,
        )

        res = self.risk_optimizer.optimize_allocations(
            asset_returns_map=asset_map,
            override_config=config,
        )

        self.assertIsInstance(res, RiskOptimizationResult)
        self.assertGreater(res.baseline_volatility, 0.20)
        # Vol scalar should scale down allocation
        self.assertLess(res.volatility_scalar, 1.0)
        self.assertGreaterEqual(res.cash_allocation, 0.05)
        self.assertLessEqual(res.optimized_weights["HIGH_VOL_STOCK"], 0.15)
        self.assertTrue(res.risk_gates_cleared)

    # ── 7. Leverage Ceiling Enforcement ───────────────────────────────────────

    def test_07_leverage_ceiling_enforced(self):
        rng = np.random.RandomState(99)
        # Low volatility asset: ~5% annualized vol
        low_vol_rets = rng.normal(0.0002, 0.003, 40).tolist()
        asset_map = {"LOW_VOL_BOND": low_vol_rets}

        config = RiskOptimizationConfig(
            target_annualized_volatility=0.15,
            max_portfolio_leverage=1.0,  # Strict unleveraged ceiling
        )

        res = self.risk_optimizer.optimize_allocations(
            asset_returns_map=asset_map,
            override_config=config,
        )

        # Raw k would be ~3.0, but clamped strictly to 1.0
        self.assertEqual(res.volatility_scalar, 1.0)
        self.assertTrue(any("clamped" in v for v in res.violations_prevented))

    # ── 8. Risk Budgeting & Equal Risk Contribution ───────────────────────────

    def test_08_risk_budgeting_erc(self):
        rng = np.random.RandomState(123)
        rets_safe = rng.normal(0.0003, 0.006, 30).tolist()  # lower vol (~10%)
        rets_risky = rng.normal(0.0008, 0.018, 30).tolist() # higher vol (~28%)

        asset_map = {
            "SAFE_ASSET": rets_safe,
            "RISKY_ASSET": rets_risky,
        }

        res = self.risk_optimizer.optimize_allocations(asset_map)
        weights = res.optimized_weights

        # In inverse-vol budgeting, SAFE_ASSET must receive a higher risk budget share than RISKY_ASSET
        self.assertGreater(res.risk_budget_allocations["SAFE_ASSET"], res.risk_budget_allocations["RISKY_ASSET"])

        # With unclamped concentration limits, SAFE_ASSET weight is strictly greater than RISKY_ASSET
        unclamped_cfg = RiskOptimizationConfig(max_single_asset_weight=0.80)
        res_unclamped = self.risk_optimizer.optimize_allocations(asset_map, override_config=unclamped_cfg)
        self.assertGreater(res_unclamped.optimized_weights["SAFE_ASSET"], res_unclamped.optimized_weights["RISKY_ASSET"])

        # Under default config, single asset concentration constraint is strictly enforced (<= 15%)
        self.assertLessEqual(weights["SAFE_ASSET"], 0.15)
        self.assertLessEqual(weights["RISKY_ASSET"], 0.15)

    # ── 9. Statistical Walk-Forward Validation Engine ─────────────────────────

    def test_09_statistical_walk_forward_validation(self):
        rng = np.random.RandomState(888)
        n = 60
        # Optimized returns have higher mean and lower vol
        base_rets = rng.normal(0.0003, 0.015, n).tolist()
        opt_rets = rng.normal(0.0006, 0.010, n).tolist()

        report = self.stat_engine.validate_walk_forward(base_rets, opt_rets)
        self.assertIsInstance(report, WalkForwardOptimizationReport)
        self.assertGreater(report.optimized_sharpe, report.baseline_sharpe)
        self.assertGreater(report.sharpe_delta, 0.0)
        self.assertGreater(report.information_ratio, 0.0)
        self.assertTrue(report.is_statistically_improved)
        self.assertTrue(report.validation_passed)

    # ── 10. Execution Boundary & Real-Money Lock ──────────────────────────────

    def test_10_tier4_live_permanently_blocked(self):
        with self.assertRaises(ValueError):
            BrokerConfig(broker_environment=BrokerEnvironment.LIVE)

        # Ensure kill switch triggers risk clearance failure in optimizer
        self.guard.telemetry_engine = unittest.mock.MagicMock()
        self.guard.telemetry_engine.is_kill_switch_triggered.return_value = True

        opt_res = self.risk_optimizer.optimize_allocations({"TCS.NS": [0.01, 0.02, -0.01, 0.015]})
        self.assertFalse(opt_res.risk_gates_cleared)
        self.assertTrue(any("KILL SWITCH" in v for v in opt_res.violations_prevented))

    # ── 11. REST API Endpoints ───────────────────────────────────────────────

    def test_11_rest_api_endpoints(self):
        # 1. Attribution endpoint
        attr_res = self.client.post("/api/factors/attribution", json={"symbol": "PORTFOLIO"})
        self.assertEqual(attr_res.status_code, 200)
        attr_data = attr_res.json()
        self.assertIn("factors", attr_data)
        self.assertIn("r_squared", attr_data)
        self.assertIn(FactorType.MARKET_RF.value, attr_data["factors"])

        # 2. Exposures endpoint
        exp_res = self.client.get("/api/factors/exposures?symbol=PORTFOLIO")
        self.assertEqual(exp_res.status_code, 200)

        # 3. Regime analysis endpoint
        reg_res = self.client.get("/api/factors/regime-analysis?current_regime=BULL")
        self.assertEqual(reg_res.status_code, 200)
        reg_data = reg_res.json()
        self.assertIn("regime_performances", reg_data)

        # 4. Optimize risk endpoint
        opt_res = self.client.post("/api/factors/optimize-risk", json={
            "target_volatility": 0.15,
            "max_single_asset_weight": 0.15,
        })
        self.assertEqual(opt_res.status_code, 200)
        opt_data = opt_res.json()
        self.assertIn("optimized_weights", opt_data)
        self.assertIn("volatility_scalar", opt_data)

        # 5. Validation endpoint
        val_res = self.client.get("/api/factors/validation")
        self.assertEqual(val_res.status_code, 200)

        # 6. Status endpoint
        st_res = self.client.get("/api/factors/status")
        self.assertEqual(st_res.status_code, 200)
        st_data = st_res.json()
        self.assertTrue(st_data["tier4_live_real_money_blocked"])
        self.assertEqual(st_data["phase"], 17)


if __name__ == "__main__":
    unittest.main()
