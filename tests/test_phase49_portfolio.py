import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.domain.portfolio_schemas import PortfolioDataState
from backend.domain.broker_schemas import BrokerConnectionState
from backend.domain.broker_schemas import BrokerAccountState, BrokerPosition

client = TestClient(app)

def test_get_portfolio_empty_or_unavailable():
    with patch("backend.application.portfolio_engine.global_account_sync_service") as mock_sync, \
         patch("backend.application.portfolio_engine.global_broker_manager") as mock_mgr:
         
         mock_adapter = MagicMock()
         mock_adapter.get_connection_state.return_value = BrokerConnectionState.DHAN_DISABLED
         mock_adapter.broker_name = "DhanBroker"
         mock_mgr.get_active_adapter.return_value = mock_adapter
         
         mock_sync.get_cached_account.return_value = None
         mock_sync.get_cached_holdings.return_value = []
         mock_sync.get_cached_positions.return_value = {}
         
         resp = client.get("/api/v1/portfolio")
         assert resp.status_code == 200
         data = resp.json()
         assert data["state"] == PortfolioDataState.UNAVAILABLE.value
         assert data["data"] is None

def test_get_portfolio_with_data():
    with patch("backend.application.portfolio_engine.global_account_sync_service") as mock_sync, \
         patch("backend.application.portfolio_engine.global_broker_manager") as mock_mgr, \
         patch("backend.application.portfolio_engine.global_portfolio_engine.market_data_gateway.get_latest_quote") as mock_mdg:
         
         mock_adapter = MagicMock()
         mock_adapter.get_connection_state.return_value = BrokerConnectionState.DHAN_CONNECTED
         mock_adapter.broker_name = "DhanBroker"
         mock_mgr.get_active_adapter.return_value = mock_adapter
         
         mock_sync.get_cached_account.return_value = BrokerAccountState(
             account_id="ACC123",
             broker_name="DhanBroker",
             cash=10000.0,
             buying_power=10000.0,
             total_equity=10000.0,
             realized_pnl=0.0,
             unrealized_pnl=0.0
         )
         
         mock_sync.get_cached_holdings.return_value = [
             {"tradingSymbol": "RELIANCE", "quantity": 10, "averagePrice": 2500.0}
         ]
         mock_sync.get_cached_positions.return_value = {
             "TCS": BrokerPosition(symbol="TCS", quantity=5, average_entry_price=3000.0, current_price=3100.0, market_value=15500.0, unrealized_pnl=500.0)
         }
         
         mock_quote = MagicMock()
         mock_quote.last_price = 2600.0
         mock_mdg.return_value = mock_quote
         
         resp = client.get("/api/v1/portfolio")
         assert resp.status_code == 200
         data = resp.json()
         assert data["state"] == PortfolioDataState.FRESH.value
         
         port = data["data"]
         assert port["broker"] == "DhanBroker"
         assert port["account_state"]["cash"] == 10000.0
         assert port["account_state"]["total_invested_value"] == 25000.0
         assert port["account_state"]["total_current_value"] == 26000.0
         assert port["account_state"]["unrealized_pnl"] == 1000.0
         
         assert len(port["holdings"]) == 1
         assert port["holdings"][0]["symbol"] == "RELIANCE"
         assert port["holdings"][0]["quantity"] == 10
         assert port["holdings"][0]["current_value"] == 26000.0
         
         assert len(port["positions"]) == 1
         assert port["positions"][0]["symbol"] == "TCS"
         assert port["positions"][0]["unrealized_pnl"] == 500.0

def test_get_portfolio_ai_analysis():
    with patch("backend.application.portfolio_engine.global_account_sync_service") as mock_sync, \
         patch("backend.application.portfolio_engine.global_broker_manager") as mock_mgr:
         
         mock_adapter = MagicMock()
         mock_adapter.get_connection_state.return_value = BrokerConnectionState.DHAN_CONNECTED
         mock_adapter.broker_name = "DhanBroker"
         mock_mgr.get_active_adapter.return_value = mock_adapter
         
         mock_sync.get_cached_account.return_value = BrokerAccountState(
             account_id="ACC123",
             broker_name="DhanBroker",
             cash=10000.0,
             buying_power=10000.0,
             total_equity=10000.0,
             realized_pnl=0.0,
             unrealized_pnl=0.0
         )
         mock_sync.get_cached_holdings.return_value = [
             {"tradingSymbol": "RELIANCE", "quantity": 10, "averagePrice": 2500.0}
         ]
         mock_sync.get_cached_positions.return_value = {}
         
         resp = client.get("/api/v1/portfolio/ai-analysis")
         assert resp.status_code == 200
         data = resp.json()
         assert "Analysis of 1 holdings" in data["summary"]
