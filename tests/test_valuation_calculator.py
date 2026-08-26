"""
Tests for Phase 3.6 — ValuationCalculator.

All tests are offline and deterministic.
No Groq calls. No Yahoo Finance calls. No external network.
Every assertion uses hand-computed expected values.
"""

import math
import unittest
from datetime import datetime, timezone

from backend.specialists.valuation_calculator import (
    ValuationMetric,
    calc_ev_ebitda,
    calc_fcf_yield,
    calc_pb_ratio,
    calc_pe_ratio,
    calc_peg_ratio,
    calc_ps_ratio,
    compute_all_valuation_metrics,
    summarize_available,
)

# ─── Shared test fixtures ─────────────────────────────────────────────────────

_CONTEXT_ID = "ctx-val-test-001"
_TIMESTAMP = datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
_PRICE = 360.0  # Current share price

_FULL_DATA = {
    "eps": 18.0,
    "prior_eps": 15.0,
    "revenue": 10000.0,
    "shares_outstanding": 100.0,
    "total_equity": 6000.0,
    "total_debt": 1500.0,
    "cash": 1800.0,
    "ebitda": 3000.0,
    "operating_cash_flow": 2200.0,
    "capex": 600.0,
}


def _calc_kwargs(data=None, price=_PRICE):
    return dict(
        data=data if data is not None else _FULL_DATA,
        current_price=price,
        context_id=_CONTEXT_ID,
        data_timestamp=_TIMESTAMP,
    )


# ─── 1. P/E Ratio ─────────────────────────────────────────────────────────────

class TestPERatio(unittest.TestCase):

    def test_pe_normal(self):
        """Standard P/E = 360 / 18 = 20.0."""
        m = calc_pe_ratio(**_calc_kwargs())
        self.assertTrue(m.available)
        self.assertAlmostEqual(m.value, 20.0, places=4)
        self.assertEqual(m.metric_name, "pe_ratio")
        self.assertEqual(m.unit, "x")

    def test_pe_zero_eps(self):
        """EPS == 0 → unavailable (division by zero)."""
        m = calc_pe_ratio(**_calc_kwargs(data={"eps": 0.0}))
        self.assertFalse(m.available)
        self.assertIn("zero", m.unavailable_reason.lower())
        self.assertIsNone(m.value)

    def test_pe_negative_eps(self):
        """EPS < 0 → unavailable (economically meaningless)."""
        m = calc_pe_ratio(**_calc_kwargs(data={"eps": -5.0}))
        self.assertFalse(m.available)
        self.assertIn("negative", m.unavailable_reason.lower())
        self.assertIsNone(m.value)

    def test_pe_missing_eps(self):
        """No eps key → unavailable."""
        m = calc_pe_ratio(**_calc_kwargs(data={}))
        self.assertFalse(m.available)
        self.assertIn("missing", m.unavailable_reason.lower())

    def test_pe_nan_eps(self):
        """NaN eps → unavailable."""
        m = calc_pe_ratio(**_calc_kwargs(data={"eps": float("nan")}))
        self.assertFalse(m.available)

    def test_pe_inf_eps(self):
        """Inf eps → unavailable."""
        m = calc_pe_ratio(**_calc_kwargs(data={"eps": float("inf")}))
        self.assertFalse(m.available)

    def test_pe_provenance_context_id(self):
        """context_id must be preserved exactly."""
        m = calc_pe_ratio(**_calc_kwargs())
        self.assertEqual(m.context_id, _CONTEXT_ID)

    def test_pe_inputs_recorded(self):
        """Inputs dict must contain current_price and eps."""
        m = calc_pe_ratio(**_calc_kwargs())
        self.assertIn("current_price", m.inputs)
        self.assertIn("eps", m.inputs)
        self.assertEqual(m.inputs["current_price"], _PRICE)
        self.assertEqual(m.inputs["eps"], 18.0)


# ─── 2. P/S Ratio ─────────────────────────────────────────────────────────────

