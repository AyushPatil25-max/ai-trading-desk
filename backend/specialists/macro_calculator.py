from typing import List, Dict, Any, Optional
from backend.domain.schemas import MarketContext, MacroMetricRecord

class MacroCalculator:
    """
    Deterministically computes macroeconomic indicators and aggregates macro evidence
    from the MarketContext.
    """

    @staticmethod
    def calculate_macro_metrics(ctx: MarketContext) -> List[MacroMetricRecord]:
        metrics: List[MacroMetricRecord] = []
        macro_data = ctx.macro_data or {}
        timestamp_str = ctx.data_timestamp.isoformat()

        # 1. Policy Rate
        policy_rate = macro_data.get("policy_rate")
        if policy_rate is not None:
            metrics.append(MacroMetricRecord(
                metric_name="policy_rate",
                value=float(policy_rate),
                unit="%",
                period="current",
                source="macro_data",
                calculation_method="Extraction",
                inputs={"policy_rate": policy_rate},
                available=True,
                context_id=ctx.context_id,
                data_timestamp=timestamp_str
            ))
        else:
            metrics.append(MacroMetricRecord(
                metric_name="policy_rate",
                unit="%",
                period="current",
                source="macro_data",
                calculation_method="Extraction",
                available=False,
                unavailable_reason="policy_rate missing from macro_data",
                context_id=ctx.context_id,
                data_timestamp=timestamp_str
            ))

        # 2. Inflation Rate
        inflation_rate = macro_data.get("inflation_rate")
        if inflation_rate is not None:
            metrics.append(MacroMetricRecord(
                metric_name="inflation_rate",
                value=float(inflation_rate),
                unit="%",
                period="current",
                source="macro_data",
                calculation_method="Extraction",
                inputs={"inflation_rate": inflation_rate},
                available=True,
                context_id=ctx.context_id,
                data_timestamp=timestamp_str
            ))
        else:
            metrics.append(MacroMetricRecord(
                metric_name="inflation_rate",
                unit="%",
                period="current",
                source="macro_data",
                calculation_method="Extraction",
                available=False,
                unavailable_reason="inflation_rate missing from macro_data",
                context_id=ctx.context_id,
                data_timestamp=timestamp_str
            ))

        # 3. Real Rate
        if policy_rate is not None and inflation_rate is not None:
            real_rate = float(policy_rate) - float(inflation_rate)
            metrics.append(MacroMetricRecord(
                metric_name="real_rate",
                value=real_rate,
                unit="%",
                period="current",
                source="computed",
                calculation_method="policy_rate - inflation_rate",
                inputs={"policy_rate": policy_rate, "inflation_rate": inflation_rate},
                available=True,
                context_id=ctx.context_id,
                data_timestamp=timestamp_str
            ))
        else:
            metrics.append(MacroMetricRecord(
                metric_name="real_rate",
                unit="%",
                period="current",
                source="computed",
                calculation_method="policy_rate - inflation_rate",
                available=False,
                unavailable_reason="Requires policy_rate and inflation_rate",
                context_id=ctx.context_id,
                data_timestamp=timestamp_str
            ))

        # 4. Treasury Yields and Spread
        t10 = macro_data.get("treasury_10y")
        t2 = macro_data.get("treasury_2y")
        
        if t10 is not None:
            metrics.append(MacroMetricRecord(
                metric_name="treasury_10y",
                value=float(t10),
                unit="%",
                period="current",
                source="macro_data",
                calculation_method="Extraction",
                inputs={"treasury_10y": t10},
                available=True,
                context_id=ctx.context_id,
                data_timestamp=timestamp_str
            ))
        if t2 is not None:
            metrics.append(MacroMetricRecord(
                metric_name="treasury_2y",
                value=float(t2),
                unit="%",
                period="current",
                source="macro_data",
                calculation_method="Extraction",
                inputs={"treasury_2y": t2},
                available=True,
                context_id=ctx.context_id,
                data_timestamp=timestamp_str
            ))

        if t10 is not None and t2 is not None:
            spread = (float(t10) - float(t2)) * 100  # in basis points
            metrics.append(MacroMetricRecord(
                metric_name="yield_spread_10y_2y",
                value=spread,
                unit="bps",
                period="current",
                source="computed",
                calculation_method="(treasury_10y - treasury_2y) * 100",
                inputs={"treasury_10y": t10, "treasury_2y": t2},
                available=True,
                context_id=ctx.context_id,
                data_timestamp=timestamp_str
            ))
        else:
            metrics.append(MacroMetricRecord(
                metric_name="yield_spread_10y_2y",
                unit="bps",
                period="current",
                source="computed",
                calculation_method="(treasury_10y - treasury_2y) * 100",
                available=False,
                unavailable_reason="Requires treasury_10y and treasury_2y",
                context_id=ctx.context_id,
                data_timestamp=timestamp_str
            ))
            
        # 5. GDP Growth
        gdp_growth = macro_data.get("gdp_growth")
        if gdp_growth is not None:
            metrics.append(MacroMetricRecord(
                metric_name="gdp_growth",
                value=float(gdp_growth),
                unit="%",
                period="current",
                source="macro_data",
                calculation_method="Extraction",
                inputs={"gdp_growth": gdp_growth},
                available=True,
                context_id=ctx.context_id,
                data_timestamp=timestamp_str
            ))

        return metrics
