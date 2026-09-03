import json
import os
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from backend.domain.ipo_schemas import IPOMaster, IPOStatus

logger = logging.getLogger(__name__)

class IPORepository:
    def __init__(self, db_path="data/ipo/ipo_master.json"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._cache: Dict[str, IPOMaster] = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.db_path):
            self._cache = {}
            return
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    ipo = IPOMaster.model_validate(item)
                    self._cache[ipo.id] = ipo
        except Exception as e:
            logger.error(f"Failed to load IPO data: {e}")
            self._cache = {}

    def _save(self):
        try:
            data = [ipo.model_dump(mode="json") for ipo in self._cache.values()]
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save IPO data: {e}")

    def save_ipo(self, ipo: IPOMaster):
        self._cache[ipo.id] = ipo
        self._save()

    def upsert_ipo(self, ipo: IPOMaster):
        if ipo.id in self._cache:
            existing = self._cache[ipo.id]
            new_dump = ipo.model_dump(exclude_unset=True, exclude_none=True)
            merged = existing.model_copy(update=new_dump)
            self._cache[ipo.id] = merged
        else:
            self._cache[ipo.id] = ipo
        self._save()

    def get_ipo(self, ipo_id: str) -> Optional[IPOMaster]:
        return self._cache.get(ipo_id)

    def get_all(self) -> List[IPOMaster]:
        return list(self._cache.values())

    def get_open(self) -> List[IPOMaster]:
        return [ipo for ipo in self._cache.values() if ipo.status == IPOStatus.OPEN]

    def get_upcoming(self) -> List[IPOMaster]:
        return [ipo for ipo in self._cache.values() if ipo.status == IPOStatus.UPCOMING]

    def get_listed(self) -> List[IPOMaster]:
        return [ipo for ipo in self._cache.values() if ipo.status == IPOStatus.LISTED]

    def get_recent(self) -> List[IPOMaster]:
        return [ipo for ipo in self._cache.values() if ipo.status in [IPOStatus.CLOSED, IPOStatus.LISTED, IPOStatus.ALLOTMENT]]

    def search(self, query: str) -> List[IPOMaster]:
        q = query.lower()
        return [ipo for ipo in self._cache.values() if q in ipo.company_name.lower() or (ipo.symbol and q in ipo.symbol.lower())]

_global_ipo_repo: Optional[IPORepository] = None

def get_ipo_repository() -> IPORepository:
    global _global_ipo_repo
    if _global_ipo_repo is None:
        _global_ipo_repo = IPORepository()
    return _global_ipo_repo
