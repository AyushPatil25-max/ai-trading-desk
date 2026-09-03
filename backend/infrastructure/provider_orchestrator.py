"""
Phase 21 — Resilient Market Data Provider Orchestration

Enterprise-grade provider orchestration layer providing:
- Deterministic priority provider selection & fallback (Primary -> Secondary -> Tertiary).
- Centralized data quality gating.
- Bounded request timeout handling with isolated worker execution.
- Per-provider circuit breaker isolation and recovery.
- Bounded retries without infinite loops.
- Deterministic pure-Python health and latency percentile tracking (p50, p95, p99).
- Secret-sanitized telemetry emission.
- Explicit degraded state on compound failure — NEVER fabricates prices.
"""

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid
import pandas as pd

from backend.domain.schemas import (
    MarketContext,
    HistoricalWindow,
    DataQualityStatus,
    SnapshotFreshness,
)
from backend.domain.provider_schemas import (
    CircuitState,
    FailureType,
    ProviderHealthMetrics,
    ProviderOrchestratorStatus,
    ProviderStatus,
    ValidationResult,
)
from backend.infrastructure.data_providers import MarketDataProvider, YFinanceProvider
from backend.infrastructure.circuit_breaker import CircuitBreaker
from backend.infrastructure.data_quality_gate import DataQualityGate

logger = logging.getLogger(__name__)


