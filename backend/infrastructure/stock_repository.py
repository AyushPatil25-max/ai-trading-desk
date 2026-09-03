import json
import logging
import os
from typing import Optional, List, Dict
from pydantic import TypeAdapter

from backend.domain.stock_schemas import StockFundamentalData, StockTechnicalData, StockAnalysisResult

logger = logging.getLogger(__name__)

class StockRepository:
    def __init__(self, storage_dir: str = "data/stocks"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        self.fundamentals_file = os.path.join(self.storage_dir, "fundamentals.json")
        self.technicals_file = os.path.join(self.storage_dir, "technicals.json")
        self.analysis_file = os.path.join(self.storage_dir, "analysis.json")
        
        self._fundamentals: Dict[str, StockFundamentalData] = {}
        self._technicals: Dict[str, StockTechnicalData] = {}
        self._analysis: Dict[str, StockAnalysisResult] = {}
        
        self._load()

    def _load(self):
        if os.path.exists(self.fundamentals_file):
            try:
                with open(self.fundamentals_file, "r") as f:
                    data = json.load(f)
                    adapter = TypeAdapter(List[StockFundamentalData])
                    items = adapter.validate_python(data)
                    self._fundamentals = {item.symbol: item for item in items}
            except Exception as e:
                logger.error(f"Failed to load fundamentals: {e}")

        if os.path.exists(self.technicals_file):
            try:
                with open(self.technicals_file, "r") as f:
                    data = json.load(f)
                    adapter = TypeAdapter(List[StockTechnicalData])
                    items = adapter.validate_python(data)
                    self._technicals = {item.symbol: item for item in items}
            except Exception as e:
                logger.error(f"Failed to load technicals: {e}")

        if os.path.exists(self.analysis_file):
            try:
                with open(self.analysis_file, "r") as f:
                    data = json.load(f)
                    adapter = TypeAdapter(List[StockAnalysisResult])
                    items = adapter.validate_python(data)
                    self._analysis = {item.symbol: item for item in items}
            except Exception as e:
                logger.error(f"Failed to load analysis: {e}")

    def _save(self):
        with open(self.fundamentals_file, "w") as f:
            f.write(TypeAdapter(List[StockFundamentalData]).dump_json(list(self._fundamentals.values())).decode())
            
        with open(self.technicals_file, "w") as f:
            f.write(TypeAdapter(List[StockTechnicalData]).dump_json(list(self._technicals.values())).decode())
            
        with open(self.analysis_file, "w") as f:
            f.write(TypeAdapter(List[StockAnalysisResult]).dump_json(list(self._analysis.values())).decode())

    def save_fundamental(self, data: StockFundamentalData):
        self._fundamentals[data.symbol] = data
        self._save()
        
    def save_technical(self, data: StockTechnicalData):
        self._technicals[data.symbol] = data
        self._save()
        
    def save_analysis(self, data: StockAnalysisResult):
        self._analysis[data.symbol] = data
        self._save()

    def get_fundamental(self, symbol: str) -> Optional[StockFundamentalData]:
        return self._fundamentals.get(symbol)
        
    def get_technical(self, symbol: str) -> Optional[StockTechnicalData]:
        return self._technicals.get(symbol)
        
    def get_analysis(self, symbol: str) -> Optional[StockAnalysisResult]:
        return self._analysis.get(symbol)

_GLOBAL_STOCK_REPO: Optional[StockRepository] = None

def get_stock_repository() -> StockRepository:
    global _GLOBAL_STOCK_REPO
    if _GLOBAL_STOCK_REPO is None:
        _GLOBAL_STOCK_REPO = StockRepository()
    return _GLOBAL_STOCK_REPO
