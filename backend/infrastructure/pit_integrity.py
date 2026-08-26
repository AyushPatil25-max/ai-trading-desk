from enum import Enum
from datetime import datetime, timezone, timedelta
from typing import List
from pydantic import BaseModel, Field
import dateutil.parser

from backend.domain.schemas import MarketContext

class PiTViolationLevel(str, Enum):
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"

class PiTViolation(BaseModel):
    level: PiTViolationLevel
    rule: str
    description: str

class PiTAuditReport(BaseModel):
    is_valid: bool
    context_id: str
    snapshot_time: datetime
    context_timestamp: datetime
    frozen_verified: bool = False
    violations: List[PiTViolation] = Field(default_factory=list)

class PointInTimeValidator:
    """
    Enforces strict Point-in-Time (PiT) data integrity.
    Prevents future data leakage, ensures historical snapshot validity,
    validates provider freshness, and guarantees context immutability.
    """
    
    def __init__(self, max_staleness_hours: float = 72.0): # 72 hours allows for weekends
        self.max_staleness_hours = max_staleness_hours

    def validate(self, context: MarketContext, snapshot_time: datetime) -> PiTAuditReport:
        violations: List[PiTViolation] = []
        is_valid = True
        
        # Ensure snapshot_time is timezone-aware
        if snapshot_time.tzinfo is None:
            snapshot_time = snapshot_time.replace(tzinfo=timezone.utc)
            
        context_time = context.data_timestamp
        if context_time.tzinfo is None:
            context_time = context_time.replace(tzinfo=timezone.utc)

        # 1. Future Leakage Check (Critical)
        if context_time > snapshot_time:
            is_valid = False
            violations.append(PiTViolation(
                level=PiTViolationLevel.CRITICAL,
                rule="NO_FUTURE_LEAKAGE",
                description=f"Context timestamp ({context_time}) is strictly ahead of requested snapshot ({snapshot_time})."
            ))

        # 2. Provider Freshness Validation (Warning)
        staleness_delta = snapshot_time - context_time
        staleness_hours = staleness_delta.total_seconds() / 3600.0
        
        # Data shouldn't be too old, but this might just be a warning depending on weekends/holidays
        if staleness_hours > self.max_staleness_hours:
            violations.append(PiTViolation(
                level=PiTViolationLevel.WARNING,
                rule="FRESHNESS_VALIDATION",
                description=f"Data is {staleness_hours:.1f} hours stale, exceeding limit of {self.max_staleness_hours}."
            ))
            
        # Data shouldn't be negative stale (handled by future leakage, but explicitly bound)
        if staleness_hours < 0:
             violations.append(PiTViolation(
                level=PiTViolationLevel.CRITICAL,
                rule="FRESHNESS_VALIDATION",
                description="Negative staleness implies future data leakage."
            ))

        # 3. Timestamp Consistency Checks (OHLCV Arrays)
        for idx, row in enumerate(context.ohlcv_historical):
            row_date_str = row.get("date")
            if row_date_str:
                try:
                    row_date = dateutil.parser.isoparse(row_date_str)
                    if row_date.tzinfo is None:
                        row_date = row_date.replace(tzinfo=timezone.utc)
                        
                    if row_date > snapshot_time:
                        is_valid = False
                        violations.append(PiTViolation(
                            level=PiTViolationLevel.CRITICAL,
                            rule="HISTORICAL_SNAPSHOT_CONSISTENCY",
                            description=f"OHLCV row {idx} contains future date {row_date} relative to snapshot {snapshot_time}."
                        ))
                except Exception as e:
                    violations.append(PiTViolation(
                        level=PiTViolationLevel.WARNING,
                        rule="HISTORICAL_SNAPSHOT_CONSISTENCY",
                        description=f"Unparsable date format at row {idx}: {str(e)}"
                    ))
                    
        # 4. Context Freeze Guarantees
        frozen_verified = getattr(context.model_config, 'get', lambda k, d: False)("frozen", False)
        # Pydantic v2 sets model_config as dict
        if isinstance(context.model_config, dict):
            frozen_verified = context.model_config.get("frozen", False)
            
        if not frozen_verified:
            # We strictly enforce immutability to prevent tampering after validation
            is_valid = False
            violations.append(PiTViolation(
                level=PiTViolationLevel.CRITICAL,
                rule="CONTEXT_FREEZE_GUARANTEE",
                description="MarketContext is not a frozen Pydantic model; mutation is possible."
            ))

        return PiTAuditReport(
            is_valid=is_valid,
            context_id=context.context_id,
            snapshot_time=snapshot_time,
            context_timestamp=context_time,
            frozen_verified=frozen_verified,
            violations=violations
        )
