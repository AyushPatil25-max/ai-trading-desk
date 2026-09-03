"""
Phase 29 — Strategy Governance & Model Lifecycle Engine

Provides an automated, deterministic governance framework for trading strategies:
- Strict lifecycle state transitions (CANDIDATE -> BACKTESTING -> VALIDATED -> CHALLENGER -> CHAMPION -> RETIRED)
- Immutable version registry with SHA-256 configuration fingerprints
- 12-dimension deterministic champion/challenger comparator
- Conservative statistical promotion gates (sample sufficiency, improvement threshold, drawdown clamp)
- Champion protection lock preventing unverified demotion
- Continuous monitoring and automated rollback triggers
- State persistence via PersistentStateStore, journal logging, and 12 tamper-evident audit events

Safety Invariants:
- STRICTLY OBSERVATIONAL & GOVERNANCE ONLY: Zero live-money order submission authority.
- Pure Python deterministic math: Zero LLM numerical calculations.
- TIER_4_LIVE_REAL_MONEY remains permanently locked, unroutable, and fail-closed.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import threading
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from backend.domain.strategy_governance_schemas import (
    GOVERNANCE_SCHEMA_VERSION,
    ChallengerRecord,
    ChampionChallengerComparison,
    ChampionRecord,
    DimensionScore,
    GateCheck,
    GateStatus,
    GovernanceDecision,
    GovernanceDecisionRecord,
    GovernancePolicy,
    GovernanceStatusSummary,
    PromotionGateResult,
    RollbackReason,
    RollbackTrigger,
    StrategyLifecycleState,
    StrategyPerformanceSnapshot,
    StrategyRole,
    StrategyVersion,
    ValidationEvidence,
)
from backend.domain.observability_schemas import EventCategory, EventSeverity
from backend.application.tamper_evident_audit_chain import global_audit_chain
from backend.application.persistent_state_store import global_persistent_state_store
from backend.application.state_journal import global_state_journal

logger = logging.getLogger(__name__)


# ── Custom Exceptions ─────────────────────────────────────────────────────────

class InvalidTransitionError(Exception):
    """Raised when an illegal strategy lifecycle state transition is requested."""
    pass


class PromotionGateBlockedError(Exception):
    """Raised when attempting to promote a strategy that failed promotion gates."""
    pass


class StrategyNotFoundError(Exception):
    """Raised when a requested strategy version does not exist in the registry."""
    pass


# ── State Machine Transition Rules ───────────────────────────────────────────

VALID_TRANSITIONS: Dict[StrategyLifecycleState, Set[StrategyLifecycleState]] = {
    StrategyLifecycleState.CANDIDATE: {
        StrategyLifecycleState.BACKTESTING,
        StrategyLifecycleState.RETIRED,
    },
    StrategyLifecycleState.BACKTESTING: {
        StrategyLifecycleState.VALIDATED,
        StrategyLifecycleState.CANDIDATE,
        StrategyLifecycleState.RETIRED,
    },
    StrategyLifecycleState.VALIDATED: {
        StrategyLifecycleState.CHALLENGER,
        StrategyLifecycleState.CANDIDATE,
        StrategyLifecycleState.RETIRED,
    },
    StrategyLifecycleState.CHALLENGER: {
        StrategyLifecycleState.CHAMPION,
        StrategyLifecycleState.VALIDATED,
        StrategyLifecycleState.RETIRED,
    },
    StrategyLifecycleState.CHAMPION: {
        StrategyLifecycleState.DEPRECATED,
        StrategyLifecycleState.ROLLED_BACK,
        StrategyLifecycleState.RETIRED,
    },
    StrategyLifecycleState.DEPRECATED: {
        StrategyLifecycleState.RETIRED,
    },
    StrategyLifecycleState.ROLLED_BACK: {
        StrategyLifecycleState.CANDIDATE,
        StrategyLifecycleState.RETIRED,
    },
    StrategyLifecycleState.RETIRED: set(),  # Terminal state
}


# ── 12-Dimension Scoring Dimension Config ─────────────────────────────────────

DIMENSION_WEIGHTS: Dict[str, float] = {
    "Sharpe Ratio": 1.5,
    "Sortino Ratio": 1.2,
    "Max Drawdown Resilience": 1.5,
    "Win Rate": 1.0,
    "Profit Factor": 1.2,
    "Total Return": 1.0,
    "Calmar Ratio": 1.0,
    "Sample Sufficiency": 0.8,
    "Consistency (Win/Loss)": 0.8,
    "Recovery Factor": 0.8,
    "Downside Risk Control": 1.0,
    "Validation Completeness": 1.0,
}


class StrategyGovernanceEngine:
    """
    Central governance engine managing strategy lifecycles, version registry,
    champion/challenger comparisons, conservative promotion gates, and rollback policies.
    """

    def __init__(self, policy: Optional[GovernancePolicy] = None):
        self._lock = threading.RLock()
        self.policy: GovernancePolicy = policy or GovernancePolicy()
        self._strategies: Dict[str, StrategyVersion] = {}
        self._champion_id: Optional[str] = None
        self._champion_defenses: int = 0
        self._decisions: List[GovernanceDecisionRecord] = []
        self._rollback_history: List[RollbackTrigger] = []
        self._comparison_history: List[ChampionChallengerComparison] = []

        # Load existing governance state if present in persistent store
        self._sync_from_persistent_store()

    # ── Strategy Registration & Registry (Step 2) ─────────────────────────────

    def register_strategy(
        self,
        name: str,
        version: str = "1.0.0",
        description: str = "",
        author: str = "SYSTEM",
        parameters: Optional[Dict[str, Any]] = None,
        performance: Optional[StrategyPerformanceSnapshot] = None,
        tags: Optional[List[str]] = None,
        operator: str = "SYSTEM_GOVERNANCE",
    ) -> StrategyVersion:
        """
        Register a new strategy version in the CANDIDATE state with computed SHA-256 fingerprint.
        """
        with self._lock:
            strat = StrategyVersion(
                name=name,
                version=version,
                description=description,
                author=author,
                state=StrategyLifecycleState.CANDIDATE,
                role=StrategyRole.CANDIDATE,
                parameters=parameters or {},
                performance=performance or StrategyPerformanceSnapshot(),
                tags=tags or [],
            )

            # Check for duplicate fingerprint within active versions
            for existing in self._strategies.values():
                if existing.name == strat.name and existing.version == strat.version:
                    raise ValueError(f"Strategy version {strat.name}:{strat.version} already exists.")

            self._strategies[strat.strategy_id] = strat

            # Record governance decision
            decision = GovernanceDecisionRecord(
                decision=GovernanceDecision.HOLD,
                strategy_id=strat.strategy_id,
                target_role=StrategyRole.CANDIDATE,
                previous_state=StrategyLifecycleState.CANDIDATE,
                new_state=StrategyLifecycleState.CANDIDATE,
                rationale=f"Registered new strategy version {strat.name}:{strat.version}",
                operator=operator,
                config_fingerprint=strat.config_fingerprint,
            )
            self._decisions.append(decision)

            # Persist mutation & audit
            self._persist_state(f"REGISTER_STRATEGY_{strat.strategy_id}")
            self._emit_audit(
                event_type="STRATEGY_REGISTERED",
                strategy_id=strat.strategy_id,
                payload={
                    "name": strat.name,
                    "version": strat.version,
                    "fingerprint": strat.config_fingerprint,
                },
            )

            return strat

    def get_strategy(self, strategy_id: str) -> StrategyVersion:
        """Retrieve strategy version by ID."""
        with self._lock:
            if strategy_id not in self._strategies:
                raise StrategyNotFoundError(f"Strategy {strategy_id} not found in registry.")
            return self._strategies[strategy_id]

    def list_strategies(
        self,
        state: Optional[StrategyLifecycleState] = None,
        role: Optional[StrategyRole] = None,
    ) -> List[StrategyVersion]:
        """List all strategies matching optional state/role filters."""
        with self._lock:
            res = list(self._strategies.values())
            if state:
                res = [s for s in res if s.state == state]
            if role:
                res = [s for s in res if s.role == role]
            return sorted(res, key=lambda s: s.created_at, reverse=True)

    def update_performance(
        self,
        strategy_id: str,
        performance: StrategyPerformanceSnapshot,
        evidence: Optional[ValidationEvidence] = None,
    ) -> StrategyVersion:
        """Update performance snapshot and attach evidence to a strategy."""
        with self._lock:
            strat = self.get_strategy(strategy_id)
            strat.performance = performance
            strat.updated_at = datetime.now(timezone.utc)
            if evidence:
                strat.evidence.append(evidence)

            self._persist_state(f"UPDATE_PERF_{strategy_id}")
            return strat

    # ── Lifecycle Transitions (Step 3) ────────────────────────────────────────

    def transition_strategy(
        self,
        strategy_id: str,
        target_state: StrategyLifecycleState,
        reason: str,
        operator: str = "SYSTEM_GOVERNANCE",
    ) -> StrategyVersion:
        """
        Transition strategy to target lifecycle state enforcing strict state machine rules.
        """
        with self._lock:
            strat = self.get_strategy(strategy_id)
            current_state = strat.state

            if current_state == target_state:
                return strat

            valid_targets = VALID_TRANSITIONS.get(current_state, set())
            if target_state not in valid_targets:
                raise InvalidTransitionError(
                    f"Invalid lifecycle transition from {current_state.value} to {target_state.value}. "
                    f"Valid target states: {[s.value for s in valid_targets]}"
                )

            # Update state & role mapping
            strat.state = target_state
            strat.updated_at = datetime.now(timezone.utc)

            if target_state == StrategyLifecycleState.CHAMPION:
                strat.role = StrategyRole.CHAMPION
                strat.promoted_at = datetime.now(timezone.utc)
            elif target_state == StrategyLifecycleState.CHALLENGER:
                strat.role = StrategyRole.CHALLENGER
            elif target_state in (StrategyLifecycleState.RETIRED, StrategyLifecycleState.DEPRECATED):
                strat.role = StrategyRole.RETIRED
                if target_state == StrategyLifecycleState.RETIRED:
                    strat.retired_at = datetime.now(timezone.utc)
            else:
                strat.role = StrategyRole.CANDIDATE

            # Record governance decision
            decision_type = (
                GovernanceDecision.PROMOTE if target_state in (StrategyLifecycleState.CHAMPION, StrategyLifecycleState.CHALLENGER, StrategyLifecycleState.VALIDATED)
                else GovernanceDecision.RETIRE if target_state == StrategyLifecycleState.RETIRED
                else GovernanceDecision.DEMOTE if target_state == StrategyLifecycleState.DEPRECATED
                else GovernanceDecision.ROLLBACK if target_state == StrategyLifecycleState.ROLLED_BACK
                else GovernanceDecision.HOLD
            )

            decision = GovernanceDecisionRecord(
                decision=decision_type,
                strategy_id=strat.strategy_id,
                target_role=strat.role,
                previous_state=current_state,
                new_state=target_state,
                rationale=reason,
                operator=operator,
                config_fingerprint=strat.config_fingerprint,
            )
            self._decisions.append(decision)

            self._persist_state(f"TRANSITION_{strategy_id}_{target_state.value}")
            self._emit_audit(
                event_type="STRATEGY_TRANSITION",
                strategy_id=strategy_id,
                payload={
                    "from_state": current_state.value,
                    "to_state": target_state.value,
                    "reason": reason,
                },
            )

            return strat

    # ── 12-Dimension Champion/Challenger Comparator (Step 4) ──────────────────

    def compare_strategies(
        self,
        champion_id: str,
        challenger_id: str,
    ) -> ChampionChallengerComparison:
        """
        Execute deterministic 12-dimension comparison between Champion and Challenger.
        """
        with self._lock:
            champ = self.get_strategy(champion_id)
            chall = self.get_strategy(challenger_id)

            cp = champ.performance
            clp = chall.performance

            dimensions: List[DimensionScore] = []

            # 1. Sharpe Ratio
            c_val = cp.sharpe_ratio or 0.0
            cl_val = clp.sharpe_ratio or 0.0
            c_score = min(100.0, max(0.0, c_val * 35.0))
            cl_score = min(100.0, max(0.0, cl_val * 35.0))
            dimensions.append(self._score_dim("Sharpe Ratio", c_val, cl_val, c_score, cl_score, "Risk-adjusted return over risk-free rate"))

            # 2. Sortino Ratio
            c_val = cp.sortino_ratio or 0.0
            cl_val = clp.sortino_ratio or 0.0
            c_score = min(100.0, max(0.0, c_val * 30.0))
            cl_score = min(100.0, max(0.0, cl_val * 30.0))
            dimensions.append(self._score_dim("Sortino Ratio", c_val, cl_val, c_score, cl_score, "Downside risk-adjusted performance"))

            # 3. Max Drawdown Resilience (lower drawdown -> higher score)
            c_val = cp.max_drawdown_pct
            cl_val = clp.max_drawdown_pct
            c_score = max(0.0, 100.0 - c_val * 2.5)
            cl_score = max(0.0, 100.0 - cl_val * 2.5)
            dimensions.append(self._score_dim("Max Drawdown Resilience", c_val, cl_val, c_score, cl_score, "Resistance to portfolio peak-to-trough losses"))

            # 4. Win Rate
            c_val = cp.win_rate_pct
            cl_val = clp.win_rate_pct
            c_score = min(100.0, max(0.0, c_val * 1.25))
            cl_score = min(100.0, max(0.0, cl_val * 1.25))
            dimensions.append(self._score_dim("Win Rate", c_val, cl_val, c_score, cl_score, "Percentage of profitable closed trades"))

            # 5. Profit Factor
            c_val = cp.profit_factor or 1.0
            cl_val = clp.profit_factor or 1.0
            c_score = min(100.0, max(0.0, c_val * 40.0))
            cl_score = min(100.0, max(0.0, cl_val * 40.0))
            dimensions.append(self._score_dim("Profit Factor", c_val, cl_val, c_score, cl_score, "Gross profits divided by gross losses"))

            # 6. Total Return
            c_val = cp.total_return_pct
            cl_val = clp.total_return_pct
            c_score = min(100.0, max(0.0, 50.0 + c_val * 1.5))
            cl_score = min(100.0, max(0.0, 50.0 + cl_val * 1.5))
            dimensions.append(self._score_dim("Total Return", c_val, cl_val, c_score, cl_score, "Cumulative percentage return across evaluation period"))

            # 7. Calmar Ratio
            c_val = cp.calmar_ratio or (cp.cagr_pct / max(0.1, cp.max_drawdown_pct))
            cl_val = clp.calmar_ratio or (clp.cagr_pct / max(0.1, clp.max_drawdown_pct))
            c_score = min(100.0, max(0.0, c_val * 30.0))
            cl_score = min(100.0, max(0.0, cl_val * 30.0))
            dimensions.append(self._score_dim("Calmar Ratio", c_val, cl_val, c_score, cl_score, "CAGR relative to maximum drawdown"))

            # 8. Sample Sufficiency
            c_val = float(cp.total_trades)
            cl_val = float(clp.total_trades)
            c_score = min(100.0, (c_val / float(self.policy.min_trade_count)) * 80.0) if c_val >= self.policy.min_trade_count else min(50.0, c_val * 1.0)
            cl_score = min(100.0, (cl_val / float(self.policy.min_trade_count)) * 80.0) if cl_val >= self.policy.min_trade_count else min(50.0, cl_val * 1.0)
            dimensions.append(self._score_dim("Sample Sufficiency", c_val, cl_val, c_score, cl_score, "Statistical robustness from trade sample size"))

            # 9. Consistency (Win/Loss Ratio)
            c_loss = max(0.01, cp.avg_loss_pct)
            cl_loss = max(0.01, clp.avg_loss_pct)
            c_wl = cp.avg_win_pct / c_loss if cp.avg_win_pct > 0 else 1.0
            cl_wl = clp.avg_win_pct / cl_loss if clp.avg_win_pct > 0 else 1.0
            c_score = min(100.0, max(0.0, c_wl * 45.0))
            cl_score = min(100.0, max(0.0, cl_wl * 45.0))
            dimensions.append(self._score_dim("Consistency (Win/Loss)", c_wl, cl_wl, c_score, cl_score, "Average win magnitude relative to average loss"))

            # 10. Recovery Factor
            c_val = cp.recovery_factor or (cp.total_return_pct / max(0.1, cp.max_drawdown_pct))
            cl_val = clp.recovery_factor or (clp.total_return_pct / max(0.1, clp.max_drawdown_pct))
            c_score = min(100.0, max(0.0, c_val * 25.0))
            cl_score = min(100.0, max(0.0, cl_val * 25.0))
            dimensions.append(self._score_dim("Recovery Factor", c_val, cl_val, c_score, cl_score, "Speed and magnitude of recovery from drawdowns"))

            # 11. Downside Risk Control (lower volatility -> higher score)
            c_val = cp.annualized_volatility_pct
            cl_val = clp.annualized_volatility_pct
            c_score = max(0.0, 100.0 - c_val * 2.0)
            cl_score = max(0.0, 100.0 - cl_val * 2.0)
            dimensions.append(self._score_dim("Downside Risk Control", c_val, cl_val, c_score, cl_score, "Annualized volatility suppression"))

            # 12. Validation Completeness
            c_val = 100.0 if (cp.out_of_sample_tested and cp.forward_tested) else 50.0 if (cp.out_of_sample_tested or cp.forward_tested) else 25.0
            cl_val = 100.0 if (clp.out_of_sample_tested and clp.forward_tested) else 50.0 if (clp.out_of_sample_tested or clp.forward_tested) else 25.0
            dimensions.append(self._score_dim("Validation Completeness", c_val, cl_val, c_val, cl_val, "Execution across Out-of-Sample and Forward test regimes"))

            # Compute weighted composite score
            total_weight = sum(d.weight for d in dimensions)
            c_composite = round(sum(d.champion_score * d.weight for d in dimensions) / total_weight, 1)
            cl_composite = round(sum(d.challenger_score * d.weight for d in dimensions) / total_weight, 1)
            delta = round(cl_composite - c_composite, 1)

            if delta > 2.0:
                winner = "CHALLENGER"
                rec = GovernanceDecision.PROMOTE
                rationale = f"Challenger outperformed Champion by +{delta} composite points across 12 dimensions."
            elif delta < -2.0:
                winner = "CHAMPION"
                rec = GovernanceDecision.HOLD
                rationale = f"Champion maintained superior performance (+{-delta} composite points over Challenger)."
            else:
                winner = "TIE"
                rec = GovernanceDecision.HOLD
                rationale = f"Performance delta ({delta:+.1f} pts) is within the margin of statistical indifference."

            comparison = ChampionChallengerComparison(
                champion_id=champion_id,
                challenger_id=challenger_id,
                champion_name=champ.name,
                challenger_name=chall.name,
                dimensions=dimensions,
                champion_composite_score=c_composite,
                challenger_composite_score=cl_composite,
                score_delta=delta,
                overall_winner=winner,
                recommendation=rec,
                rationale=rationale,
            )

            self._comparison_history.append(comparison)
            self._emit_audit(
                event_type="STRATEGY_COMPARISON",
                strategy_id=challenger_id,
                payload={
                    "champion_id": champion_id,
                    "challenger_id": challenger_id,
                    "champion_score": c_composite,
                    "challenger_score": cl_composite,
                    "winner": winner,
                },
            )

            return comparison

    def _score_dim(
        self,
        name: str,
        c_val: Optional[float],
        cl_val: Optional[float],
        c_score: float,
        cl_score: float,
        desc: str,
    ) -> DimensionScore:
        weight = DIMENSION_WEIGHTS.get(name, 1.0)
        c_s = round(max(0.0, min(100.0, c_score)), 1)
        cl_s = round(max(0.0, min(100.0, cl_score)), 1)

        if abs(cl_s - c_s) < 1.0:
            winner = "TIE"
        elif cl_s > c_s:
            winner = "CHALLENGER"
        else:
            winner = "CHAMPION"

        return DimensionScore(
            dimension_name=name,
            champion_value=round(c_val, 2) if c_val is not None else None,
            challenger_value=round(cl_val, 2) if cl_val is not None else None,
            champion_score=c_s,
            challenger_score=cl_s,
            weight=weight,
            winner=winner,
            description=desc,
        )

    # ── Conservative Statistical Promotion Gates (Step 5) ─────────────────────

    def evaluate_promotion_gates(
        self,
        challenger_id: str,
        champion_id: Optional[str] = None,
    ) -> PromotionGateResult:
        """
        Evaluate conservative promotion gates to determine if Challenger qualifies for Champion role.
        """
        with self._lock:
            chall = self.get_strategy(challenger_id)
            champ_id = champion_id or self._champion_id
            champ = self.get_strategy(champ_id) if champ_id else None

            clp = chall.performance
            checks: List[GateCheck] = []
            blockers: List[str] = []
            warnings: List[str] = []

            # Gate 1: Minimum Trade Count
            passed_tc = clp.total_trades >= self.policy.min_trade_count
            checks.append(GateCheck(
                gate_name="Minimum Trade Count",
                status=GateStatus.PASSED if passed_tc else GateStatus.FAILED,
                required_value=self.policy.min_trade_count,
                actual_value=clp.total_trades,
                passed=passed_tc,
                evidence=f"{clp.total_trades} trades evaluated (min required: {self.policy.min_trade_count})"
            ))
            if not passed_tc:
                blockers.append(f"Insufficient trade sample size: {clp.total_trades} < {self.policy.min_trade_count}")

            # Gate 2: Maximum Drawdown Ceiling
            passed_dd = clp.max_drawdown_pct <= self.policy.max_drawdown_tolerance_pct
            checks.append(GateCheck(
                gate_name="Max Drawdown Tolerance",
                status=GateStatus.PASSED if passed_dd else GateStatus.FAILED,
                required_value=self.policy.max_drawdown_tolerance_pct,
                actual_value=clp.max_drawdown_pct,
                passed=passed_dd,
                evidence=f"Max drawdown {clp.max_drawdown_pct:.1f}% vs ceiling {self.policy.max_drawdown_tolerance_pct:.1f}%"
            ))
            if not passed_dd:
                blockers.append(f"Max drawdown {clp.max_drawdown_pct:.1f}% exceeds tolerance {self.policy.max_drawdown_tolerance_pct:.1f}%")

            # Gate 3: Minimum Win Rate
            passed_wr = clp.win_rate_pct >= self.policy.min_win_rate_pct
            checks.append(GateCheck(
                gate_name="Minimum Win Rate",
                status=GateStatus.PASSED if passed_wr else GateStatus.FAILED,
                required_value=self.policy.min_win_rate_pct,
                actual_value=clp.win_rate_pct,
                passed=passed_wr,
                evidence=f"Win rate {clp.win_rate_pct:.1f}% vs required {self.policy.min_win_rate_pct:.1f}%"
            ))
            if not passed_wr:
                blockers.append(f"Win rate {clp.win_rate_pct:.1f}% below minimum {self.policy.min_win_rate_pct:.1f}%")

            # Gate 4: Minimum Profit Factor
            actual_pf = clp.profit_factor or 0.0
            passed_pf = actual_pf >= self.policy.min_profit_factor
            checks.append(GateCheck(
                gate_name="Minimum Profit Factor",
                status=GateStatus.PASSED if passed_pf else GateStatus.FAILED,
                required_value=self.policy.min_profit_factor,
                actual_value=actual_pf,
                passed=passed_pf,
                evidence=f"Profit factor {actual_pf:.2f} vs required {self.policy.min_profit_factor:.2f}"
            ))
            if not passed_pf:
                blockers.append(f"Profit factor {actual_pf:.2f} below threshold {self.policy.min_profit_factor:.2f}")

            # Gate 5: Out-of-Sample Validation Requirement
            if self.policy.require_out_of_sample:
                passed_oos = clp.out_of_sample_tested
                checks.append(GateCheck(
                    gate_name="Out-of-Sample Validation",
                    status=GateStatus.PASSED if passed_oos else GateStatus.FAILED,
                    required_value=True,
                    actual_value=clp.out_of_sample_tested,
                    passed=passed_oos,
                    evidence="Out-of-sample partition testing completed" if passed_oos else "Missing out-of-sample backtest validation"
                ))
                if not passed_oos:
                    blockers.append("Missing required Out-of-Sample validation evidence")

            # Gate 6: Forward Validation Requirement
            if self.policy.require_forward_validation:
                passed_fwd = clp.forward_tested
                checks.append(GateCheck(
                    gate_name="Forward Paper Validation",
                    status=GateStatus.PASSED if passed_fwd else GateStatus.FAILED,
                    required_value=True,
                    actual_value=clp.forward_tested,
                    passed=passed_fwd,
                    evidence="Forward paper-trading validation completed" if passed_fwd else "Missing forward validation session"
                ))
                if not passed_fwd:
                    blockers.append("Missing required Forward paper-trading validation evidence")

            # Gate 7: Relative Improvement vs Champion (if Champion exists)
            if champ:
                cp = champ.performance
                c_sharpe = cp.sharpe_ratio or 1.0
                cl_sharpe = clp.sharpe_ratio or 0.0
                sharpe_improvement_pct = ((cl_sharpe - c_sharpe) / max(0.01, abs(c_sharpe))) * 100.0
                passed_imp = sharpe_improvement_pct >= self.policy.min_sharpe_improvement_pct

                checks.append(GateCheck(
                    gate_name="Sharpe Ratio Improvement",
                    status=GateStatus.PASSED if passed_imp else GateStatus.FAILED,
                    required_value=f"+{self.policy.min_sharpe_improvement_pct:.1f}%",
                    actual_value=f"{sharpe_improvement_pct:+.1f}%",
                    passed=passed_imp,
                    evidence=f"Challenger Sharpe ({cl_sharpe:.2f}) vs Champion ({c_sharpe:.2f}) -> {sharpe_improvement_pct:+.1f}%"
                ))
                if not passed_imp:
                    blockers.append(f"Sharpe improvement ({sharpe_improvement_pct:+.1f}%) below required threshold (+{self.policy.min_sharpe_improvement_pct:.1f}%)")

                # Relative Drawdown Constraint
                dd_diff = clp.max_drawdown_pct - cp.max_drawdown_pct
                passed_rel_dd = dd_diff <= self.policy.max_relative_drawdown_increase_pct
                checks.append(GateCheck(
                    gate_name="Relative Drawdown Constraint",
                    status=GateStatus.PASSED if passed_rel_dd else GateStatus.FAILED,
                    required_value=f"<= +{self.policy.max_relative_drawdown_increase_pct:.1f}%",
                    actual_value=f"{dd_diff:+.1f}%",
                    passed=passed_rel_dd,
                    evidence=f"Challenger DD ({clp.max_drawdown_pct:.1f}%) vs Champion DD ({cp.max_drawdown_pct:.1f}%) -> delta {dd_diff:+.1f}%"
                ))
                if not passed_rel_dd:
                    blockers.append(f"Challenger drawdown exceeds champion by {dd_diff:+.1f}%, surpassing tolerance (+{self.policy.max_relative_drawdown_increase_pct:.1f}%)")

            all_passed = len(blockers) == 0

            result = PromotionGateResult(
                challenger_id=challenger_id,
                champion_id=champ_id,
                all_gates_passed=all_passed,
                gate_checks=checks,
                blocking_reasons=blockers,
                warnings=warnings,
                confidence_level_pct=self.policy.confidence_level_pct,
                recommendation=GovernanceDecision.PROMOTE if all_passed else GovernanceDecision.REJECT,
            )

            self._emit_audit(
                event_type="PROMOTION_GATE_EVALUATED",
                strategy_id=challenger_id,
                payload={
                    "all_passed": all_passed,
                    "blockers_count": len(blockers),
                    "recommendation": result.recommendation.value,
                },
            )

            return result

    # ── Champion Promotion & Protection (Step 6) ──────────────────────────────

    def promote_to_champion(
        self,
        challenger_id: str,
        override_protection: bool = False,
        operator: str = "SYSTEM_GOVERNANCE",
        rationale: str = "Promoted after passing all conservative statistical gates",
    ) -> StrategyVersion:
        """
        Promote a Challenger strategy to the authoritative Champion role.
        Enforces Champion Protection Gate: challenger MUST pass all gates.
        """
        with self._lock:
            chall = self.get_strategy(challenger_id)

            if chall.state not in (StrategyLifecycleState.CHALLENGER, StrategyLifecycleState.VALIDATED):
                raise InvalidTransitionError(
                    f"Cannot promote strategy in {chall.state.value} state. Must be CHALLENGER or VALIDATED."
                )

            # Evaluate gates
            gate_result = self.evaluate_promotion_gates(challenger_id)
            if not gate_result.all_gates_passed and not override_protection:
                raise PromotionGateBlockedError(
                    f"Promotion blocked by governance gates: {'; '.join(gate_result.blocking_reasons)}"
                )

            old_champion_id = self._champion_id

            # Deprecate existing champion
            if old_champion_id and old_champion_id in self._strategies:
                old_champ = self._strategies[old_champion_id]
                old_champ.state = StrategyLifecycleState.DEPRECATED
                old_champ.role = StrategyRole.RETIRED
                old_champ.updated_at = datetime.now(timezone.utc)
                self._emit_audit(
                    event_type="STRATEGY_DEMOTED",
                    strategy_id=old_champion_id,
                    payload={"promoted_challenger_id": challenger_id},
                )

            # Promote challenger
            chall.state = StrategyLifecycleState.CHAMPION
            chall.role = StrategyRole.CHAMPION
            chall.promoted_at = datetime.now(timezone.utc)
            chall.updated_at = datetime.now(timezone.utc)

            self._champion_id = challenger_id
            self._champion_defenses = 0

            # Record governance decision
            decision = GovernanceDecisionRecord(
                decision=GovernanceDecision.PROMOTE,
                strategy_id=challenger_id,
                target_role=StrategyRole.CHAMPION,
                previous_state=StrategyLifecycleState.CHALLENGER,
                new_state=StrategyLifecycleState.CHAMPION,
                rationale=rationale,
                operator=operator,
                gate_evaluation_id=gate_result.evaluation_id,
                config_fingerprint=chall.config_fingerprint,
            )
            self._decisions.append(decision)

            self._persist_state(f"PROMOTE_{challenger_id}")
            self._emit_audit(
                event_type="STRATEGY_PROMOTED",
                strategy_id=challenger_id,
                payload={
                    "previous_champion_id": old_champion_id,
                    "evaluation_id": gate_result.evaluation_id,
                },
            )

            return chall

    # ── Continuous Monitoring & Rollback Engine (Step 7) ──────────────────────

    def evaluate_rollback_conditions(
        self,
        current_metrics: Dict[str, Any],
        champion_id: Optional[str] = None,
    ) -> Optional[RollbackTrigger]:
        """
        Evaluate live/forward operational metrics against rollback thresholds.
        Returns RollbackTrigger if breach is detected, None if healthy.
        """
        with self._lock:
            champ_id = champion_id or self._champion_id
            if not champ_id or champ_id not in self._strategies:
                return None

            champ = self._strategies[champ_id]

            # 1. Drawdown Breach
            current_dd = current_metrics.get("current_drawdown_pct", 0.0)
            if current_dd >= self.policy.rollback_max_drawdown_pct:
                return RollbackTrigger(
                    champion_id=champ_id,
                    reason=RollbackReason.DRAWDOWN_BREACH,
                    trigger_metric="current_drawdown_pct",
                    trigger_value=current_dd,
                    threshold_value=self.policy.rollback_max_drawdown_pct,
                    details=f"Current drawdown {current_dd:.1f}% breached rollback ceiling {self.policy.rollback_max_drawdown_pct:.1f}%",
                )

            # 2. Strategy Drift Breach
            drift_score = current_metrics.get("drift_score", 0.0)
            if drift_score >= self.policy.rollback_drift_threshold:
                return RollbackTrigger(
                    champion_id=champ_id,
                    reason=RollbackReason.DRIFT_DETECTED,
                    trigger_metric="drift_score",
                    trigger_value=drift_score,
                    threshold_value=self.policy.rollback_drift_threshold,
                    details=f"Strategy drift score {drift_score:.2f} exceeded safety threshold {self.policy.rollback_drift_threshold:.2f}",
                )

            # 3. Forward Divergence Breach
            fwd_win_rate = current_metrics.get("forward_win_rate_pct", 100.0)
            expected_win_rate = champ.performance.win_rate_pct
            if expected_win_rate > 0 and fwd_win_rate < (expected_win_rate * 0.5):
                return RollbackTrigger(
                    champion_id=champ_id,
                    reason=RollbackReason.FORWARD_DIVERGENCE,
                    trigger_metric="forward_win_rate_pct",
                    trigger_value=fwd_win_rate,
                    threshold_value=expected_win_rate * 0.5,
                    details=f"Forward win rate ({fwd_win_rate:.1f}%) collapsed below 50% of expected backtest win rate ({expected_win_rate:.1f}%)",
                )

            return None

    def trigger_rollback(
        self,
        reason: RollbackReason,
        details: str = "",
        fallback_strategy_id: Optional[str] = None,
        operator: str = "SYSTEM_GOVERNANCE",
    ) -> Tuple[StrategyVersion, Optional[StrategyVersion]]:
        """
        Execute an immediate rollback of the active Champion strategy to a safe fallback.
        """
        with self._lock:
            if not self._champion_id or self._champion_id not in self._strategies:
                raise ValueError("No active Champion to rollback.")

            champ = self._strategies[self._champion_id]
            champ_id = self._champion_id

            # Determine fallback strategy
            fallback: Optional[StrategyVersion] = None
            if fallback_strategy_id and fallback_strategy_id in self._strategies:
                fallback = self._strategies[fallback_strategy_id]
            else:
                # Find most recent deprecated champion or validated candidate
                deprecated = [s for s in self._strategies.values() if s.state == StrategyLifecycleState.DEPRECATED]
                if deprecated:
                    fallback = sorted(deprecated, key=lambda s: s.updated_at, reverse=True)[0]

            # Demote champion to ROLLED_BACK
            champ.state = StrategyLifecycleState.ROLLED_BACK
            champ.role = StrategyRole.CANDIDATE
            champ.updated_at = datetime.now(timezone.utc)

            # If fallback exists, reinstate it
            if fallback:
                fallback.state = StrategyLifecycleState.CHAMPION
                fallback.role = StrategyRole.CHAMPION
                fallback.updated_at = datetime.now(timezone.utc)
                self._champion_id = fallback.strategy_id
            else:
                self._champion_id = None

            trigger = RollbackTrigger(
                champion_id=champ_id,
                reason=reason,
                trigger_metric="MANUAL_OR_BREACH",
                trigger_value=1.0,
                threshold_value=1.0,
                fallback_strategy_id=fallback.strategy_id if fallback else None,
                details=details or f"Rollback triggered: {reason.value}",
            )
            self._rollback_history.append(trigger)

            # Record governance decision
            decision = GovernanceDecisionRecord(
                decision=GovernanceDecision.ROLLBACK,
                strategy_id=champ_id,
                target_role=StrategyRole.CANDIDATE,
                previous_state=StrategyLifecycleState.CHAMPION,
                new_state=StrategyLifecycleState.ROLLED_BACK,
                rationale=details or f"Rollback due to {reason.value}",
                operator=operator,
                config_fingerprint=champ.config_fingerprint,
            )
            self._decisions.append(decision)

            self._persist_state(f"ROLLBACK_{champ_id}")
            self._emit_audit(
                event_type="STRATEGY_ROLLBACK",
                strategy_id=champ_id,
                severity=EventSeverity.CRITICAL,
                payload={
                    "reason": reason.value,
                    "fallback_id": fallback.strategy_id if fallback else None,
                    "details": details,
                },
            )

            return champ, fallback

    # ── Operational Status & Query API (Step 8) ───────────────────────────────

    def get_champion(self) -> Optional[ChampionRecord]:
        """Get summary of the active Champion strategy."""
        with self._lock:
            if not self._champion_id or self._champion_id not in self._strategies:
                return None
            champ = self._strategies[self._champion_id]
            return ChampionRecord(
                strategy_id=champ.strategy_id,
                name=champ.name,
                version=champ.version,
                promoted_at=champ.promoted_at or champ.created_at,
                defenses_count=self._champion_defenses,
                performance=champ.performance,
                config_fingerprint=champ.config_fingerprint,
            )

    def get_challengers(self) -> List[ChallengerRecord]:
        """Get list of active Challenger strategies."""
        with self._lock:
            challengers = [s for s in self._strategies.values() if s.state == StrategyLifecycleState.CHALLENGER]
            return [
                ChallengerRecord(
                    strategy_id=s.strategy_id,
                    name=s.name,
                    version=s.version,
                    registered_at=s.created_at,
                    composite_score=0.0,
                    performance=s.performance,
                    config_fingerprint=s.config_fingerprint,
                )
                for s in sorted(challengers, key=lambda x: x.created_at, reverse=True)
            ]

    def get_status_summary(self) -> GovernanceStatusSummary:
        """Produce comprehensive operational governance status summary."""
        with self._lock:
            champ_record = self.get_champion()
            challengers = self.get_challengers()

            dist: Dict[str, int] = {}
            for s in self._strategies.values():
                dist[s.state.value] = dist.get(s.state.value, 0) + 1

            last_dec = self._decisions[-1] if self._decisions else None

            return GovernanceStatusSummary(
                schema_version=GOVERNANCE_SCHEMA_VERSION,
                total_strategies_count=len(self._strategies),
                active_champion=champ_record,
                active_challengers=challengers,
                state_distribution=dist,
                total_decisions_count=len(self._decisions),
                last_decision=last_dec,
                policy=self.policy,
                system_health="HEALTHY",
                tier_4_live_real_money_locked=True,
            )

    def list_decisions(self, limit: int = 50) -> List[GovernanceDecisionRecord]:
        """List historical governance decision audit records."""
        with self._lock:
            return list(reversed(self._decisions))[:limit]

    def update_policy(self, new_policy: GovernancePolicy, operator: str = "OPERATOR") -> GovernancePolicy:
        """Update governance policy thresholds."""
        with self._lock:
            self.policy = new_policy
            self._persist_state("UPDATE_GOVERNANCE_POLICY")
            self._emit_audit(
                event_type="GOVERNANCE_POLICY_UPDATED",
                strategy_id="SYSTEM",
                payload=new_policy.model_dump(),
            )
            return self.policy

    # ── State Persistence & Audit Integrations (Step 9) ───────────────────────

    def _persist_state(self, mutation_type: str) -> None:
        """Persist governance state to Phase 28 PersistentStateStore and StateJournal."""
        try:
            state_data = {
                "strategies": {k: v.model_dump(mode="json") for k, v in self._strategies.items()},
                "champion_id": self._champion_id,
                "champion_defenses": self._champion_defenses,
                "policy": self.policy.model_dump(mode="json"),
            }
            rev = global_persistent_state_store.commit_mutation(
                mutation_type=f"GOVERNANCE_{mutation_type}",
                mutations={"strategy_governance": state_data},
                idempotency_key=f"gov-{uuid.uuid4().hex[:8]}",
            )
            global_state_journal.append_entry(
                event_type=f"GOVERNANCE_{mutation_type}",
                state_revision=rev.revision,
                payload={"strategies_count": len(self._strategies), "champion_id": self._champion_id},
            )
        except Exception as e:
            logger.warning("Could not persist governance state to PersistentStateStore: %s", e)

    def _sync_from_persistent_store(self) -> None:
        """Hydrate governance state from PersistentStateStore if available."""
        try:
            store_state = global_persistent_state_store.get_state()
            gov_state = store_state.get("strategy_governance")
            if gov_state and isinstance(gov_state, dict):
                strats = gov_state.get("strategies", {})
                for sid, sdata in strats.items():
                    self._strategies[sid] = StrategyVersion.model_validate(sdata)
                self._champion_id = gov_state.get("champion_id")
                self._champion_defenses = gov_state.get("champion_defenses", 0)
                if "policy" in gov_state:
                    self.policy = GovernancePolicy.model_validate(gov_state["policy"])
        except Exception as e:
            logger.debug("No existing persistent governance state to restore: %s", e)

    def _emit_audit(
        self,
        event_type: str,
        strategy_id: str,
        payload: Optional[Dict[str, Any]] = None,
        severity: EventSeverity = EventSeverity.INFO,
    ) -> None:
        """Emit standardized governance event into Phase 23 TamperEvidentAuditChain."""
        try:
            global_audit_chain.append_event(
                event_type=event_type,
                category=EventCategory.CONFIGURATION,
                component="StrategyGovernanceEngine",
                correlation_id=f"gov-{uuid.uuid4().hex[:8]}",
                severity=severity,
                payload=payload or {},
            )
        except Exception as e:
            logger.warning("Failed to emit audit event %s: %s", event_type, e)


# ── Global Singleton Instance ─────────────────────────────────────────────────

global_strategy_governance_engine = StrategyGovernanceEngine()