class TestPSRatio(unittest.TestCase):

    def test_ps_normal(self):
        """P/S = 360 / (10000 / 100) = 360 / 100 = 3.6."""
        m = calc_ps_ratio(**_calc_kwargs())
        self.assertTrue(m.available)
        self.assertAlmostEqual(m.value, 3.6, places=4)

    def test_ps_missing_revenue(self):
        """Missing revenue → unavailable."""
        m = calc_ps_ratio(**_calc_kwargs(data={"shares_outstanding": 100.0}))
        self.assertFalse(m.available)
        self.assertIn("revenue", m.unavailable_reason.lower())

    def test_ps_missing_shares(self):
        """Missing shares_outstanding → unavailable."""
        m = calc_ps_ratio(**_calc_kwargs(data={"revenue": 10000.0}))
        self.assertFalse(m.available)
        self.assertIn("shares_outstanding", m.unavailable_reason.lower())

    def test_ps_zero_shares(self):
        """shares_outstanding == 0 → unavailable (division by zero)."""
        m = calc_ps_ratio(**_calc_kwargs(data={"revenue": 10000.0, "shares_outstanding": 0.0}))
        self.assertFalse(m.available)

    def test_ps_zero_revenue(self):
        """revenue == 0 → unavailable."""
        m = calc_ps_ratio(**_calc_kwargs(data={"revenue": 0.0, "shares_outstanding": 100.0}))
        self.assertFalse(m.available)

    def test_ps_revenue_per_share_in_inputs(self):
        """revenue_per_share must appear in inputs for provenance."""
        m = calc_ps_ratio(**_calc_kwargs())
        self.assertIn("revenue_per_share", m.inputs)
        self.assertAlmostEqual(m.inputs["revenue_per_share"], 100.0, places=4)


# ─── 3. P/B Ratio ─────────────────────────────────────────────────────────────

class TestPBRatio(unittest.TestCase):

    def test_pb_normal(self):
        """P/B = 360 / (6000 / 100) = 360 / 60 = 6.0."""
        m = calc_pb_ratio(**_calc_kwargs())
        self.assertTrue(m.available)
        self.assertAlmostEqual(m.value, 6.0, places=4)

    def test_pb_missing_equity(self):
        """Missing total_equity → unavailable."""
        m = calc_pb_ratio(**_calc_kwargs(data={"shares_outstanding": 100.0}))
        self.assertFalse(m.available)
        self.assertIn("total_equity", m.unavailable_reason.lower())

    def test_pb_zero_equity(self):
        """total_equity == 0 → unavailable."""
        m = calc_pb_ratio(**_calc_kwargs(data={"total_equity": 0.0, "shares_outstanding": 100.0}))
        self.assertFalse(m.available)

    def test_pb_negative_equity(self):
        """Negative book value → unavailable (distorted)."""
        m = calc_pb_ratio(**_calc_kwargs(data={"total_equity": -500.0, "shares_outstanding": 100.0}))
        self.assertFalse(m.available)
        self.assertIn("non-positive", m.unavailable_reason.lower())

    def test_pb_bvps_in_inputs(self):
        """book_value_per_share must appear in inputs for provenance."""
        m = calc_pb_ratio(**_calc_kwargs())
        self.assertIn("book_value_per_share", m.inputs)
        self.assertAlmostEqual(m.inputs["book_value_per_share"], 60.0, places=4)


# ─── 4. EV/EBITDA ─────────────────────────────────────────────────────────────

class TestEVEBITDA(unittest.TestCase):

    def test_ev_ebitda_normal(self):
        """
        market_cap = 360 * 100 = 36000
        EV = 36000 + 1500 - 1800 = 35700
        EV/EBITDA = 35700 / 3000 = 11.9
        """
        m = calc_ev_ebitda(**_calc_kwargs())
        self.assertTrue(m.available)
        self.assertAlmostEqual(m.value, 11.9, places=4)

    def test_ev_ebitda_negative_ebitda(self):
        """Negative EBITDA → unavailable."""
        data = dict(_FULL_DATA, ebitda=-500.0)
        m = calc_ev_ebitda(**_calc_kwargs(data=data))
        self.assertFalse(m.available)
        self.assertIn("negative", m.unavailable_reason.lower())

    def test_ev_ebitda_zero_ebitda(self):
        """EBITDA == 0 → unavailable (division by zero)."""
        data = dict(_FULL_DATA, ebitda=0.0)
        m = calc_ev_ebitda(**_calc_kwargs(data=data))
        self.assertFalse(m.available)

    def test_ev_ebitda_missing_shares(self):
        """Missing shares_outstanding → unavailable."""
        data = {k: v for k, v in _FULL_DATA.items() if k != "shares_outstanding"}
        m = calc_ev_ebitda(**_calc_kwargs(data=data))
        self.assertFalse(m.available)

    def test_ev_ebitda_defaults_missing_debt_cash(self):
        """Missing total_debt and cash → defaults to 0; assumption is documented."""
        data = {"shares_outstanding": 100.0, "ebitda": 3000.0}
        m = calc_ev_ebitda(**_calc_kwargs(data=data))
        self.assertTrue(m.available)
        # EV = 360*100 + 0 - 0 = 36000; EV/EBITDA = 36000/3000 = 12.0
        self.assertAlmostEqual(m.value, 12.0, places=4)
        self.assertTrue(any("total_debt" in a for a in m.assumptions))
        self.assertTrue(any("cash" in a for a in m.assumptions))

    def test_ev_ebitda_enterprise_value_in_inputs(self):
        """enterprise_value must appear in inputs for provenance."""
        m = calc_ev_ebitda(**_calc_kwargs())
        self.assertIn("enterprise_value", m.inputs)
        self.assertAlmostEqual(m.inputs["enterprise_value"], 35700.0, places=1)


