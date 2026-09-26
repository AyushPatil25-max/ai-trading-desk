import pytest
from datetime import datetime, timezone
from backend.application.bull_bear_engine import BullBearRiskEngine
from backend.domain.schemas import MarketContext, DataQualityStatus, EvidenceSummary, EvidenceRecord, EvidenceCategory, SignalDirection, EvidenceType

def test_bullish_evidence():
    engine = BullBearRiskEngine()
    ctx = MarketContext(
        context_id='ctx-1',
        symbol='RELIANCE',
        data_timestamp=datetime.now(timezone.utc),
        provider='TEST',
        current_price=2500.0,
        quality_status=DataQualityStatus.OK
    )
    # Simulate bullish records
    rec1 = EvidenceRecord(
        evidence_id="ev-1", symbol="RELIANCE", context_id="ctx-1", specialist_name="Tech",
        data_timestamp=datetime.now(timezone.utc), evidence_type=EvidenceType.DETERMINISTIC_CALCULATION,
        category=EvidenceCategory.TECHNICAL, direction=SignalDirection.BULLISH, confidence=1.0, claim="Trend UP"
    )
    rec2 = EvidenceRecord(
        evidence_id="ev-2", symbol="RELIANCE", context_id="ctx-1", specialist_name="Tech",
        data_timestamp=datetime.now(timezone.utc), evidence_type=EvidenceType.DETERMINISTIC_CALCULATION,
        category=EvidenceCategory.MOMENTUM, direction=SignalDirection.BULLISH, confidence=1.0, claim="Mom UP"
    )
    summary = EvidenceSummary(run_id="run-1", symbol="RELIANCE", context_id="ctx-1", evidence_records=[rec1, rec2])
    
    res = engine.evaluate(ctx, summary)
    # total_bull = 2.0 (1.0 from TREND, 1.0 from MOMENTUM) -> > total_bear (0) + 1.0 -> BULLISH
    assert res.directional_state.value == "BULLISH"
    assert res.bullish_score == 2.0

def test_bearish_evidence():
    engine = BullBearRiskEngine()
    ctx = MarketContext(
        context_id='ctx-2', symbol='TCS', data_timestamp=datetime.now(timezone.utc),
        provider='TEST', current_price=1600.0, quality_status=DataQualityStatus.OK
    )
    rec1 = EvidenceRecord(
        evidence_id="ev-3", symbol="TCS", context_id="ctx-2", specialist_name="Tech",
        data_timestamp=datetime.now(timezone.utc), evidence_type=EvidenceType.DETERMINISTIC_CALCULATION,
        category=EvidenceCategory.TECHNICAL, direction=SignalDirection.BEARISH, confidence=1.0, claim="Trend DOWN"
    )
    rec2 = EvidenceRecord(
        evidence_id="ev-4", symbol="TCS", context_id="ctx-2", specialist_name="Tech",
        data_timestamp=datetime.now(timezone.utc), evidence_type=EvidenceType.DETERMINISTIC_CALCULATION,
        category=EvidenceCategory.MOMENTUM, direction=SignalDirection.BEARISH, confidence=1.0, claim="Mom DOWN"
    )
    summary = EvidenceSummary(run_id="run-2", symbol="TCS", context_id="ctx-2", evidence_records=[rec1, rec2])

    res = engine.evaluate(ctx, summary)
    assert res.directional_state.value == "BEARISH"

def test_stale_data():
    engine = BullBearRiskEngine()
    ctx = MarketContext(
        context_id='ctx-3', symbol='INFY', data_timestamp=datetime.now(timezone.utc),
        provider='TEST', current_price=1500.0, quality_status=DataQualityStatus.DEGRADED
    )
    summary = EvidenceSummary(run_id="run-3", symbol="INFY", context_id="ctx-3", evidence_records=[])
    res = engine.evaluate(ctx, summary)
    assert res.risk_state.value == "HIGH"

def test_mixed_evidence():
    engine = BullBearRiskEngine()
    ctx = MarketContext(
        context_id='ctx-4', symbol='HDFC', data_timestamp=datetime.now(timezone.utc),
        provider='TEST', current_price=1600.0, quality_status=DataQualityStatus.OK
    )
    rec1 = EvidenceRecord(
        evidence_id="ev-5", symbol="HDFC", context_id="ctx-4", specialist_name="Tech",
        data_timestamp=datetime.now(timezone.utc), evidence_type=EvidenceType.DETERMINISTIC_CALCULATION,
        category=EvidenceCategory.TECHNICAL, direction=SignalDirection.BEARISH, confidence=1.0, claim="Trend DOWN"
    )
    rec2 = EvidenceRecord(
        evidence_id="ev-6", symbol="HDFC", context_id="ctx-4", specialist_name="Tech",
        data_timestamp=datetime.now(timezone.utc), evidence_type=EvidenceType.DETERMINISTIC_CALCULATION,
        category=EvidenceCategory.MOMENTUM, direction=SignalDirection.BULLISH, confidence=1.0, claim="Mom UP"
    )
    rec3 = EvidenceRecord(
        evidence_id="ev-7", symbol="HDFC", context_id="ctx-4", specialist_name="Tech",
        data_timestamp=datetime.now(timezone.utc), evidence_type=EvidenceType.DETERMINISTIC_CALCULATION,
        category=EvidenceCategory.TECHNICAL, direction=SignalDirection.BEARISH, confidence=1.0, claim="Trend DOWN 2"
    )
    rec4 = EvidenceRecord(
        evidence_id="ev-8", symbol="HDFC", context_id="ctx-4", specialist_name="Tech",
        data_timestamp=datetime.now(timezone.utc), evidence_type=EvidenceType.DETERMINISTIC_CALCULATION,
        category=EvidenceCategory.MOMENTUM, direction=SignalDirection.BULLISH, confidence=1.0, claim="Mom UP 2"
    )
    summary = EvidenceSummary(run_id="run-4", symbol="HDFC", context_id="ctx-4", evidence_records=[rec1, rec2, rec3, rec4])
    
    res = engine.evaluate(ctx, summary)
    # bull_score = 1.5, bear_score = 2.0 (capped). Both > 1.0 -> CONFLICT -> MIXED
    assert res.directional_state.value == "MIXED"
    assert res.risk_state.value == "MODERATE"
