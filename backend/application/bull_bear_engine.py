import logging
import hashlib
from typing import List, Tuple, Optional
from datetime import datetime, timezone

from backend.domain.schemas import MarketContext, DataQualityStatus
from backend.domain.chart_schemas import (
    ChartPatternIntelligencePayload, TrendRegime, VolatilityRegime,
    PatternStatus, BreakoutType
)
from backend.domain.bull_bear_schemas import (
    BullBearRiskResult,
    DirectionalState,
    EngineRiskState,
    EngineConflictRecord,
    EngineRiskFactor,
)

logger = logging.getLogger(__name__)

# Per-group maximum weight caps as defined in Phase 13 requirements
GROUP_CAPS = {
    'TREND': 2.0,
    'TECHNICAL': 2.0,
    'MOMENTUM': 1.5,
    'VOLUME': 1.0,
    'VOLATILITY': 1.0,
    'QUANT': 1.0,
    # Default cap for any unforeseen group
    'DEFAULT': 2.0,
}

def _deterministic_id(context_id: str, evidence_type: str, source_id: str) -> str:
    """Create a deterministic SHA‑256 based evidence ID.

    The ID is derived from a stable upstream identity consisting of the
    MarketContext `context_id`, the `evidence_type` string, and a `source_id`
    which may be the upstream evidence identifier (or a fallback placeholder).
    The first 16 hex characters are used to keep the identifier concise while
    retaining collision resistance.
    """
    raw = f"{context_id}:{evidence_type}:{source_id}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]

from backend.domain.schemas import EvidenceRecord, ProvenanceRecord, EvidenceCategory, SignalDirection, EvidenceType

class BullBearRiskEngine:
    def __init__(self):
        self.max_weight_per_group = 2.0

    def evaluate(
        self,
        market_context: MarketContext,
        evidence_summary, # backend.domain.schemas.EvidenceSummary
    ) -> BullBearRiskResult:
        result = BullBearRiskResult(
            directional_state=DirectionalState.INSUFFICIENT_DATA,
            risk_state=EngineRiskState.UNKNOWN,
        )

        if not market_context or not evidence_summary:
            return result

        if market_context.quality_status in [DataQualityStatus.CRITICAL_FAILURE, DataQualityStatus.DEGRADED]:
            result.risk_factors.append(
                EngineRiskFactor(
                    factor_type='DATA_QUALITY_RISK',
                    severity=EngineRiskState.HIGH,
                    description='Market data is stale or has critical errors.',
                )
            )

        evidence_list: List[EvidenceRecord] = []
        now = datetime.now(timezone.utc)

        # 1. Parse existing upstream EvidenceRecords from EvidenceSummary
        upstream_records = getattr(evidence_summary, "evidence_records", getattr(evidence_summary, "records", []))
        
        # We will group by category to respect correlation caps
        bull_group_scores: dict[str, float] = {}
        bear_group_scores: dict[str, float] = {}

        for rec in upstream_records:
            if not isinstance(rec, EvidenceRecord):
                continue
            if rec.direction not in [SignalDirection.BULLISH, SignalDirection.BEARISH]:
                continue
            
            group_name = rec.category.value if rec.category else 'DEFAULT'
            is_bullish = rec.direction == SignalDirection.BULLISH
            
            # Create provenance linking back to the upstream record
            from backend.domain.schemas import DataSource
            
            prov_source = rec.source if hasattr(rec, 'source') and isinstance(getattr(rec, 'source'), DataSource) else DataSource(
                provider_name='BullBearEngine',
                source_tier='TIER_1_PRIMARY_OFFICIAL',
                authority='SYSTEM',
                subscription_required=False,
                authentication_required=False,
                provider_version='1.0'
            )
            
            prov = ProvenanceRecord(
                metric=rec.metric_name or rec.claim,
                symbol=rec.symbol,
                value=float(rec.value) if isinstance(rec.value, (int, float)) else 0.0,
                unit=rec.unit or '',
                currency='',
                source=prov_source,
                verification_status=rec.verification_status if hasattr(rec, 'verification_status') else 'UNVERIFIED',
                quality='MEDIUM',
                observed_at=rec.data_timestamp,
                retrieved_at=now,
                publication_time=rec.timestamp,
                effective_time=rec.timestamp,
                period='',
                context_id=rec.evidence_id,  # Link to parent evidence ID
                adjusted=False
            )

            # Generate new deterministic ID
            ev_id = _deterministic_id(market_context.context_id, 'BULL_BEAR_DERIVED', rec.evidence_id)
            
            new_ev = EvidenceRecord(
                evidence_id=ev_id,
                symbol=rec.symbol,
                context_id=market_context.context_id,
                specialist_name='BullBearRiskEngine',
                data_timestamp=rec.data_timestamp,
                evidence_type=EvidenceType.DETERMINISTIC_CALCULATION,
                claim=f'Derived from {rec.specialist_name}: {rec.claim}',
                provenance=[prov],
                category=rec.category,
                direction=rec.direction,
                confidence=rec.confidence,
                is_deterministic=True
            )
            evidence_list.append(new_ev)

            # Cap weighting
            weight = getattr(rec, "importance", rec.confidence or 1.0)
            if is_bullish:
                bull_group_scores[group_name] = bull_group_scores.get(group_name, 0.0) + weight
            else:
                bear_group_scores[group_name] = bear_group_scores.get(group_name, 0.0) + weight

        # 2. Scoring with per-group caps
        total_bull = sum(min(w, GROUP_CAPS.get(g, GROUP_CAPS['DEFAULT'])) for g, w in bull_group_scores.items())
        total_bear = sum(min(w, GROUP_CAPS.get(g, GROUP_CAPS['DEFAULT'])) for g, w in bear_group_scores.items())

        result.bullish_score = total_bull
        result.bearish_score = total_bear
        result.active_evidence = evidence_list

        # 3. Conflict detection
        if total_bull > 1.0 and total_bear > 1.0:
            result.conflicts.append(
                EngineConflictRecord(
                    conflict_type='STRONG_OPPOSING_EVIDENCE',
                    bullish_evidence_ids=[e.evidence_id for e in evidence_list if e.direction == SignalDirection.BULLISH],
                    bearish_evidence_ids=[e.evidence_id for e in evidence_list if e.direction == SignalDirection.BEARISH],
                    resolution_note='Significant evidence on both sides.',
                )
            )
            result.directional_state = DirectionalState.MIXED
        elif total_bull > total_bear + 1.0:
            result.directional_state = DirectionalState.BULLISH
        elif total_bear > total_bull + 1.0:
            result.directional_state = DirectionalState.BEARISH
        elif total_bull > 0 or total_bear > 0:
            result.directional_state = DirectionalState.MIXED
        else:
            result.directional_state = DirectionalState.NEUTRAL

        # 4. Risk state calculation
        if result.risk_factors:
            result.risk_state = EngineRiskState.HIGH
        elif result.conflicts:
            result.risk_state = EngineRiskState.MODERATE
        else:
            result.risk_state = EngineRiskState.LOW

        return result
