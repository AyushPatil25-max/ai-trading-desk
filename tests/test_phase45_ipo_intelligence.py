import pytest
from datetime import datetime, date, timedelta
from backend.domain.ipo_schemas import (
    IPOMaster, IPOStatus, IPOType, GMPStatus, DataQuality,
    IPOScoreVerdict
)
from backend.application.ipo_engine import IPOEngine

def test_ipo_schema_mainboard_retail_limit():
    ipo = IPOMaster(
        id="IPO_MAIN_TEST",
        company_name="Mainboard Co",
        exchange="NSE",
        segment=IPOType.MAINBOARD,
        status=IPOStatus.OPEN,
        issue_price=100.0,
        lot_size=100,
        minimum_application_lots=1
    )
    # Min investment should be 10,000
    assert ipo.minimum_investment == 10000.0
    # Max retail investment for mainboard is Rs 2 Lakh. 
    # 200,000 / 10,000 = 20 lots = 2,00,000 max.
    assert ipo.maximum_retail_investment == 200000.0
    assert ipo.minimum_application_shares == 100

def test_ipo_schema_sme_retail_limit():
    ipo = IPOMaster(
        id="IPO_SME_TEST",
        company_name="SME Co",
        exchange="NSE",
        segment=IPOType.SME,
        status=IPOStatus.OPEN,
        issue_price=100.0,
        lot_size=1200, # Standard SME lot size
        minimum_application_lots=1
    )
    # SME min investment > 1 Lakh. Usually 1.2 Lakh.
    assert ipo.minimum_investment == 120000.0
    # Max retail logic ignores the 2L cap calculation if not Mainboard 
    # (actually in our logic we passed for SME, so it's None)
    assert ipo.maximum_retail_investment is None

def test_ipo_schema_gmp_status_fresh():
    ipo = IPOMaster(
        id="IPO_GMP",
        company_name="GMP Co",
        exchange="NSE",
        segment=IPOType.MAINBOARD,
        status=IPOStatus.OPEN,
        gmp=50.0,
        gmp_timestamp=datetime.now() - timedelta(hours=5),
        issue_price=100.0
    )
    assert ipo.gmp_status == GMPStatus.AVAILABLE
    assert len(ipo.listing_scenarios) == 3
    assert ipo.listing_scenarios[1].scenario_name == "BASE"
    assert ipo.listing_scenarios[1].estimated_listing_price == 150.0
    assert ipo.listing_scenarios[1].estimated_gain_percent == 50.0

def test_ipo_schema_gmp_status_stale():
    ipo = IPOMaster(
        id="IPO_GMP_STALE",
        company_name="GMP Stale Co",
        exchange="NSE",
        segment=IPOType.MAINBOARD,
        status=IPOStatus.OPEN,
        gmp=50.0,
        gmp_timestamp=datetime.now() - timedelta(days=3)
    )
    assert ipo.gmp_status == GMPStatus.STALE

def test_ipo_schema_missing_gmp():
    ipo = IPOMaster(
        id="IPO_NO_GMP",
        company_name="No GMP",
        exchange="NSE",
        segment=IPOType.MAINBOARD,
        status=IPOStatus.OPEN
    )
    assert ipo.gmp_status == GMPStatus.UNAVAILABLE
    assert len(ipo.listing_scenarios) == 0

def test_issue_size_calculations():
    ipo = IPOMaster(
        id="IPO_SIZE",
        company_name="Size Co",
        exchange="NSE",
        segment=IPOType.MAINBOARD,
        status=IPOStatus.OPEN,
        issue_price=100.0,
        total_issue_shares=1000000,
        fresh_issue_shares=800000,
        ofs_shares=200000
    )
    assert ipo.total_issue_size == 100000000.0
    assert ipo.fresh_issue_size == 80000000.0
    assert ipo.ofs_size == 20000000.0

@pytest.mark.asyncio
async def test_ipo_analysis_engine_missing_data():
    engine = IPOEngine()
    await engine.trigger_refresh()
    # Mocking a repo record
    repo = engine.repo
    ipo = IPOMaster(
        id="IPO_ANALYSIS_MISSING",
        company_name="Missing Co",
        exchange="NSE",
        segment=IPOType.MAINBOARD,
        status=IPOStatus.OPEN
    )
    repo.save_ipo(ipo)
    
    analysis = await engine.analyze_ipo("IPO_ANALYSIS_MISSING")
    assert analysis.verdict == IPOScoreVerdict.INSUFFICIENT_DATA
    assert analysis.data_quality_status == DataQuality.ERROR
    assert "Missing issue price or lot size" in analysis.warnings

@pytest.mark.asyncio
async def test_ipo_analysis_engine_full_data():
    engine = IPOEngine()
    repo = engine.repo
    ipo = IPOMaster(
        id="IPO_ANALYSIS_FULL",
        company_name="Full Co",
        exchange="NSE",
        segment=IPOType.MAINBOARD,
        status=IPOStatus.OPEN,
        issue_price=100.0,
        lot_size=100,
        revenue=500.0,
        pat=50.0,
        pe=15.0,
        total_subscription=100.0,
        gmp=40.0,
        gmp_timestamp=datetime.now(),
        promoters=["Promoter A"]
    )
    repo.save_ipo(ipo)
    
    analysis = await engine.analyze_ipo("IPO_ANALYSIS_FULL")
    assert analysis.verdict == IPOScoreVerdict.STRONG_POSITIVE
    assert analysis.data_quality_status == DataQuality.COMPLETE
    assert analysis.confidence > 0.8
    assert "Solid revenue base" in analysis.strengths
    assert "Profitable" in analysis.strengths
    assert "Reasonable absolute P/E" in analysis.strengths
    assert "Massive total subscription" in analysis.strengths
    
@pytest.mark.asyncio
async def test_ipo_analysis_engine_poor_quality_but_analyzable():
    engine = IPOEngine()
    repo = engine.repo
    ipo = IPOMaster(
        id="IPO_ANALYSIS_POOR",
        company_name="Poor Co",
        exchange="NSE",
        segment=IPOType.MAINBOARD,
        status=IPOStatus.OPEN,
        issue_price=100.0,
        lot_size=100,
        pat=-10.0, # Loss making
        pe=80.0,   # Expensive
        total_subscription=0.5, # Undersubscribed
        gmp=-5.0,  # Negative GMP
        promoters=["Promoter B"]
    )
    repo.save_ipo(ipo)
    
    analysis = await engine.analyze_ipo("IPO_ANALYSIS_POOR")
    assert analysis.verdict in [IPOScoreVerdict.NEGATIVE, IPOScoreVerdict.AVOID]
    assert "Loss making" in analysis.weaknesses
    assert "Expensive absolute valuation" in analysis.weaknesses
    assert "Negative GMP" in analysis.warnings
    assert "Under-subscribed" in analysis.warnings

