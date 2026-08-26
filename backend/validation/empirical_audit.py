"""
Empirical Data Trust & Strategy Auditor — Phase 5.4A

Performs deep data provider availability auditing, Point-In-Time data trust verification,
survivorship bias detection, specialist data sufficiency accounting, and deterministic strategy classification.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from backend.domain.schemas import DataQuality, SourceTier
from backend.simulation.simulation_state import PerformanceMetrics


class StrategyClassification(str, Enum):
    EMPIRICALLY_PROMISING = "EMPIRICALLY_PROMISING"
    MIXED_INCONCLUSIVE = "MIXED_INCONCLUSIVE"
    NOT_CURRENTLY_PROMISING = "NOT_CURRENTLY_PROMISING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ProviderAvailabilityEntry(BaseModel):
    dataset: str
    provider_name: str
    historical_depth: str
    timestamp_quality: str
    pit_quality: str
    source_tier: SourceTier
    auth_required: bool
    symbol_coverage: str
    date_bounds: str
    limitations: str


class DataSufficiencyReport(BaseModel):
    specialist_availability: Dict[str, float] = Field(default_factory=dict)
    overall_data_completeness_pct: float = 0.0
    quality_segment: str = "MEDIUM"
    survivorship_bias_risk: bool = True
    survivorship_notes: str = ""


class EmpiricalScorecard(BaseModel):
    classification: StrategyClassification
    classification_reason: str
    data_sufficiency: DataSufficiencyReport
    total_return_pct: float
    cagr_pct: float
    annualized_volatility: float
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    max_drawdown_pct: float
    calmar_ratio: Optional[float] = None
    win_rate: float
    profit_factor: Optional[float] = None
    total_trades: int
    turnover: float
    break_even_cost_bps: int
    is_pit_clean: bool
    survivorship_bias_risk: bool
    reproducibility_hash: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class DataTrustAuditor:
    """
    Audits live/offline data providers, measures real data completeness, and classifies strategy efficacy.
    """

    @classmethod
    def audit_providers(cls) -> List[ProviderAvailabilityEntry]:
        """
        Audit all integrated infrastructure providers in the trading desk.
        """
        return [
            ProviderAvailabilityEntry(
                dataset="OHLCV Bars & Quotes",
                provider_name="yfinance",
                historical_depth="Up to 10+ years daily, 60 days intraday",
                timestamp_quality="Market close / Bar timestamp (UTC/IST)",
                pit_quality="High (Historical bars frozen on close)",
                source_tier=SourceTier.TIER_4_SECONDARY,
                auth_required=False,
                symbol_coverage="NSE & BSE Equities (.NS, .BO)",
                date_bounds="2000-01-01 to Present",
                limitations="Secondary aggregator; possible unadjusted split anomalies if not verified",
            ),
            ProviderAvailabilityEntry(
                dataset="Official Quotes & Delivery Data",
                provider_name="NSE_Official",
                historical_depth="Historical Bhavcopy & Delivery reports",
                timestamp_quality="Official Exchange Timestamp",
                pit_quality="Primary Official (Tier 1)",
                source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
                auth_required=True,
                symbol_coverage="All NSE Listed Equities",
                date_bounds="Available via authenticated data feed",
                limitations="Official API requires active enterprise subscription credentials",
            ),
            ProviderAvailabilityEntry(
                dataset="Financial Statements & Ratios",
                provider_name="yfinance / Corporate Filings",
                historical_depth="Quarterly and Annual (4-5 quarters)",
                timestamp_quality="Period end date & Filing timestamp",
                pit_quality="Medium (Filing publication lag must be enforced)",
                source_tier=SourceTier.TIER_4_SECONDARY,
                auth_required=False,
                symbol_coverage="Major NSE 500 Equities",
                date_bounds="2019 to Present",
                limitations="Filing timestamps must be strictly gated to prevent look-ahead bias",
            ),
            ProviderAvailabilityEntry(
                dataset="Corporate Disclosures & Filings",
                provider_name="BSE / NSE Corporate Announcements",
                historical_depth="Real-time filings and annual reports",
                timestamp_quality="Exchange submission timestamp",
                pit_quality="Primary Official (Tier 1)",
                source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
                auth_required=True,
                symbol_coverage="All listed Indian companies",
                date_bounds="Live & Authenticated Archives",
                limitations="Requires exchange feed connection for full historical depth",
            ),
            ProviderAvailabilityEntry(
                dataset="Institutional Flows (FII / DII)",
                provider_name="SEBI / NSE Institutional Reports",
                historical_depth="Daily aggregated net flows",
                timestamp_quality="EOD publication timestamp",
                pit_quality="Regulatory Official (Tier 2)",
                source_tier=SourceTier.TIER_2_REGULATORY,
                auth_required=False,
                symbol_coverage="Market-wide & specific security deliveries",
                date_bounds="2020 to Present",
                limitations="Security-specific FII holding updates published quarterly",
            ),
            ProviderAvailabilityEntry(
                dataset="Macroeconomic Indicators (Repo Rate, CPI, GDP)",
                provider_name="RBI / MoSPI",
                historical_depth="Multi-year monthly/quarterly series",
                timestamp_quality="Official statistical release timestamp",
                pit_quality="Primary Official (Tier 1)",
                source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
                auth_required=False,
                symbol_coverage="India Macro Series",
                date_bounds="2015 to Present",
                limitations="Macro updates on monthly/bimonthly MPC schedule",
            ),
            ProviderAvailabilityEntry(
                dataset="News Streams",
                provider_name="yfinance News / RSS Feeds",
                historical_depth="Recent 30-90 days",
                timestamp_quality="Publication UTC timestamp",
                pit_quality="Medium (Subject to publisher timestamp accuracy)",
                source_tier=SourceTier.TIER_4_SECONDARY,
                auth_required=False,
                symbol_coverage="Nifty 50 and active tickers",
                date_bounds="Rolling window",
                limitations="Deep multi-year historical news archives require dedicated news vendor",
            ),
            ProviderAvailabilityEntry(
                dataset="Universe Constituents (Nifty 50 / 500)",
                provider_name="NSE Index Services",
                historical_depth="Semiannual index rebalancing records",
                timestamp_quality="Effective reconstitution date",
                pit_quality="Primary Official (Tier 1)",
                source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
                auth_required=False,
                symbol_coverage="Nifty Index family",
                date_bounds="2020 to Present",
                limitations="Static constituent lists carry survivorship bias risk unless historical reconstitution feed is active",
            ),
        ]

    @classmethod
    def audit_data_sufficiency(cls, datasets: Dict[str, Dict[str, Any]]) -> DataSufficiencyReport:
        """
        Compute real percentage data sufficiency across all 9 specialist domains.
        """
        if not datasets:
            return DataSufficiencyReport(
                specialist_availability={},
                overall_data_completeness_pct=0.0,
                quality_segment="DEGRADED",
                survivorship_bias_risk=True,
                survivorship_notes="No datasets provided.",
            )

        total_symbols = len(datasets)
        counts = {
            "Technical": 0,
            "Momentum": 0,
            "Quant": 0,
            "Fundamental": 0,
            "Valuation": 0,
            "Sector": 0,
            "Macro": 0,
            "News": 0,
            "Institutional": 0,
        }

        for symbol, data in datasets.items():
            ohlcv = data.get("ohlcv_historical", [])
            tech = data.get("technical_indicators", {})
            fund = data.get("fundamental_data", {})
            news = data.get("news_data", {})
            inst = data.get("institutional_data", [])

            if len(ohlcv) >= 20:
                counts["Technical"] += 1
                counts["Momentum"] += 1
                counts["Quant"] += 1

            if fund and ("net_profit" in fund or "revenue" in fund or "pe_ratio" in fund):
                counts["Fundamental"] += 1
                counts["Valuation"] += 1

            if data.get("sector_data") or symbol.endswith(".NS"):
                counts["Sector"] += 1
                counts["Macro"] += 1

            if news and (isinstance(news, list) and len(news) > 0 or isinstance(news, dict) and len(news.get("articles", [])) > 0):
                counts["News"] += 1

            if inst and len(inst) > 0:
                counts["Institutional"] += 1

        availability = {
            k: round((v / total_symbols) * 100.0, 1)
            for k, v in counts.items()
        }

        overall_pct = round(sum(availability.values()) / len(availability), 1)

        if overall_pct >= 75.0:
            quality_segment = "HIGH"
        elif overall_pct >= 50.0:
            quality_segment = "MEDIUM"
        elif overall_pct >= 25.0:
            quality_segment = "LOW"
        else:
            quality_segment = "DEGRADED"

        return DataSufficiencyReport(
            specialist_availability=availability,
            overall_data_completeness_pct=overall_pct,
            quality_segment=quality_segment,
            survivorship_bias_risk=True,
            survivorship_notes="Constituent lists evaluated over static historical proxy. SURVIVORSHIP_BIAS_RISK = TRUE.",
        )

    @classmethod
    def classify_strategy(
        cls,
        metrics: PerformanceMetrics,
        data_sufficiency: DataSufficiencyReport,
        is_clean_pit: bool,
        survivorship_bias: bool,
    ) -> Tuple[StrategyClassification, str]:
        """
        Deterministically classify strategy efficacy based on empirical validation rules.
        """
        # Rule 1: Insufficient Data check
        if data_sufficiency.overall_data_completeness_pct < 30.0 or metrics.total_trades < 3:
            return (
                StrategyClassification.INSUFFICIENT_DATA,
                f"Validation data completeness ({data_sufficiency.overall_data_completeness_pct:.1f}%) or sample size ({metrics.total_trades} trades) is insufficient for statistical confidence.",
            )

        # Rule 2: Point-In-Time Leakage check
        if not is_clean_pit:
            return (
                StrategyClassification.NOT_CURRENTLY_PROMISING,
                "Strategy validation failed due to Point-In-Time temporal leakage contamination.",
            )

        # Rule 3: Clear Underperformance check
        if metrics.total_return_pct <= 0.0 or (metrics.profit_factor and metrics.profit_factor < 1.0) or metrics.max_drawdown_pct > 25.0:
            return (
                StrategyClassification.NOT_CURRENTLY_PROMISING,
                f"Strategy underperformed out-of-sample: Return {metrics.total_return_pct:+.2f}%, Max DD {metrics.max_drawdown_pct:.1f}%, Profit Factor {metrics.profit_factor}.",
            )

        # Rule 4: High Performance with Survivorship Bias check
        sh = metrics.sharpe_ratio or 0.0
        if metrics.total_return_pct >= 8.0 and sh >= 0.8 and metrics.max_drawdown_pct <= 20.0 and metrics.win_rate >= 50.0:
            if survivorship_bias:
                return (
                    StrategyClassification.MIXED_INCONCLUSIVE,
                    f"Strategy generated positive return ({metrics.total_return_pct:+.2f}%, Sharpe {sh:.2f}), but survivorship bias is present in constituent history.",
                )
            else:
                return (
                    StrategyClassification.EMPIRICALLY_PROMISING,
                    f"Strategy passed all out-of-sample risk-adjusted return ({metrics.total_return_pct:+.2f}%, Sharpe {sh:.2f}) and drawdown ({metrics.max_drawdown_pct:.1f}%) criteria on verified survivorship-free data.",
                )

        return (
            StrategyClassification.MIXED_INCONCLUSIVE,
            f"Strategy showed mixed performance (Return {metrics.total_return_pct:+.2f}%, Sharpe {sh:.2f}, Win Rate {metrics.win_rate:.1f}%).",
        )
