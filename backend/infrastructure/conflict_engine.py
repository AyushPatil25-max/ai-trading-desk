from typing import List, Optional, Tuple
from datetime import datetime

from backend.domain.schemas import (
    ProvenanceRecord, DataConflict, VerificationStatus, SourceTier
)

# Define hierarchy map. Lower index = higher priority.
_TIER_HIERARCHY = {
    SourceTier.TIER_1_PRIMARY_OFFICIAL: 1,
    SourceTier.TIER_2_REGULATORY: 2,
    SourceTier.TIER_3_LICENSED: 3,
    SourceTier.TIER_4_SECONDARY: 4,
    SourceTier.TIER_5_UNVERIFIED: 5,
}

class Phase2ConflictEngine:
    """
    Deterministically resolves conflicts based on institutional rules:
    - Higher source tier wins.
    - If equal tier: newer observed_at wins.
    - If values differ beyond tolerance, creates CONFLICTED status.
    - Never silently overwrites.
    """
    
    def __init__(self, tolerance_pct: float = 0.05):
        self.tolerance_pct = tolerance_pct

    def resolve(self, record_a: ProvenanceRecord, record_b: ProvenanceRecord) -> Tuple[ProvenanceRecord, Optional[DataConflict]]:
        """
        Resolves two conflicting ProvenanceRecords.
        Returns the winning record (with potentially updated status) and a DataConflict if they meaningfully differ.
        """
        # Ensure we are comparing the same metric
        if record_a.metric != record_b.metric:
            raise ValueError("Cannot resolve records for different metrics.")
            
        tier_a_rank = _TIER_HIERARCHY.get(record_a.source.source_tier, 99)
        tier_b_rank = _TIER_HIERARCHY.get(record_b.source.source_tier, 99)
        
        # Determine winner structurally
        winner = record_a
        loser = record_b
        
        if tier_a_rank < tier_b_rank:
            winner = record_a
            loser = record_b
            resolution_str = f"{winner.source.source_tier.name} overrides {loser.source.source_tier.name}"
        elif tier_b_rank < tier_a_rank:
            winner = record_b
            loser = record_a
            resolution_str = f"{winner.source.source_tier.name} overrides {loser.source.source_tier.name}"
        else:
            # Equal tier, fallback to newer observed_at
            if record_b.observed_at > record_a.observed_at:
                winner = record_b
                loser = record_a
                resolution_str = "Equal tier, newer observed_at wins"
            else:
                winner = record_a
                loser = record_b
                resolution_str = "Equal tier, newer observed_at wins (or identical)"
                
        # Calculate differences to check for tolerance breaches
        val_a, val_b = winner.value, loser.value
        abs_diff = abs(val_a - val_b)
        
        min_val = min(val_a, val_b)
        if min_val == 0:
            pct_diff = 1.0 if abs_diff > 0 else 0.0
        else:
            pct_diff = abs_diff / abs(min_val)
            
        # If differences exceed tolerance, we must flag the conflict and mark the winner as CONFLICTED
        conflict_record = None
        
        if pct_diff > self.tolerance_pct:
            conflict_record = DataConflict(
                metric=winner.metric,
                symbol=winner.symbol,
                source_a=winner.source.provider_name,
                value_a=winner.value,
                source_b=loser.source.provider_name,
                value_b=loser.value,
                timestamp_a=winner.observed_at,
                timestamp_b=loser.observed_at,
                absolute_difference=abs_diff,
                percentage_difference=pct_diff,
                resolution=resolution_str,
                resolution_reason="Tolerance breached, marked as CONFLICTED. Strict tier/time hierarchy applied."
            )
            # Important: Never silently overwrite; flag the returned winner so downstream knows it beat a conflicting value.
            winner = winner.model_copy(update={"verification_status": VerificationStatus.CONFLICTED})
            
        return winner, conflict_record
