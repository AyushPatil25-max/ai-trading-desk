import os
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import pandas as pd

from backend.domain.backtest_schemas import (
    BacktestConfig,
    SingleDecisionBacktestResult,
    BatchBacktestResult
)
from backend.domain.schemas import MarketContext, SnapshotFreshness
from backend.application.backtest_engine import BacktestEngine
from backend.infrastructure.providers.yfinance_provider import YFinanceProvider
from backend.infrastructure.security_master import get_security_master
from pydantic import BaseModel

HISTORICAL_RESEARCH_DIR = "backend/data/historical_research"
os.makedirs(HISTORICAL_RESEARCH_DIR, exist_ok=True)


class HistoricalResearchRequest(BaseModel):
    symbol: str
    as_of: datetime
    config: Optional[BacktestConfig] = None


class HistoricalResearchService:
    def __init__(self):
        self.engine = BacktestEngine()
        self.yfinance = YFinanceProvider()
        self.security_master = get_security_master()

    async def run_historical_research(self, request: HistoricalResearchRequest) -> SingleDecisionBacktestResult:
        symbol = request.symbol
        as_of = request.as_of
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
            
        config = request.config or BacktestConfig()

        # Ensure we don't accidentally execute
        # the engine enforces PIT boundaries

        # 1. Fetch 5 years of historical data from YFinance to ensure enough history & future
        hist_res = await self.yfinance.get_historical_data(symbol, "5y")
        ohlcv_historical = []
        if hist_res.status == "SUCCESS" and hist_res.data:
            ohlcv_historical = hist_res.data.get("ohlcv", [])

        # Fetch fundamentals (TTM) - Ideally would be PIT, but we'll accept what provider gives 
        # and document that fundamental point-in-time is limited
        fundamentals_res = await self.yfinance.get_fundamentals(symbol)
        fundamental_data = fundamentals_res.data if fundamentals_res.status == "SUCCESS" else {}

        # 2. Construct MarketContext
        ctx_id = f"ctx-hist-{uuid.uuid4().hex[:8]}"
        
        # Get current price AT `as_of` for the market context (if possible, else use closest historical close)
        current_price = 1.0
        for bar in reversed(ohlcv_historical):
            bar_ts = bar.get("timestamp") or bar.get("date") or bar.get("datetime")
            if isinstance(bar_ts, pd.Timestamp):
                bar_dt = bar_ts.to_pydatetime()
            elif isinstance(bar_ts, str):
                try:
                    bar_dt = datetime.fromisoformat(bar_ts.replace("Z", "+00:00"))
                except ValueError:
                    continue
            else:
                bar_dt = bar_ts
                
            if bar_dt.tzinfo is None:
                bar_dt = bar_dt.replace(tzinfo=timezone.utc)
                
            if bar_dt <= as_of:
                current_price = float(bar.get("close", 1.0))
                break

        market_context = MarketContext(
            context_id=ctx_id,
            symbol=symbol,
            generated_at=datetime.now(timezone.utc),
            data_timestamp=as_of,
            provider="HistoricalResearchService",
            is_cached=False,
            freshness_status=SnapshotFreshness.FRESH,
            current_price=current_price,
            ohlcv_historical=ohlcv_historical,
            fundamental_data=fundamental_data,
        )

        # 3. Run deterministic backtest
        result: SingleDecisionBacktestResult = self.engine.run_single_backtest(
            raw_context=market_context,
            as_of=as_of,
            config=config,
            committee_decision=None,
            candidate_plan=None,
            market_regime=None,
            scenario_result=None
        )

        # 4. Save result
        self._save_result(result)

        return result

    def _save_result(self, result: SingleDecisionBacktestResult):
        file_path = os.path.join(HISTORICAL_RESEARCH_DIR, f"{result.backtest_id}.json")
        try:
            with open(file_path, "w") as f:
                f.write(result.model_dump_json(indent=2))
        except Exception as e:
            print(f"Failed to save historical research result: {e}")

    def get_result(self, backtest_id: str) -> Optional[SingleDecisionBacktestResult]:
        file_path = os.path.join(HISTORICAL_RESEARCH_DIR, f"{backtest_id}.json")
        if not os.path.exists(file_path):
            return None
        
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
                return SingleDecisionBacktestResult(**data)
        except Exception as e:
            print(f"Failed to load historical research result: {e}")
            return None

    def list_results(self) -> List[Dict[str, Any]]:
        results = []
        for filename in os.listdir(HISTORICAL_RESEARCH_DIR):
            if filename.endswith(".json"):
                file_path = os.path.join(HISTORICAL_RESEARCH_DIR, filename)
                try:
                    with open(file_path, "r") as f:
                        data = json.load(f)
                        bt_id = data.get("backtest_id")
                        ds = data.get("decision_snapshot", {})
                        po = data.get("primary_outcome", {})
                        
                        results.append({
                            "backtest_id": bt_id,
                            "symbol": ds.get("symbol"),
                            "evaluation_timestamp": ds.get("evaluation_timestamp"),
                            "outcome_status": po.get("outcome_status"),
                            "net_return_pct": po.get("net_return_pct")
                        })
                except Exception:
                    continue
        
        # Sort by evaluation timestamp descending
        results.sort(key=lambda x: x.get("evaluation_timestamp", ""), reverse=True)
        return results
