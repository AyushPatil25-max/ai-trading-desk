import unittest
import asyncio
from datetime import datetime, date, timezone
from fastapi.testclient import TestClient

from backend.domain.ipo_schemas import (
    IPOMaster, GMPObservation, IPOSubscriptionObservation,
    IPOStatus, IPOType, IPOScoreVerdict, IPOAnalysis
)
from backend.application.ipo_engine import IPOEngine, DeterministicFixtureIPOProvider
from backend.application.ipo_routes import get_engine
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.main import app

class TestIPOIntelligenceE2E(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = DeterministicFixtureIPOProvider()
        self.engine = IPOEngine(self.provider, self.provider, self.provider)
        app.dependency_overrides[get_engine] = lambda: self.engine
        self.client = TestClient(app)
        global_audit_chain.reset()
        
    async def test_01_ipo_schema_validation(self):
        ipo = IPOMaster(
            id="IPO_1",
            company_name="Tech Corp",
            exchange="NSE",
            segment=IPOType.MAINBOARD,
            status=IPOStatus.UPCOMING,
            issue_price=100.0,
            market_lot=50,
            total_issue_shares=100000,
            fresh_issue_shares=60000,
            ofs_shares=40000
        )
        self.provider.add_ipo(ipo)
        fetched = await self.engine.get_ipo_details("IPO_1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, "IPO_1")

    async def test_02_derived_issue_size(self):
        ipo = IPOMaster(
            id="IPO_2", company_name="Tech Corp", exchange="NSE", segment=IPOType.MAINBOARD, status=IPOStatus.UPCOMING,
            issue_price=100.0, market_lot=50, total_issue_shares=100000, fresh_issue_shares=60000, ofs_shares=40000
        )
        self.provider.add_ipo(ipo)
        fetched = await self.engine.get_ipo_details("IPO_2")
        self.assertEqual(fetched.total_issue_size, 10000000.0)
        self.assertEqual(fetched.fresh_issue_size, 6000000.0)

    async def test_03_derived_minimum_investment(self):
        ipo = IPOMaster(
            id="IPO_3", company_name="Tech Corp", exchange="NSE", segment=IPOType.MAINBOARD, status=IPOStatus.UPCOMING,
            issue_price=100.0, market_lot=50
        )
        self.provider.add_ipo(ipo)
        fetched = await self.engine.get_ipo_details("IPO_3")
        self.assertEqual(fetched.minimum_investment, 5000.0)

    async def test_04_sme_ipo_type_distinction(self):
        ipo = IPOMaster(
            id="IPO_SME", company_name="SME Corp", exchange="NSE", segment=IPOType.SME, status=IPOStatus.OPEN,
            issue_price=50.0, market_lot=1000
        )
        self.provider.add_ipo(ipo)
        fetched = await self.engine.get_ipo_details("IPO_SME")
        self.assertEqual(fetched.segment, IPOType.SME)
        self.assertEqual(fetched.minimum_investment, 50000.0)

    async def test_05_gmp_percentage_calculation(self):
        ipo = IPOMaster(id="IPO_GMP1", company_name="Corp", exchange="NSE", segment=IPOType.MAINBOARD, status=IPOStatus.UPCOMING, issue_price=100.0)
        self.provider.add_ipo(ipo)
        self.provider.add_gmp("IPO_GMP1", GMPObservation(id="IPO_GMP1", gmp_value=25.0, source="Market", observed_at=datetime.now(timezone.utc)))
        fetched = await self.engine.get_ipo_details("IPO_GMP1")
        self.assertEqual(fetched.latest_gmp.gmp_percentage, 25.0)
        self.assertEqual(fetched.latest_gmp.estimated_listing_price, 125.0)

    async def test_06_zero_issue_price_gmp_handling(self):
        ipo = IPOMaster(id="IPO_ZERO", company_name="Corp", exchange="NSE", segment=IPOType.MAINBOARD, status=IPOStatus.UPCOMING, issue_price=0.0)
        self.provider.add_ipo(ipo)
        self.provider.add_gmp("IPO_ZERO", GMPObservation(id="IPO_ZERO", gmp_value=10.0, source="Market X", observed_at=datetime.now(timezone.utc)))
        fetched = await self.engine.get_ipo_details("IPO_ZERO")
        self.assertIsNone(fetched.latest_gmp.gmp_percentage)
        self.assertIsNone(fetched.latest_gmp.estimated_listing_price)

    async def test_07_gmp_trend_tracking(self):
        self.provider.add_ipo(IPOMaster(id="IPO_TREND", company_name="Trend", exchange="NSE", segment=IPOType.MAINBOARD, status=IPOStatus.OPEN))
        self.provider.add_gmp("IPO_TREND", GMPObservation(id="IPO_TREND", gmp_value=10.0, source="A", observed_at=datetime.now(timezone.utc)))
        self.provider.add_gmp("IPO_TREND", GMPObservation(id="IPO_TREND", gmp_value=15.0, source="A", observed_at=datetime.now(timezone.utc)))
        trend = await self.engine.get_gmp_trend("IPO_TREND")
        self.assertEqual(len(trend), 2)
        self.assertEqual(trend[1].gmp_value, 15.0)

    async def test_08_insufficient_data_verdict(self):
        self.provider.add_ipo(IPOMaster(id="IPO_GHOST", company_name="Ghost", exchange="NSE", segment=IPOType.MAINBOARD, status=IPOStatus.UPCOMING))
        analysis = await self.engine.analyze_ipo("IPO_GHOST")
        self.assertEqual(analysis.verdict, IPOScoreVerdict.INSUFFICIENT_DATA)

    async def test_09_ofs_heavy_issue_penalization(self):
        ipo = IPOMaster(id="IPO_OFS", company_name="Hype", exchange="BSE", segment=IPOType.MAINBOARD, status=IPOStatus.CLOSED,
            issue_price=200.0, total_issue_shares=1000, fresh_issue_shares=100, ofs_shares=900, lot_size=10)
        self.provider.add_ipo(ipo)
        self.provider.add_gmp("IPO_OFS", GMPObservation(id="IPO_OFS", gmp_value=200.0, source="Market", observed_at=datetime.now(timezone.utc)))
        self.provider.add_subscription("IPO_OFS", IPOSubscriptionObservation(id="IPO_OFS", observation_date=date.today(), total=100.0, source="Ex", observed_at=datetime.now(timezone.utc)))
        analysis = await self.engine.analyze_ipo("IPO_OFS")
        self.assertNotEqual(analysis.verdict, IPOScoreVerdict.STRONG)

    async def test_10_positive_fundamental_ipo_analysis(self):
        ipo = IPOMaster(id="IPO_STRONG", company_name="Solid", exchange="NSE", segment=IPOType.MAINBOARD, status=IPOStatus.OPEN,
            issue_price=100.0, total_issue_shares=1000, fresh_issue_shares=1000, ofs_shares=0, revenue=500.0, pat=50.0, pe=15.0, lot_size=10)
        self.provider.add_ipo(ipo)
        self.provider.add_gmp("IPO_STRONG", GMPObservation(id="IPO_STRONG", gmp_value=100.0, source="Market", observed_at=datetime.now(timezone.utc)))
        self.provider.add_subscription("IPO_STRONG", IPOSubscriptionObservation(id="IPO_STRONG", observation_date=date.today(), total=50.0, source="Ex", observed_at=datetime.now(timezone.utc)))
        analysis = await self.engine.analyze_ipo("IPO_STRONG")
        self.assertEqual(analysis.verdict, IPOScoreVerdict.POSITIVE)

    async def test_11_ipo_listing_retrieval(self):
        self.provider.add_ipo(IPOMaster(id="IPO_L1", company_name="A", exchange="NSE", segment=IPOType.MAINBOARD, status=IPOStatus.UPCOMING))
        self.provider.add_ipo(IPOMaster(id="IPO_L2", company_name="B", exchange="NSE", segment=IPOType.MAINBOARD, status=IPOStatus.OPEN))
        listed = await self.engine.get_ipo_list()
        self.assertGreaterEqual(len(listed), 2)
        open_list = await self.engine.get_ipo_list("OPEN")
        self.assertGreaterEqual(len(open_list), 1)
        self.assertTrue(any(ipo.id == "IPO_L2" for ipo in open_list))

    async def test_12_analyze_non_existent_ipo(self):
        with self.assertRaises(ValueError):
            await self.engine.analyze_ipo("INVALID_IPO")

    def test_13_api_list_endpoint(self):
        resp = self.client.get("/api/ipo/list")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    def test_14_api_upcoming_endpoint(self):
        resp = self.client.get("/api/ipo/upcoming")
        self.assertEqual(resp.status_code, 200)

    def test_15_api_open_endpoint(self):
        resp = self.client.get("/api/ipo/open")
        self.assertEqual(resp.status_code, 200)

    def test_16_api_listed_endpoint(self):
        resp = self.client.get("/api/ipo/listed")
        self.assertEqual(resp.status_code, 200)

    def test_17_api_get_ipo_details_not_found(self):
        resp = self.client.get("/api/ipo/NOT_FOUND_IPO")
        self.assertEqual(resp.status_code, 404)

    def test_18_api_get_ipo_details_success(self):
        self.provider.add_ipo(IPOMaster(id="API_1", company_name="A", exchange="NSE", segment=IPOType.MAINBOARD, status=IPOStatus.UPCOMING))
        resp = self.client.get("/api/ipo/API_1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["ipo_id"], "API_1")

    def test_19_api_get_gmp_history(self):
        self.provider.add_ipo(IPOMaster(id="API_GMP", company_name="A", exchange="NSE", segment=IPOType.MAINBOARD, status=IPOStatus.UPCOMING))
        resp = self.client.get("/api/ipo/API_GMP/gmp")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    def test_20_api_get_subscription(self):
        self.provider.add_ipo(IPOMaster(id="API_SUB", company_name="A", exchange="NSE", segment=IPOType.MAINBOARD, status=IPOStatus.UPCOMING))
        resp = self.client.get("/api/ipo/API_SUB/subscription")
        self.assertEqual(resp.status_code, 200)

    def test_21_api_analyze_ipo(self):
        self.provider.add_ipo(IPOMaster(id="API_ANALYZE", company_name="A", exchange="NSE", segment=IPOType.MAINBOARD, status=IPOStatus.UPCOMING))
        resp = self.client.get("/api/ipo/API_ANALYZE/analysis")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("verdict", resp.json())

    def test_22_api_analyze_ipo_not_found(self):
        resp = self.client.get("/api/ipo/API_ANALYZE_INVALID/analysis")
        self.assertEqual(resp.status_code, 404)

    def test_23_audit_event_emission_on_refresh(self):
        resp = self.client.post("/api/ipo/DUMMY/refresh")
        self.assertEqual(resp.status_code, 200)
        events = global_audit_chain.query_events(category="MARKET_DATA")
        self.assertTrue(any(e.event_type == "IPO_DATA_REFRESHED" and e.correlation_id == "DUMMY" for e in events))

    def test_24_audit_event_emission_on_analysis(self):
        self.provider.add_ipo(IPOMaster(id="AUDIT_ANALYZE", company_name="A", exchange="NSE", segment=IPOType.MAINBOARD, status=IPOStatus.UPCOMING))
        self.client.get("/api/ipo/AUDIT_ANALYZE/analysis")
        events = global_audit_chain.query_events(category="SIGNAL")
        self.assertTrue(any(e.event_type == "IPO_ANALYSIS_COMPLETED" and e.correlation_id == "AUDIT_ANALYZE" for e in events))
        
    def test_25_safety_and_determinism_no_execution_authority(self):
        self.assertFalse(hasattr(self.engine, "submit_order"))
        self.assertFalse(hasattr(self.engine, "execute_trade"))
        self.assertFalse(hasattr(self.engine, "arm_live_trading"))

if __name__ == '__main__':
    unittest.main()
