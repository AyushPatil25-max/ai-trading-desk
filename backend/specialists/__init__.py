# Specialists package — production-grade specialist agent implementations.
#
# Each specialist follows the Golden Specialist Pattern:
#
#   BaseAgent
#       ↓
#   _build_evidence()       — assembles deterministic indicator snapshots from MarketContext
#       ↓
#   _build_prompt()         — constructs the LLM prompt injecting those values
#       ↓
#   LLMClient.generate_structured()   — AI interpretation / judgment
#       ↓
#   _build_output()         — composes AgentOutput with validated payload
#
# The LLM is the interpreter, not the source of truth for numerical values.

from backend.specialists.technical_specialist import TechnicalSpecialist
from backend.specialists.momentum_specialist import MomentumSpecialist
from backend.specialists.quant_specialist import QuantSpecialist
from backend.specialists.fundamental_specialist import FundamentalSpecialist
from backend.specialists.valuation_specialist import ValuationSpecialist
from backend.specialists.sector_specialist import SectorSpecialist
from backend.specialists.macro_specialist import MacroSpecialist
from backend.specialists.news_specialist import NewsSpecialist
from backend.specialists.institutional_specialist import InstitutionalSpecialist

__all__ = [
    "TechnicalSpecialist",
    "MomentumSpecialist",
    "QuantSpecialist",
    "FundamentalSpecialist",
    "ValuationSpecialist",
    "SectorSpecialist",
    "MacroSpecialist",
    "NewsSpecialist",
    "InstitutionalSpecialist",
]
