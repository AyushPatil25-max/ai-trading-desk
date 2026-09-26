import uuid
import logging
from typing import List, Dict, Any, Tuple

from backend.domain.schemas import MarketContext, DataQualityStatus
from backend.domain.stock_comparison_schemas import (
    StockComparisonRequest, StockComparisonResult, StockComparisonValues,
    ComparisonMetricValue, ComparisonRelativeObservation
)
from backend.application.context_service import ContextService

logger = logging.getLogger(__name__)

class StockComparisonEngine:
    def __init__(self, context_service: ContextService):
        self.context_service = context_service

    def _extract_metric(self, context: MarketContext, field_path: str) -> Tuple[Any, bool]:
        if context.quality_status == DataQualityStatus.CRITICAL_FAILURE:
            return None, False

        parts = field_path.split('.')
        base = parts[0]
        
        if len(parts) == 1:
            if hasattr(context, base):
                val = getattr(context, base)
                return val, val is not None
            return None, False
            
        if len(parts) == 2:
            sub = parts[1]
            if base == 'technical':
                val = context.technical_indicators.get(sub)
                return val, val is not None
            if base == 'fundamental':
                val = context.fundamental_data.get(sub)
                return val, val is not None
            if base == 'sector':
                val = context.sector_data.get(sub)
                return val, val is not None
            if base == 'macro':
                val = context.macro_data.get(sub)
                return val, val is not None
                
        return None, False

    def _calculate_relative_observation(self, metric: str, values: List[Tuple[str, Any, bool]]) -> ComparisonRelativeObservation:
        valid_vals = [v for v in values if v[2] and isinstance(v[1], (int, float))]
        if len(valid_vals) < 2:
            return ComparisonRelativeObservation(
                metric=metric,
                observation="Incomparable: Insufficient numeric data",
                winner_symbol=None,
                is_comparable=False
            )
            
        max_v = max(valid_vals, key=lambda x: x[1])
        min_v = min(valid_vals, key=lambda x: x[1])
        
        diff = max_v[1] - min_v[1]
        
        return ComparisonRelativeObservation(
            metric=metric,
            observation=f"Difference of {diff:.2f} between highest ({max_v[0]}) and lowest ({min_v[0]})",
            winner_symbol=max_v[0],
            is_comparable=True
        )

    async def compare_securities(self, request: StockComparisonRequest) -> StockComparisonResult:
        symbols = request.symbols
        if not symbols:
            raise ValueError("No symbols provided for comparison")
            
        if len(symbols) > 10:
            raise ValueError("Maximum comparison limit exceeded (10)")

        comparison_id = f"cmp-{uuid.uuid4().hex[:8]}"
        
        contexts = {}
        # Fetch uniquely to avoid redundant calls for duplicates
        for sym in set(symbols):
            try:
                contexts[sym] = await self.context_service.get_market_context(sym)
            except Exception as e:
                logger.error(f"Failed to fetch context for {sym}: {e}")

        comparisons = []
        metric_values_across = {m: [] for m in request.metrics}

        for sym in symbols:
            ctx = contexts.get(sym)
            
            comp_vals = StockComparisonValues(
                symbol=sym,
                data_quality=ctx.quality_status if ctx else DataQualityStatus.CRITICAL_FAILURE,
                context_id=ctx.context_id if ctx else "UNKNOWN"
            )

            if ctx and ctx.quality_status != DataQualityStatus.CRITICAL_FAILURE:
                for metric in request.metrics:
                    val, is_avail = self._extract_metric(ctx, metric)
                    freshness = ctx.quality_status.value
                    
                    comp_vals.metrics[metric] = ComparisonMetricValue(
                        value=val,
                        is_available=is_avail,
                        freshness_status=freshness
                    )
                    
                    metric_values_across[metric].append((sym, val, is_avail))
            else:
                for metric in request.metrics:
                    comp_vals.metrics[metric] = ComparisonMetricValue(
                        value=None,
                        is_available=False,
                        freshness_status="INVALID" if not ctx else ctx.quality_status.value
                    )
                    metric_values_across[metric].append((sym, None, False))

            comparisons.append(comp_vals)

        observations = []
        for metric, m_vals in metric_values_across.items():
            obs = self._calculate_relative_observation(metric, m_vals)
            observations.append(obs)
            
        return StockComparisonResult(
            comparison_id=comparison_id,
            symbols=symbols,
            comparisons=comparisons,
            relative_observations=observations
        )
