"""
Phase 17 — Multi-Factor Attribution Engine

Authoritative quantitative attribution engine implementing the Fama-French 5-factor
model (Market/RF, SMB, HML, RMW, CMA) plus Carhart Momentum (MOM).
Calculates multivariate factor betas, Jensen's alpha, t-statistics, p-values,
R-squared, and variance decomposition using deterministic Python / NumPy operations.
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from backend.domain.factor_risk_schemas import (
    FactorDataStatus,
    FactorType,
    MultiFactorAttributionResult,
    SingleFactorAttribution,
)


STANDARD_FACTORS = [
    FactorType.MARKET_RF,
    FactorType.SMB,
    FactorType.HML,
    FactorType.RMW,
    FactorType.CMA,
    FactorType.MOM,
]


def normal_p_value(t_stat: float) -> float:
    """
    Compute two-tailed p-value from t-statistic using standard normal error function.
    Deterministic, pure-Python calculation without external scipy dependency.
    """
    if math.isnan(t_stat) or math.isinf(t_stat):
        return 1.0
    abs_t = abs(t_stat)
    # p = erfc(abs_t / sqrt(2))
    return float(math.erfc(abs_t / math.sqrt(2.0)))


class FactorAttributionEngine:
    """
    Multivariate OLS factor decomposition engine for asset and portfolio returns.
    Pure Python & NumPy authority.
    """

    def __init__(self, risk_free_annual_rate: float = 0.065) -> None:
        self.risk_free_annual_rate = risk_free_annual_rate
        self.daily_rf = (1.0 + risk_free_annual_rate) ** (1.0 / 252.0) - 1.0
        self._cached_results: Dict[str, MultiFactorAttributionResult] = {}

    def generate_synthetic_factor_series(
        self,
        length: int = 60,
        benchmark_returns: Optional[List[float]] = None,
        seed: int = 42,
    ) -> Dict[str, List[float]]:
        """
        Deterministic fallback synthetic factor generator derived from benchmark
        and standard stylised statistical distributions when external style factor feeds are absent.
        """
        rng = np.random.RandomState(seed)
        if benchmark_returns and len(benchmark_returns) >= length:
            mkt = np.array(benchmark_returns[:length])
        else:
            # Baseline market with drift + vol
            mkt = rng.normal(0.0004, 0.012, length)

        mkt_rf = mkt - self.daily_rf
        smb = rng.normal(0.0001, 0.006, length)
        hml = rng.normal(0.00005, 0.007, length)
        rmw = rng.normal(0.00015, 0.005, length)
        cma = rng.normal(0.00008, 0.004, length)
        mom = rng.normal(0.0002, 0.009, length)

        return {
            FactorType.MARKET_RF.value: mkt_rf.tolist(),
            FactorType.SMB.value: smb.tolist(),
            FactorType.HML.value: hml.tolist(),
            FactorType.RMW.value: rmw.tolist(),
            FactorType.CMA.value: cma.tolist(),
            FactorType.MOM.value: mom.tolist(),
        }

    def run_attribution(
        self,
        symbol_or_portfolio: str,
        asset_returns: List[float],
        factor_returns: Optional[Dict[str, List[float]]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> MultiFactorAttributionResult:
        """
        Perform multivariate linear regression of asset excess returns on factor returns.
        Handles missing data, short histories, and distinguishes missing factors from zero exposure.
        """
        now = datetime.now(timezone.utc)
        st_dt = start_date or now
        end_dt = end_date or now
        n = len(asset_returns)

        # ── Insufficient History Guard ─────────────────────────────────────────
        min_required_obs = len(STANDARD_FACTORS) + 2
        if n < min_required_obs:
            empty_factors = {
                f.value: SingleFactorAttribution(
                    factor_name=f.value,
                    factor_type=f,
                    beta=0.0,
                    status=FactorDataStatus.INSUFFICIENT_HISTORY,
                )
                for f in STANDARD_FACTORS
            }
            return MultiFactorAttributionResult(
                symbol_or_portfolio=symbol_or_portfolio,
                start_date=st_dt,
                end_date=end_dt,
                observation_count=n,
                alpha=0.0,
                r_squared=0.0,
                adjusted_r_squared=0.0,
                factors=empty_factors,
                systematic_risk_pct=0.0,
                specific_risk_pct=100.0,
                insufficient_sample=True,
                data_status=FactorDataStatus.INSUFFICIENT_HISTORY,
                warnings=[f"Insufficient sample: {n} observations provided, minimum {min_required_obs} required."],
            )

        # ── Factor Sourcing ───────────────────────────────────────────────────
        data_status = FactorDataStatus.AVAILABLE
        if factor_returns is None or not any(factor_returns.values()):
            factor_returns = self.generate_synthetic_factor_series(length=n)
            data_status = FactorDataStatus.ESTIMATED

        # Align lengths
        y_arr = np.array(asset_returns[:n], dtype=float) - self.daily_rf

        # Build feature matrix X = [1, F1, F2, ..., Fk]
        active_factor_names: List[str] = []
        feature_cols: List[np.ndarray] = [np.ones(n, dtype=float)]

        for f_type in STANDARD_FACTORS:
            f_name = f_type.value
            f_series = factor_returns.get(f_name)
            if f_series and len(f_series) >= n:
                active_factor_names.append(f_name)
                feature_cols.append(np.array(f_series[:n], dtype=float))

        k = len(active_factor_names)
        if k == 0:
            return MultiFactorAttributionResult(
                symbol_or_portfolio=symbol_or_portfolio,
                start_date=st_dt,
                end_date=end_dt,
                observation_count=n,
                insufficient_sample=True,
                data_status=FactorDataStatus.UNAVAILABLE,
                warnings=["No valid factor return series available for regression."],
            )

        X = np.column_stack(feature_cols)

        # ── OLS Multivariate Regression ───────────────────────────────────────
        try:
            # Solve normal equations: beta = (X^T X)^(-1) X^T y
            XtX = np.dot(X.T, X)
            Xty = np.dot(X.T, y_arr)
            # Add small regularizer to ensure matrix invertibility in collinear samples
            XtX_inv = np.linalg.pinv(XtX)
            beta_hat = np.dot(XtX_inv, Xty)

            # Fitted values and residuals
            y_pred = np.dot(X, beta_hat)
            residuals = y_arr - y_pred

            ssr = float(np.sum(residuals ** 2))
            sst = float(np.sum((y_arr - np.mean(y_arr)) ** 2))

            r_squared = max(0.0, min(1.0, 1.0 - (ssr / sst))) if sst > 1e-12 else 0.0

            dof = max(1, n - k - 1)
            adjusted_r_squared = max(0.0, min(1.0, 1.0 - (1.0 - r_squared) * (n - 1) / dof))

            residual_variance = ssr / dof
            cov_matrix = residual_variance * XtX_inv
            std_errors = np.sqrt(np.maximum(np.diag(cov_matrix), 1e-12))

            t_stats = beta_hat / std_errors
            p_values = [normal_p_value(float(t)) for t in t_stats]

            # Alpha decomposition (Intercept = index 0)
            daily_alpha = float(beta_hat[0])
            annualized_alpha = daily_alpha * 252.0
            alpha_t = float(t_stats[0])
            alpha_p = float(p_values[0])

            # Factor attributions
            factor_attributions: Dict[str, SingleFactorAttribution] = {}
            for idx, f_name in enumerate(active_factor_names):
                param_idx = idx + 1
                b = float(beta_hat[param_idx])
                t = float(t_stats[param_idx])
                p = float(p_values[param_idx])
                f_ret = float(np.sum(X[:, param_idx]))
                ret_contrib = b * f_ret

                factor_attributions[f_name] = SingleFactorAttribution(
                    factor_name=f_name,
                    factor_type=FactorType(f_name),
                    beta=round(b, 4),
                    t_statistic=round(t, 2),
                    p_value=round(p, 4),
                    is_significant=(p < 0.05),
                    factor_return=round(f_ret, 4),
                    return_contribution=round(ret_contrib, 4),
                    status=data_status,
                )

            # Fill missing factors as UNAVAILABLE (not 0 beta)
            for f_type in STANDARD_FACTORS:
                if f_type.value not in factor_attributions:
                    factor_attributions[f_type.value] = SingleFactorAttribution(
                        factor_name=f_type.value,
                        factor_type=f_type,
                        beta=0.0,
                        status=FactorDataStatus.UNAVAILABLE,
                    )

            systematic_risk = round(r_squared * 100.0, 2)
            specific_risk = round((1.0 - r_squared) * 100.0, 2)

            res = MultiFactorAttributionResult(
                symbol_or_portfolio=symbol_or_portfolio,
                start_date=st_dt,
                end_date=end_dt,
                observation_count=n,
                alpha=round(annualized_alpha, 4),
                alpha_t_stat=round(alpha_t, 2),
                alpha_p_value=round(alpha_p, 4),
                r_squared=round(r_squared, 4),
                adjusted_r_squared=round(adjusted_r_squared, 4),
                residual_standard_error=round(float(math.sqrt(residual_variance)), 4),
                factors=factor_attributions,
                systematic_risk_pct=systematic_risk,
                specific_risk_pct=specific_risk,
                insufficient_sample=False,
                data_status=data_status,
                warnings=[],
            )
            self._cached_results[symbol_or_portfolio] = res
            return res

        except Exception as exc:
            # Safe fail-soft fallback
            return MultiFactorAttributionResult(
                symbol_or_portfolio=symbol_or_portfolio,
                start_date=st_dt,
                end_date=end_dt,
                observation_count=n,
                insufficient_sample=True,
                data_status=FactorDataStatus.UNAVAILABLE,
                warnings=[f"OLS regression computation failed: {str(exc)}"],
            )

    def get_latest_attribution(self, symbol: str) -> Optional[MultiFactorAttributionResult]:
        """Retrieve most recent factor attribution result for a symbol."""
        return self._cached_results.get(symbol)


# Global singleton instance
global_factor_engine = FactorAttributionEngine()
