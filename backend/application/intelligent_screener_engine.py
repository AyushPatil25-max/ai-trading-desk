import logging
import asyncio
from typing import List, Dict, Any, Optional, Tuple, Union
import operator

from backend.domain.schemas import MarketContext, DataQualityStatus
from backend.domain.intelligent_screener_schemas import (
    ScreenerRequest, ScreenerResponse, ScreenerMatchResult,
    FilterCriterion, FilterGroup, ScreenerOperator, LogicalOperator,
    MatchedCriterionDetail, FailedCriterionDetail, UnavailableCriterionDetail
)
from backend.application.context_service import ContextService
from backend.scanner.universe import StockUniverse, UniverseType
from backend.scanner.historical_universe import HistoricalUniverse

logger = logging.getLogger(__name__)

OPS = {
    ScreenerOperator.EQ: operator.eq,
    ScreenerOperator.NEQ: operator.ne,
    ScreenerOperator.GT: operator.gt,
    ScreenerOperator.GTE: operator.ge,
    ScreenerOperator.LT: operator.lt,
    ScreenerOperator.LTE: operator.le,
    ScreenerOperator.IN: lambda a, b: a in b if isinstance(b, (list, set, tuple)) else False,
    ScreenerOperator.NOT_IN: lambda a, b: a not in b if isinstance(b, (list, set, tuple)) else True,
}

class IntelligentScreenerEngine:
    def __init__(self, context_service: ContextService):
        self.context_service = context_service
        # StockUniverse manages our supported universes
        self.universe_manager = StockUniverse()
        self.historical_universe = HistoricalUniverse()

    def _extract_field_value(self, context: MarketContext, field_path: str) -> Tuple[Any, bool]:
        """
        Extracts a value from MarketContext. Returns (value, is_available).
        field_path can be 'current_price', 'technical.rsi', 'fundamental.pe_ratio', etc.
        """
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

    def _evaluate_criterion(self, criterion: FilterCriterion, context: MarketContext, result: ScreenerMatchResult) -> bool:
        actual_val, is_available = self._extract_field_value(context, criterion.field)
        
        if not is_available:
            result.unavailable_criteria.append(UnavailableCriterionDetail(
                field=criterion.field,
                reason=f"Data unavailable for {criterion.field}"
            ))
            return False
            
        op_func = OPS.get(criterion.operator)
        if not op_func:
            result.failed_criteria.append(FailedCriterionDetail(
                field=criterion.field,
                operator=criterion.operator.value,
                target_value=criterion.value,
                actual_value=actual_val,
                reason="Unknown operator"
            ))
            return False

        try:
            matched = op_func(actual_val, criterion.value)
            if matched:
                result.matched_criteria.append(MatchedCriterionDetail(
                    field=criterion.field,
                    operator=criterion.operator.value,
                    target_value=criterion.value,
                    actual_value=actual_val
                ))
                return True
            else:
                result.failed_criteria.append(FailedCriterionDetail(
                    field=criterion.field,
                    operator=criterion.operator.value,
                    target_value=criterion.value,
                    actual_value=actual_val
                ))
                return False
        except Exception:
            # e.g., type mismatch
            result.failed_criteria.append(FailedCriterionDetail(
                field=criterion.field,
                operator=criterion.operator.value,
                target_value=criterion.value,
                actual_value=actual_val,
                reason="Evaluation exception (type mismatch?)"
            ))
            return False

    def _evaluate_group(self, group: FilterGroup, context: MarketContext, result: ScreenerMatchResult) -> bool:
        if not group.criteria:
            return True # Empty group matches
            
        if group.logical_operator == LogicalOperator.AND:
            all_match = True
            for item in group.criteria:
                if isinstance(item, FilterCriterion):
                    if not self._evaluate_criterion(item, context, result):
                        all_match = False
                elif isinstance(item, FilterGroup):
                    if not self._evaluate_group(item, context, result):
                        all_match = False
            return all_match
            
        elif group.logical_operator == LogicalOperator.OR:
            any_match = False
            for item in group.criteria:
                if isinstance(item, FilterCriterion):
                    if self._evaluate_criterion(item, context, result):
                        any_match = True
                elif isinstance(item, FilterGroup):
                    if self._evaluate_group(item, context, result):
                        any_match = True
            return any_match
            
        return False

    async def _scan_symbol(self, symbol: str, request: ScreenerRequest) -> ScreenerMatchResult:
        context = await self.context_service.get_market_context(symbol)
        
        res = ScreenerMatchResult(
            symbol=symbol,
            is_match=False,
            data_quality=context.quality_status,
            context_id=context.context_id
        )
        
        if context.quality_status == DataQualityStatus.CRITICAL_FAILURE:
            # Cannot evaluate
            return res
            
        is_match = self._evaluate_group(request.filters, context, res)
        res.is_match = is_match
        
        # Determine rank score if matched and sorted
        if is_match and request.sort_by:
            val, ok = self._extract_field_value(context, request.sort_by)
            if ok and isinstance(val, (int, float)):
                res.rank_score = float(val)
                
        return res

    async def execute_screen(self, request: ScreenerRequest) -> ScreenerResponse:
        # Get universe symbols
        try:
            utype = UniverseType(request.universe_type)
            snapshot = self.universe_manager.get_universe(utype)
            symbols = [c.symbol for c in snapshot]
        except ValueError:
            # Fallback to historical universe if not a standard enum
            symbols = self.historical_universe.get_universe_symbols(request.universe_type)
            if not symbols:
                # If neither works, empty universe
                symbols = []

        if not symbols:
            return ScreenerResponse(
                universe_type=request.universe_type,
                total_evaluated=0,
                total_matches=0,
                matches=[]
            )

        tasks = [self._scan_symbol(sym, request) for sym in symbols]
        # Bounded concurrency to avoid overwhelming providers
        # Usually gather is fine if context_service uses caches / singleflight
        scan_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_matches = []
        for r in scan_results:
            if isinstance(r, ScreenerMatchResult) and r.is_match:
                valid_matches.append(r)
                
        # Sort if required
        if request.sort_by:
            valid_matches.sort(key=lambda x: x.rank_score, reverse=request.sort_descending)
            
        # Limit
        if request.limit > 0:
            valid_matches = valid_matches[:request.limit]
            
        return ScreenerResponse(
            universe_type=request.universe_type,
            total_evaluated=len(symbols),
            total_matches=len(valid_matches),
            matches=valid_matches
        )