class ResilientProviderOrchestrator(MarketDataProvider):
    """
    Resilient orchestrator that wraps multiple MarketDataProviders with
    circuit breakers, data-quality validation gates, bounded timeouts,
    and automatic failover.
    Implements MarketDataProvider to preserve 100% backward compatibility.
    """

    SENSITIVE_KEYS = {"api_key", "secret", "password", "token", "auth_token", "access_token", "credential"}

    def __init__(
        self,
        providers: Optional[List[Tuple[MarketDataProvider, int]]] = None,
        timeout_seconds: float = 5.0,
        max_retries: int = 1,
        quality_gate: Optional[DataQualityGate] = None,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 30.0,
        telemetry_engine: Optional[Any] = None,
    ):
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._quality_gate = quality_gate or DataQualityGate()
        self._telemetry_engine = telemetry_engine

        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ProviderOrch")

        # Map provider_name -> (provider_instance, priority, is_primary)
        self._providers: Dict[str, MarketDataProvider] = {}
        self._priorities: Dict[str, int] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._primary_name: str = ""
        self._active_name: str = ""
        self._fallback_level: int = 0

        self._failure_threshold = failure_threshold
        self._recovery_timeout_seconds = recovery_timeout_seconds

        if providers:
            for p, prio in providers:
                self.register_provider(p, priority=prio, is_primary=(prio == 1))
        else:
            # Default to YFinanceProvider as primary
            self.register_provider(YFinanceProvider(), priority=1, is_primary=True)

    @property
    def name(self) -> str:
        return "resilient_orchestrator"

    def register_provider(
        self,
        provider: MarketDataProvider,
        priority: int = 1,
        is_primary: bool = False,
    ) -> None:
        """Register a provider with deterministic priority ordering."""
        with self._lock:
            p_name = provider.name
            self._providers[p_name] = provider
            self._priorities[p_name] = priority
            if is_primary or not self._primary_name or priority == 1:
                self._primary_name = p_name
            if not self._active_name:
                self._active_name = self._primary_name

            if p_name not in self._circuit_breakers:
                self._circuit_breakers[p_name] = CircuitBreaker(
                    name=p_name,
                    failure_threshold=self._failure_threshold,
                    recovery_timeout_seconds=self._recovery_timeout_seconds,
                )

    def _sanitize_metadata(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        """Redact any sensitive credentials or tokens from telemetry metadata."""
        sanitized = {}
        for k, v in meta.items():
            if any(s in k.lower() for s in self.SENSITIVE_KEYS):
                sanitized[k] = "***REDACTED***"
            elif isinstance(v, dict):
                sanitized[k] = self._sanitize_metadata(v)
            else:
                sanitized[k] = v
        return sanitized

    def _emit_telemetry(self, event_name: str, details: Dict[str, Any]) -> None:
        """Emit telemetry event with zero secret leakage."""
        clean_details = self._sanitize_metadata(details)
        if self._telemetry_engine and hasattr(self._telemetry_engine, "record_event"):
            try:
                from backend.domain.telemetry_schemas import ExecutionEventType, EventSeverity
                ev_type = getattr(ExecutionEventType, "BROKER_REQUEST", ExecutionEventType.ORDER_ACKNOWLEDGED)
                self._telemetry_engine.record_event(
                    event_type=ev_type,
                    execution_id=f"DATA-PROVIDER-{uuid.uuid4().hex[:8]}",
                    reason=f"Provider Event: {event_name}",
                    severity=EventSeverity.INFO,
                    metadata={"event": event_name, **clean_details},
                )
            except Exception as e:
                logger.debug(f"Telemetry emission skipped: {e}")


    def _get_sorted_providers(self) -> List[Tuple[str, MarketDataProvider, int]]:
        """Return list of (name, provider, priority) sorted deterministically by priority ASC."""
        with self._lock:
            items = []
            for name, prov in self._providers.items():
                items.append((name, prov, self._priorities.get(name, 99)))
            items.sort(key=lambda x: (x[2], x[0]))
            return items

    def get_market_context(
        self,
        symbol: str,
        window: HistoricalWindow = HistoricalWindow.RECENT,
    ) -> MarketContext:
        """
        Fetch normalized market context via resilient multi-provider orchestration.
        Guarantees deterministic fallback, quality validation, bounded timeout, and auditability.
        """
        sorted_providers = self._get_sorted_providers()
        if not sorted_providers:
            return self._build_critical_failure_context(
                symbol=symbol,
                window=window,
                reason="No market data providers registered in orchestrator.",
            )

        last_errors: List[str] = []
        fallback_level = 0

        for idx, (p_name, provider, prio) in enumerate(sorted_providers):
            cb = self._circuit_breakers[p_name]

            # 1. Check Circuit Breaker
            if not cb.allow_request():
                msg = f"Provider '{p_name}' skipped: circuit breaker {cb.state.value}"
                last_errors.append(msg)
                self._emit_telemetry("PROVIDER_CIRCUIT_BLOCKED", {"provider": p_name, "state": cb.state.value})
                fallback_level += 1
                continue

            # Provider selected
            self._emit_telemetry(
                "PROVIDER_SELECTED",
                {"provider": p_name, "priority": prio, "fallback_level": fallback_level, "symbol": symbol}
            )

            # 2. Bounded Execution with Retries
            for attempt in range(self._max_retries + 1):
                t0 = time.monotonic()
                try:
                    # Execute in worker thread with timeout
                    future = self._executor.submit(provider.get_market_context, symbol, window)
                    context: MarketContext = future.result(timeout=self._timeout_seconds)
                    elapsed_ms = (time.monotonic() - t0) * 1000.0

                    # 3. Data Quality Validation Gate
                    val_res: ValidationResult = self._quality_gate.validate(
                        context,
                        expected_symbol=symbol,
                        requested_window=window,
                    )

                    if not val_res.is_valid:
                        rejection_reason = "; ".join(val_res.failure_reasons)
                        cb.record_failure(
                            failure_type=FailureType.VALIDATION_FAILED,
                            reason=rejection_reason,
                            latency_ms=elapsed_ms,
                        )
                        self._emit_telemetry(
                            "DATA_VALIDATION_REJECTION",
                            {
                                "provider": p_name,
                                "symbol": symbol,
                                "reasons": val_res.failure_reasons,
                                "attempt": attempt + 1,
                            }
                        )
                        last_errors.append(f"Provider '{p_name}' rejected: {rejection_reason}")
                        # Move to next provider on validation rejection
                        break

                    # Successful fetch and validation!
                    cb.record_success(latency_ms=elapsed_ms)
                    with self._lock:
                        self._active_name = p_name
                        self._fallback_level = fallback_level

                    # Enrich context metadata
                    warnings = list(context.warnings) if context.warnings else []
                    if fallback_level > 0:
                        warnings.append(f"Fallback provider active: {p_name} (level {fallback_level})")
                        self._emit_telemetry(
                            "PROVIDER_FALLBACK_SUCCESS",
                            {"provider": p_name, "fallback_level": fallback_level, "symbol": symbol}
                        )

                    return context.model_copy(update={
                        "source_provider": p_name,
                        "provider": self.name,
                        "warnings": warnings,
                    })

                except FuturesTimeoutError:
                    elapsed_ms = (time.monotonic() - t0) * 1000.0
                    cb.record_failure(
                        failure_type=FailureType.TIMEOUT,
                        reason=f"Timeout exceeded ({self._timeout_seconds}s)",
                        latency_ms=elapsed_ms,
                    )
                    self._emit_telemetry(
                        "PROVIDER_TIMEOUT",
                        {"provider": p_name, "symbol": symbol, "attempt": attempt + 1, "timeout_s": self._timeout_seconds}
                    )
                    last_errors.append(f"Provider '{p_name}' timed out after {self._timeout_seconds}s")

                except Exception as e:
                    elapsed_ms = (time.monotonic() - t0) * 1000.0
                    err_msg = str(e) or type(e).__name__
                    cb.record_failure(
                        failure_type=FailureType.API_ERROR,
                        reason=err_msg,
                        latency_ms=elapsed_ms,
                    )
                    self._emit_telemetry(
                        "PROVIDER_FAILURE",
                        {"provider": p_name, "symbol": symbol, "attempt": attempt + 1, "error": err_msg}
                    )
                    last_errors.append(f"Provider '{p_name}' error: {err_msg}")

            fallback_level += 1

        # All providers failed! Return explicit degraded state — NEVER fabricate prices!
        self._emit_telemetry(
            "ALL_PROVIDERS_FAILED",
            {"symbol": symbol, "errors": last_errors, "fallback_level": fallback_level}
        )
        return self._build_critical_failure_context(
            symbol=symbol,
            window=window,
            reason=f"All {len(sorted_providers)} providers failed: " + " | ".join(last_errors),
        )

    def get_historical_data(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        """Fetch raw historical dataframe with resilient fallback."""
        sorted_providers = self._get_sorted_providers()
        for p_name, provider, prio in sorted_providers:
            cb = self._circuit_breakers[p_name]
            if not cb.allow_request():
                continue
            t0 = time.monotonic()
            try:
                future = self._executor.submit(provider.get_historical_data, symbol, period)
                df = future.result(timeout=self._timeout_seconds)
                elapsed_ms = (time.monotonic() - t0) * 1000.0
                if df is not None and not df.empty:
                    cb.record_success(latency_ms=elapsed_ms)
                    return df
                else:
                    cb.record_failure(FailureType.VALIDATION_FAILED, "Empty dataframe", elapsed_ms)
            except Exception as e:
                elapsed_ms = (time.monotonic() - t0) * 1000.0
                cb.record_failure(FailureType.API_ERROR, str(e), elapsed_ms)

        return pd.DataFrame()

    def _build_critical_failure_context(
        self,
        symbol: str,
        window: HistoricalWindow,
        reason: str,
    ) -> MarketContext:
        """Generate an explicit, auditable degraded market context without inventing data."""
        now = datetime.now(timezone.utc)
        return MarketContext(
            context_id=f"ctx-degraded-{uuid.uuid4().hex[:8]}",
            symbol=symbol,
            generated_at=now,
            data_timestamp=now,
            provider=self.name,
            source_provider="NONE",
            historical_window=window,
            current_price=0.0,
            quality_status=DataQualityStatus.CRITICAL_FAILURE,
            freshness_status=SnapshotFreshness.INVALID,
            completeness_status="UNAVAILABLE",
            warnings=[reason],
            ohlcv_historical=[],
            technical_indicators={},
            fundamental_data={},
        )

    def reset_circuits(self) -> None:
        """Reset all provider circuit breakers."""
        with self._lock:
            for cb in self._circuit_breakers.values():
                cb.reset()
            self._fallback_level = 0
            self._active_name = self._primary_name

    def get_status(self) -> ProviderOrchestratorStatus:
        """Compute full orchestrator health status and metrics."""
        with self._lock:
            metrics_map: Dict[str, ProviderHealthMetrics] = {}
            has_unavailable = False
            has_degraded = False

            for name, cb in self._circuit_breakers.items():
                prio = self._priorities.get(name, 99)
                is_prim = (name == self._primary_name)
                m = cb.get_metrics(priority=prio, is_primary=is_prim)
                metrics_map[name] = m

                if m.status == ProviderStatus.UNAVAILABLE:
                    has_unavailable = True
                elif m.status == ProviderStatus.DEGRADED:
                    has_degraded = True

            if all(m.status == ProviderStatus.UNAVAILABLE for m in metrics_map.values()) and metrics_map:
                sys_status = ProviderStatus.UNAVAILABLE
            elif has_unavailable or has_degraded or self._fallback_level > 0:
                sys_status = ProviderStatus.DEGRADED
            else:
                sys_status = ProviderStatus.HEALTHY

            warning = None
            if self._fallback_level > 0:
                warning = f"System operating on fallback provider level {self._fallback_level} ({self._active_name})"
            elif sys_status == ProviderStatus.UNAVAILABLE:
                warning = "All registered market data providers are unavailable"

            return ProviderOrchestratorStatus(
                system_status=sys_status,
                primary_provider=self._primary_name or "NONE",
                active_provider=self._active_name or "NONE",
                fallback_level=self._fallback_level,
                is_fallback_active=(self._fallback_level > 0),
                degraded_warning=warning,
                provider_metrics=metrics_map,
                evaluated_at=datetime.now(timezone.utc),
            )
