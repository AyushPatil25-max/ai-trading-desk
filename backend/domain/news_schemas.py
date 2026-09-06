from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Generic, TypeVar

class NewsCategory(str, Enum):
    COMPANY = "COMPANY"
    MARKET = "MARKET"
    SECTOR = "SECTOR"
    ECONOMIC = "ECONOMIC"
    IPO = "IPO"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    RESULTS = "RESULTS"
    MANAGEMENT = "MANAGEMENT"
    REGULATORY = "REGULATORY"
    GOVERNMENT = "GOVERNMENT"
    MACRO = "MACRO"
    OTHER = "OTHER"

class SentimentState(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"

class ImportanceLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"

class NewsDataState(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"

class NewsProvenance(BaseModel):
    source_name: str
    source_type: str
    source_url: Optional[str] = None
    fetched_at: str

class RuleBasedSentiment(BaseModel):
    methodology: str = "RULE-BASED SENTIMENT"
    confidence: float

class AISummary(BaseModel):
    summary: str
    key_points: List[str]
    potential_market_relevance: str
    confidence: float
    generated_at: str

class NewsItem(BaseModel):
    id: str
    headline: str
    summary: Optional[str] = None
    source_name: str
    source_type: str
    source_url: Optional[str] = None
    published_at: Optional[str] = None
    fetched_at: str
    symbols: List[str] = []
    company_name: Optional[str] = None
    exchange: Optional[str] = None
    category: NewsCategory = NewsCategory.OTHER
    relevance: float = 0.0
    sentiment: SentimentState = SentimentState.UNKNOWN
    sentiment_confidence: float = 0.0
    importance: ImportanceLevel = ImportanceLevel.UNKNOWN
    language: Optional[str] = None
    data_state: NewsDataState = NewsDataState.FRESH
    provenance: NewsProvenance
    content_hash: str
    ai_analysis: Optional[AISummary] = None
    rule_sentiment: Optional[RuleBasedSentiment] = None

class CorporateEventType(str, Enum):
    DIVIDEND = "DIVIDEND"
    BONUS = "BONUS"
    SPLIT = "SPLIT"
    RIGHTS_ISSUE = "RIGHTS_ISSUE"
    BUYBACK = "BUYBACK"
    MERGER = "MERGER"
    ACQUISITION = "ACQUISITION"
    DEMERGER = "DEMERGER"
    BOARD_DECISION = "BOARD_DECISION"
    EARNINGS = "EARNINGS"
    IPO = "IPO"
    MACRO = "MACRO"
    OTHER = "OTHER"

class EventItem(BaseModel):
    id: str
    title: str
    event_type: CorporateEventType
    company: Optional[str] = None
    symbols: List[str] = []
    scheduled_time: Optional[str] = None
    source_name: str
    source_url: Optional[str] = None
    importance: ImportanceLevel = ImportanceLevel.UNKNOWN
    status: str = "UPCOMING"
    data_state: NewsDataState = NewsDataState.FRESH
    provenance: NewsProvenance
    additional_data: Dict[str, Any] = {}

class AlertState(str, Enum):
    ACTIVE = "ACTIVE"
    TRIGGERED = "TRIGGERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISABLED = "DISABLED"
    EXPIRED = "EXPIRED"
    ERROR = "ERROR"

class AlertRule(BaseModel):
    id: str
    symbol: Optional[str] = None
    category: Optional[NewsCategory] = None
    min_importance: Optional[ImportanceLevel] = None
    sentiment: Optional[SentimentState] = None
    state: AlertState = AlertState.ACTIVE
    created_at: str
    cooldown_minutes: int = 60
    last_triggered_at: Optional[str] = None

class AlertEvent(BaseModel):
    id: str
    rule_id: str
    trigger_event_id: str
    timestamp: str
    source_name: str
    symbol: Optional[str] = None
    reason: str

class NewsFilter(BaseModel):
    symbol: Optional[str] = None
    category: Optional[NewsCategory] = None
    sentiment: Optional[SentimentState] = None
    importance: Optional[ImportanceLevel] = None
    limit: int = 50
    from_date: Optional[str] = None
    to_date: Optional[str] = None

T = TypeVar('T')

class ProviderResponseState(str, Enum):
    SUCCESS_WITH_DATA = "SUCCESS_WITH_DATA"
    SUCCESS_EMPTY = "SUCCESS_EMPTY"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"
    STALE = "STALE"

class NewsResponse(BaseModel, Generic[T]):
    state: ProviderResponseState
    data: List[T]
    error_message: Optional[str] = None