# ─── 5. FCF Yield ─────────────────────────────────────────────────────────────

class TestFCFYield(unittest.TestCase):

    def test_fcf_yield_normal(self):
        """
        FCF = 2200 - 600 = 1600
        FCF per share = 1600 / 100 = 16.0
        FCF Yield = (16 / 360) * 100 = 4.4444%
        """
        m = calc_fcf_yield(**_calc_kwargs())
        self.assertTrue(m.available)
        expected = (1600 / 100 / 360) * 100
        self.assertAlmostEqual(m.value, round(expected, 4), places=3)

    def test_fcf_yield_negative_fcf(self):
        """Negative FCF is valid (yield becomes negative — still computed)."""
        data = dict(_FULL_DATA, operating_cash_flow=-200.0, capex=100.0)
        m = calc_fcf_yield(**_calc_kwargs(data=data))
        self.assertTrue(m.available)
        self.assertLess(m.value, 0.0)

    def test_fcf_yield_missing_ocf(self):
        """Missing operating_cash_flow → unavailable."""
        data = {"shares_outstanding": 100.0, "capex": 600.0}
        m = calc_fcf_yield(**_calc_kwargs(data=data))
        self.assertFalse(m.available)
        self.assertIn("operating_cash_flow", m.unavailable_reason.lower())

    def test_fcf_yield_missing_shares(self):
        """Missing shares_outstanding → unavailable."""
        data = {"operating_cash_flow": 2200.0, "capex": 600.0}
        m = calc_fcf_yield(**_calc_kwargs(data=data))
        self.assertFalse(m.available)

    def test_fcf_yield_defaults_missing_capex(self):
        """Missing capex → defaults to 0; assumption documented."""
        data = {"operating_cash_flow": 2200.0, "shares_outstanding": 100.0}
        m = calc_fcf_yield(**_calc_kwargs(data=data))
        self.assertTrue(m.available)
        expected = (2200 / 100 / _PRICE) * 100
        self.assertAlmostEqual(m.value, round(expected, 4), places=3)
        self.assertTrue(any("capex" in a for a in m.assumptions))

    def test_fcf_yield_fcf_per_share_in_inputs(self):
        """fcf_per_share must appear in inputs for provenance."""
        m = calc_fcf_yield(**_calc_kwargs())
        self.assertIn("fcf_per_share", m.inputs)


# ─── 6. PEG Ratio ─────────────────────────────────────────────────────────────

