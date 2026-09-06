import hashlib
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from uuid import uuid4

from backend.domain.news_schemas import (
    NewsItem, NewsCategory, SentimentState, ImportanceLevel, NewsDataState, 
    NewsProvenance, EventItem, CorporateEventType, AlertRule, AlertEvent, AlertState,
    RuleBasedSentiment, ProviderResponseState, NewsResponse
)
from backend.infrastructure.providers.yfinance_provider import YFinanceProvider
from backend.infrastructure.security_master import get_security_master

logger = logging.getLogger(__name__)

class NewsEngine:
    def __init__(self):
        self.orchestrator = YFinanceProvider()
        self.sm = get_security_master()
        self.alerts: Dict[str, AlertRule] = {}
        self.alert_events: List[AlertEvent] = []

    def _generate_hash(self, headline: str, url: str) -> str:
        s = f"{headline.lower().strip()}|{url.lower().strip()}"
        return hashlib.sha256(s.encode('utf-8')).hexdigest()

    def _classify_sentiment(self, text: str) -> (SentimentState, RuleBasedSentiment):
        text = text.lower()
        
        # Word boundary regex to avoid matching generic substrings inside unrelated words
        pos_words = [r"\bsoars\b", r"\bsurges\b", r"\bbeats\b", r"\brecord high\b", r"\bgrowth\b"]
        neg_words = [r"\bplunges\b", r"\bfalls\b", r"\bmisses\b", r"\bdown\b", r"\bwarning\b", r"\bpenalty\b"]
        
        pos_count = sum(1 for w in pos_words if re.search(w, text))
        neg_count = sum(1 for w in neg_words if re.search(w, text))
        
        if pos_count > neg_count:
            return SentimentState.POSITIVE, RuleBasedSentiment(confidence=0.4 + (pos_count * 0.1))
        elif neg_count > pos_count:
            return SentimentState.NEGATIVE, RuleBasedSentiment(confidence=0.4 + (neg_count * 0.1))
        else:
            return SentimentState.UNKNOWN, RuleBasedSentiment(confidence=0.0)

    async def get_company_news(self, symbol: str, limit: int = 50) -> NewsResponse[NewsItem]:
        try:
            res = await self.orchestrator.get_news(symbol)
        except Exception as e:
            return NewsResponse(state=ProviderResponseState.ERROR, data=[], error_message=str(e))
            
        if not res.success:
            return NewsResponse(state=ProviderResponseState.ERROR, data=[], error_message=res.error_message)
            
        if not res.data:
            return NewsResponse(state=ProviderResponseState.SUCCESS_EMPTY, data=[])
            
        now = datetime.now(timezone.utc)
        items = []
        
        for raw in res.data:
            if not isinstance(raw, dict): continue
            
            title = raw.get("title") or ""
            if not title: continue
            
            url = raw.get("link") or raw.get("url") or None
            pub_dt = raw.get("providerPublishTime") or raw.get("pubDate")
            
            pub_ts = None
            if isinstance(pub_dt, (int, float)):
                try:
                    pub_ts = datetime.fromtimestamp(pub_dt, tz=timezone.utc).isoformat()
                except Exception:
                    pass
            elif isinstance(pub_dt, str):
                pub_ts = pub_dt
                
            prov = NewsProvenance(
                source_name=raw.get("publisher") or "Yahoo Finance",
                source_type="Financial News API",
                source_url=url,
                fetched_at=now.isoformat()
            )
            
            chash = self._generate_hash(title, url or "")
            
            cat = NewsCategory.COMPANY
            importance = ImportanceLevel.MEDIUM
            lower_title = title.lower()
            if re.search(r"\b(dividend|split|bonus)\b", lower_title):
                cat = NewsCategory.CORPORATE_ACTION
                importance = ImportanceLevel.HIGH
            elif re.search(r"\b(q[1-4]|earnings|results)\b", lower_title):
                cat = NewsCategory.RESULTS
                importance = ImportanceLevel.CRITICAL
                
            sentiment, rule_sent = self._classify_sentiment(title)
            
            state = NewsDataState.FRESH
            if pub_ts:
                try:
                    p_dt = datetime.fromisoformat(pub_ts.replace("Z", "+00:00"))
                    if now - p_dt > timedelta(days=7):
                        state = NewsDataState.STALE
                except:
                    pass

            item = NewsItem(
                id=str(uuid4()),
                headline=title,
                summary=raw.get("summary"),
                source_name=prov.source_name,
                source_type=prov.source_type,
                source_url=prov.source_url,
                published_at=pub_ts,
                fetched_at=prov.fetched_at,
                symbols=[symbol],
                category=cat,
                sentiment=sentiment,
                sentiment_confidence=rule_sent.confidence,
                importance=importance,
                data_state=state,
                provenance=prov,
                content_hash=chash,
                ai_analysis=None,
                rule_sentiment=rule_sent
            )
            items.append(item)
            
        seen = set()
        deduped = []
        for i in items:
            if i.content_hash not in seen:
                seen.add(i.content_hash)
                deduped.append(i)
                
        def sort_key(x):
            return x.published_at if x.published_at else ""
            
        deduped.sort(key=sort_key, reverse=True)
        final_list = deduped[:limit]
        
        if len(final_list) > 0:
            self.evaluate_news_alerts(final_list)
        
        return NewsResponse(
            state=ProviderResponseState.SUCCESS_WITH_DATA if final_list else ProviderResponseState.SUCCESS_EMPTY,
            data=final_list
        )

    async def get_corporate_actions(self, symbol: str) -> NewsResponse[EventItem]:
        try:
            res = await self.orchestrator.get_corporate_actions(symbol)
        except Exception as e:
            return NewsResponse(state=ProviderResponseState.ERROR, data=[], error_message=str(e))
        
        if not res.success:
            return NewsResponse(state=ProviderResponseState.ERROR, data=[], error_message=res.error_message)
            
        if not res.data:
            return NewsResponse(state=ProviderResponseState.SUCCESS_EMPTY, data=[])
            
        events = []
        now = datetime.now(timezone.utc).isoformat()
        
        for k, v in res.data.items():
            if not isinstance(v, list): continue
            
            evt_type = CorporateEventType.OTHER
            if "dividend" in k.lower():
                evt_type = CorporateEventType.DIVIDEND
            elif "split" in k.lower():
                evt_type = CorporateEventType.SPLIT
                
            for action in v:
                prov = NewsProvenance(
                    source_name="Yahoo Finance",
                    source_type="Corporate Action API",
                    fetched_at=now
                )
                
                date_val = action.get("Date") or action.get("date")
                events.append(EventItem(
                    id=str(uuid4()),
                    title=f"{symbol} {k}",
                    event_type=evt_type,
                    symbols=[symbol],
                    scheduled_time=str(date_val) if date_val else None,
                    source_name="Yahoo Finance",
                    importance=ImportanceLevel.HIGH,
                    status="COMPLETED" if date_val else "UNKNOWN",
                    data_state=NewsDataState.FRESH,
                    provenance=prov,
                    additional_data=action
                ))
                
        return NewsResponse(
            state=ProviderResponseState.SUCCESS_WITH_DATA if events else ProviderResponseState.SUCCESS_EMPTY,
            data=events
        )

    def evaluate_news_alerts(self, news_items: List[NewsItem]):
        now_dt = datetime.now(timezone.utc)
        
        imp_rank = {
            ImportanceLevel.CRITICAL: 4,
            ImportanceLevel.HIGH: 3,
            ImportanceLevel.MEDIUM: 2,
            ImportanceLevel.LOW: 1,
            ImportanceLevel.UNKNOWN: 0
        }
        
        for news in news_items:
            for rule_id, rule in self.alerts.items():
                if rule.state != AlertState.ACTIVE:
                    continue
                    
                if rule.symbol and rule.symbol not in news.symbols:
                    continue
                    
                if rule.category and rule.category != news.category:
                    continue
                    
                if rule.sentiment and rule.sentiment != news.sentiment:
                    continue
                    
                if rule.min_importance:
                    if imp_rank[news.importance] < imp_rank[rule.min_importance]:
                        continue
                        
                # Cooldown check
                if rule.last_triggered_at:
                    try:
                        last_trig = datetime.fromisoformat(rule.last_triggered_at.replace("Z", "+00:00"))
                        if now_dt - last_trig < timedelta(minutes=rule.cooldown_minutes):
                            continue
                    except:
                        pass
                        
                # Duplicate suppression via already triggered check (naively for this run)
                # Ensure we don't trigger same news id twice
                already_triggered = any(e.trigger_event_id == news.id and e.rule_id == rule.id for e in self.alert_events)
                if already_triggered:
                    continue
                    
                # Fire Alert
                evt = AlertEvent(
                    id=str(uuid4()),
                    rule_id=rule.id,
                    trigger_event_id=news.id,
                    timestamp=now_dt.isoformat(),
                    source_name=news.provenance.source_name,
                    symbol=news.symbols[0] if news.symbols else None,
                    reason=f"Matched headline: {news.headline}"
                )
                self.alert_events.append(evt)
                rule.last_triggered_at = now_dt.isoformat()
                rule.state = AlertState.TRIGGERED

    def create_alert_rule(self, rule: AlertRule) -> AlertRule:
        self.alerts[rule.id] = rule
        return rule
        
    def get_alert_rules(self) -> List[AlertRule]:
        return list(self.alerts.values())
        
    def get_alert_events(self) -> List[AlertEvent]:
        return self.alert_events
        
    def update_alert_rule(self, rule_id: str, updates: Dict[str, Any]) -> Optional[AlertRule]:
        if rule_id not in self.alerts:
            return None
        rule = self.alerts[rule_id]
        if "state" in updates:
            rule.state = AlertState(updates["state"])
        if "cooldown_minutes" in updates:
            rule.cooldown_minutes = updates["cooldown_minutes"]
        return rule
        
    def delete_alert_rule(self, rule_id: str) -> bool:
        if rule_id in self.alerts:
            del self.alerts[rule_id]
            return True
        return False
        
global_news_engine = NewsEngine()
def get_news_engine() -> NewsEngine:
    return global_news_engine