class TestPEGRatio(unittest.TestCase):

    def test_peg_normal(self):
        """
        P/E = 360 / 18 = 20.0
        EPS growth = ((18 - 15) / 15) * 100 = 20%
        PEG = 20.0 / 20.0 = 1.0
        """
        m = calc_peg_ratio(**_calc_kwargs())
        self.assertTrue(m.available)
        self.assertAlmostEqual(m.value, 1.0, places=4)

    def test_peg_explicit_growth_rate(self):
        """Explicit eps_growth_rate field takes priority over derived rate."""
        data = dict(_FULL_DATA, eps_growth_rate=25.0)
        m = calc_peg_ratio(**_calc_kwargs(data=data))
        self.assertTrue(m.available)
        # P/E = 20, growth = 25 → PEG = 0.8
        self.assertAlmostEqual(m.value, 0.8, places=4)

    def test_peg_negative_growth(self):
        """Negative EPS growth → unavailable (economically distorted)."""
        data = dict(_FULL_DATA, prior_eps=20.0)  # declining eps
        m = calc_peg_ratio(**_calc_kwargs(data=data))
        self.assertFalse(m.available)
        self.assertIn("negative", m.unavailable_reason.lower())

    def test_peg_zero_growth(self):
        """Zero EPS growth → unavailable (division by zero)."""
        data = dict(_FULL_DATA, prior_eps=18.0)  # same eps → 0% growth
        m = calc_peg_ratio(**_calc_kwargs(data=data))
        self.assertFalse(m.available)

    def test_peg_missing_prior_eps(self):
        """Missing prior_eps → unavailable."""
        data = {k: v for k, v in _FULL_DATA.items() if k != "prior_eps"}
        m = calc_peg_ratio(**_calc_kwargs(data=data))
        self.assertFalse(m.available)

    def test_peg_zero_prior_eps(self):
        """prior_eps == 0 → unavailable (growth rate undefined)."""
        data = dict(_FULL_DATA, prior_eps=0.0)
        m = calc_peg_ratio(**_calc_kwargs(data=data))
        self.assertFalse(m.available)

    def test_peg_propagates_pe_unavailability(self):
        """If P/E is unavailable (negative EPS), PEG is also unavailable."""
        data = dict(_FULL_DATA, eps=-5.0)
        m = calc_peg_ratio(**_calc_kwargs(data=data))
        self.assertFalse(m.available)


# ─── 7. compute_all_valuation_metrics ────────────────────────────────────────

class TestComputeAll(unittest.TestCase):

    def test_returns_six_metrics(self):
        """compute_all returns exactly 6 metrics (one per method)."""
        metrics = compute_all_valuation_metrics(
            fundamental_data=_FULL_DATA,
            current_price=_PRICE,
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        self.assertEqual(len(metrics), 6)

    def test_all_available_with_full_data(self):
        """All 6 metrics are available when complete data is supplied."""
        metrics = compute_all_valuation_metrics(
            fundamental_data=_FULL_DATA,
            current_price=_PRICE,
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        unavail = [m for m in metrics if not m.available]
        self.assertEqual(unavail, [], msg=f"Unexpected unavailable: {[m.unavailable_reason for m in unavail]}")

    def test_empty_data_all_unavailable(self):
        """Empty fundamental_data → all metrics unavailable."""
        metrics = compute_all_valuation_metrics(
            fundamental_data={},
            current_price=_PRICE,
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        avail = [m for m in metrics if m.available]
        self.assertEqual(avail, [])

    def test_context_id_preserved_in_all_metrics(self):
        """context_id must appear in every returned metric record."""
        metrics = compute_all_valuation_metrics(
            fundamental_data=_FULL_DATA,
            current_price=_PRICE,
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        for m in metrics:
            self.assertEqual(m.context_id, _CONTEXT_ID, msg=f"context_id missing in {m.metric_name}")

    def test_metric_names_are_distinct(self):
        """Every returned metric must have a unique metric_name."""
        metrics = compute_all_valuation_metrics(
            fundamental_data=_FULL_DATA,
            current_price=_PRICE,
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        names = [m.metric_name for m in metrics]
        self.assertEqual(len(names), len(set(names)))

    def test_summarize_available_counts_correctly(self):
        """summarize_available returns correct method list and count."""
        metrics = compute_all_valuation_metrics(
            fundamental_data=_FULL_DATA,
            current_price=_PRICE,
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        methods, count = summarize_available(metrics)
        self.assertEqual(count, 6)
        self.assertEqual(len(methods), 6)
        self.assertIn("Price-to-Earnings (P/E)", methods)

    def test_partial_data_produces_partial_availability(self):
        """With only EPS provided, only P/E should be available."""
        data = {"eps": 18.0}
        metrics = compute_all_valuation_metrics(
            fundamental_data=data,
            current_price=_PRICE,
            context_id=_CONTEXT_ID,
            data_timestamp=_TIMESTAMP,
        )
        available = [m for m in metrics if m.available]
        self.assertEqual(len(available), 1)
        self.assertEqual(available[0].metric_name, "pe_ratio")


if __name__ == "__main__":
    unittest.main()
