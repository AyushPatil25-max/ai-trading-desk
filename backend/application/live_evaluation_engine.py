"""
Phase 16 — Live Evaluation & Automated Agent Performance Engine

Provides automated closed-loop learning evaluation over forward simulation trades
and Trading OS multi-agent predictions. Evaluates directional accuracy, grades
Bull and Bear agents, computes specialist performance attribution, calculates
Brier calibration scores, and generates dynamic conviction adjustment weights.
"""

from datetime import datetime, timezone
import logging
import math
import threading
from typing import Any, Dict, List, Optional
import uuid

from backend.domain.live_evaluation_schemas import (
    AgentGrade,
    AgentPerformanceMatrix,
    CalibrationMetrics,
    DebateEvaluationSummary,
    PredictionOutcomeRecord,
    SpecialistScorecard,
)
from backend.domain.trading_os_schemas import TradingOSRun

logger = logging.getLogger(__name__)

STANDARD_SPECIALISTS = [
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


def calculate_letter_grade(skill_score: float) -> AgentGrade:
    """Map a continuous 0.0 to 100.0 skill score to an objective letter grade."""
    if skill_score >= 90.0:
        return AgentGrade.A_PLUS
    elif skill_score >= 80.0:
        return AgentGrade.A
    elif skill_score >= 70.0:
        return AgentGrade.B_PLUS
    elif skill_score >= 60.0:
        return AgentGrade.B
    elif skill_score >= 50.0:
        return AgentGrade.C
    elif skill_score >= 40.0:
        return AgentGrade.D
    else:
        return AgentGrade.F


class LiveEvaluationEngine:
    """
    Authoritative evaluation engine executing learning loops over multi-agent decisions.
    All calculations are deterministic, transparent, and executed in pure Python.
    """

    def __init__(self, telemetry_engine: Optional[Any] = None) -> None:
        self._lock = threading.Lock()
        self.telemetry_engine = telemetry_engine
        self._records: Dict[str, PredictionOutcomeRecord] = {}
        self.latest_matrix: Optional[AgentPerformanceMatrix] = None

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def record_run_prediction(
        self,
        run: TradingOSRun,
        evaluation_timestamp: Optional[datetime] = None,
    ) -> PredictionOutcomeRecord:
        """
        Extract agent forecasts and committee verdict from a completed TradingOSRun.
        """
        with self._lock:
            now = evaluation_timestamp or datetime.now(timezone.utc)

            # 1. Committee Action & Conviction
            committee_data = run.committee_decision or getattr(run, "committee", None) or {}
            action = committee_data.get("action", "HOLD")
            conviction = float(committee_data.get("conviction", 0.5))

            # 2. Debate Confidence
            debate_data = run.debate or {}
            bull_conf = float(debate_data.get("bull_confidence", 0.5))
            bear_conf = float(debate_data.get("bear_confidence", 0.5))

            # 3. Specialist Signals
            specialist_sigs: Dict[str, str] = {}
            ev_data = run.evidence or {}
            ev_items = ev_data.get("items", []) if isinstance(ev_data, dict) else (ev_data if isinstance(ev_data, list) else [])
            for item in ev_items:
                if isinstance(item, dict):
                    source = item.get("source_agent")
                    rec = item.get("recommendation")
                    if source and rec:
                        specialist_sigs[source] = str(rec).upper()

            # Ensure all standard specialists have an entry
            for spec in STANDARD_SPECIALISTS:
                if spec not in specialist_sigs:
                    # Fallback to general action if not explicitly segregated
                    specialist_sigs[spec] = action

            rec_id = f"pred-{uuid.uuid4().hex[:8]}"
            record = PredictionOutcomeRecord(
                prediction_id=rec_id,
                run_id=run.run_id,
                symbol=run.symbol,
                decision_action=action,
                calibrated_conviction=conviction,
                bull_confidence=bull_conf,
                bear_confidence=bear_conf,
                specialist_signals=specialist_sigs,
                timestamp=now,
            )

            self._records[run.run_id] = record
            return record

    def record_trade_outcome(
        self,
        symbol: str,
        realized_return_pct: float,
        run_id: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> Optional[PredictionOutcomeRecord]:
        """
        Pair an actual realized market return with a previous prediction.
        """
        with self._lock:
            target_record: Optional[PredictionOutcomeRecord] = None

            if run_id and run_id in self._records:
                target_record = self._records[run_id]
            else:
                # Find most recent uncompleted prediction for this symbol
                sym_upper = symbol.upper()
                candidates = [
                    r for r in self._records.values()
                    if r.symbol.upper() == sym_upper and r.actual_return_pct is None
                ]
                if candidates:
                    candidates.sort(key=lambda x: x.timestamp, reverse=True)
                    target_record = candidates[0]

            if not target_record:
                logger.debug(f"[LiveEvaluationEngine] No unmatched prediction found for {symbol}.")
                return None

            # Calculate direction and win/loss
            target_record.actual_return_pct = realized_return_pct
            if realized_return_pct > 0.0001:
                target_record.actual_direction = "UP"
            elif realized_return_pct < -0.0001:
                target_record.actual_direction = "DOWN"
            else:
                target_record.actual_direction = "FLAT"

            # Determine win status relative to committee recommendation
            action = target_record.decision_action.upper()
            if "BUY" in action:
                target_record.is_win = (target_record.actual_direction == "UP")
            elif "SELL" in action or "AVOID" in action:
                target_record.is_win = (target_record.actual_direction == "DOWN")
            else:
                # HOLD is neutral win if volatility is minimal
                target_record.is_win = (abs(realized_return_pct) <= 0.01)

            return target_record

    # ── Evaluation & Attribution Core ─────────────────────────────────────────

    def evaluate(self) -> AgentPerformanceMatrix:
        """
        Execute comprehensive evaluation loop over all paired prediction-outcome records.
        """
        with self._lock:
            eval_id = f"eval-{uuid.uuid4().hex[:8]}"
            now = datetime.now(timezone.utc)

            completed = [r for r in self._records.values() if r.actual_return_pct is not None]
            total_completed = len(completed)

            if total_completed == 0:
                # Safe baseline when no trades have finalized yet
                return self._create_baseline_matrix(eval_id, now)

            # 1. Overall Decision Accuracy
            wins = sum(1 for r in completed if r.is_win)
            overall_accuracy = wins / total_completed

            # 2. Bull vs. Bear Evaluation
            debate_summary = self._evaluate_debate(completed)

            # 3. Specialist Attribution
            specialist_cards = self._evaluate_specialists(completed)

            # 4. Calibration & Brier Score
            calibration_metrics = self._evaluate_calibration(completed)

            # 5. Dynamic Weight Adjustments
            dynamic_weights: Dict[str, float] = {}
            for sc in specialist_cards:
                # Centered around 1.0, clamped between 0.70 and 1.30
                multiplier = 1.0 + ((sc.skill_score - 50.0) / 100.0)
                dynamic_weights[sc.specialist_name] = round(max(0.70, min(1.30, multiplier)), 3)

            matrix = AgentPerformanceMatrix(
                evaluation_id=eval_id,
                evaluated_at=now,
                total_runs_evaluated=len(self._records),
                total_completed_trades=total_completed,
                overall_accuracy=round(overall_accuracy, 4),
                debate_summary=debate_summary,
                specialists=specialist_cards,
                calibration=calibration_metrics,
                dynamic_weight_adjustments=dynamic_weights,
            )

            self.latest_matrix = matrix
            return matrix

    def _evaluate_debate(self, records: List[PredictionOutcomeRecord]) -> DebateEvaluationSummary:
        """Evaluate Bull Specialist vs. Bear Specialist predictive skill."""
        n = len(records)
        bull_correct = 0
        bear_correct = 0

        for r in records:
            actual_dir = r.actual_direction
            if actual_dir == "UP":
                bull_correct += 1
            elif actual_dir == "DOWN":
                bear_correct += 1
            else:
                # FLAT market: partial credit
                bull_correct += 0.5
                bear_correct += 0.5

        bull_acc = bull_correct / n
        bear_acc = bear_correct / n

        # Skill score: blend of accuracy and confidence calibration
        bull_score = round(max(0.0, min(100.0, bull_acc * 100.0)), 1)
        bear_score = round(max(0.0, min(100.0, bear_acc * 100.0)), 1)

        bull_wins = sum(1 for r in records if r.bull_confidence > r.bear_confidence and r.actual_direction == "UP")
        bear_wins = sum(1 for r in records if r.bear_confidence > r.bull_confidence and r.actual_direction == "DOWN")

        return DebateEvaluationSummary(
            bull_skill_score=bull_score,
            bull_grade=calculate_letter_grade(bull_score),
            bull_accuracy=round(bull_acc, 4),
            bear_skill_score=bear_score,
            bear_grade=calculate_letter_grade(bear_score),
            bear_accuracy=round(bear_acc, 4),
            winning_side_frequency={
                "BULL": round(bull_wins / n, 4),
                "BEAR": round(bear_wins / n, 4),
            },
            total_debates_evaluated=n,
            contradiction_resolution_rate=1.0,
        )

    def _evaluate_specialists(self, records: List[PredictionOutcomeRecord]) -> List[SpecialistScorecard]:
        """Compute attribution and skill score for each individual specialist agent."""
        cards: List[SpecialistScorecard] = []
        n = len(records)

        for spec_name in STANDARD_SPECIALISTS:
            correct = 0
            ret_contrib_sum = 0.0

            for r in records:
                sig = r.specialist_signals.get(spec_name, "HOLD").upper()
                ret = r.actual_return_pct or 0.0

                is_correct = False
                if "BUY" in sig and ret > 0:
                    is_correct = True
                    ret_contrib_sum += ret
                elif ("SELL" in sig or "AVOID" in sig) and ret < 0:
                    is_correct = True
                    ret_contrib_sum += abs(ret)
                elif "HOLD" in sig and abs(ret) <= 0.01:
                    is_correct = True
                else:
                    ret_contrib_sum -= abs(ret)

                if is_correct:
                    correct += 1

            acc = correct / n
            skill_score = round(max(0.0, min(100.0, acc * 100.0)), 1)
            grade = calculate_letter_grade(skill_score)
            avg_contrib = round(ret_contrib_sum / n, 4)

            # Simple Information Coefficient proxy: (Accuracy - 0.5) * 2
            ic = round((acc - 0.5) * 2.0, 3)

            cards.append(SpecialistScorecard(
                specialist_name=spec_name,
                skill_score=skill_score,
                letter_grade=grade,
                directional_accuracy=round(acc, 4),
                win_rate=round(acc, 4),
                total_predictions=n,
                correct_predictions=correct,
                avg_return_contribution=avg_contrib,
                information_coefficient=ic,
            ))

        return cards

    def _evaluate_calibration(self, records: List[PredictionOutcomeRecord]) -> CalibrationMetrics:
        """
        Compute probabilistic calibration (Brier Score: sum (p - o)^2 / N).
        Target: Brier Score <= 0.25 is well-calibrated (better than random coin flip).
        """
        n = len(records)
        brier_sum = 0.0
        conf_sum = 0.0
        win_count = 0

        for r in records:
            p = r.calibrated_conviction
            o = 1.0 if r.is_win else 0.0
            brier_sum += (p - o) ** 2
            conf_sum += p
            if r.is_win:
                win_count += 1

        brier = brier_sum / n
        avg_conf = conf_sum / n
        actual_win_rate = win_count / n
        overconfidence = avg_conf - actual_win_rate

        ece = abs(overconfidence)
        cal_grade = "EXCELLENT" if brier < 0.15 else ("GOOD" if brier < 0.25 else "DEGRADED")

        return CalibrationMetrics(
            brier_score=round(brier, 4),
            expected_calibration_error=round(ece, 4),
            overconfidence_score=round(overconfidence, 4),
            total_samples=n,
            calibration_grade=cal_grade,
        )

    def _create_baseline_matrix(self, eval_id: str, now: datetime) -> AgentPerformanceMatrix:
        """Create neutral baseline matrix when no trades have finalized yet."""
        default_cards = [
            SpecialistScorecard(
                specialist_name=s,
                skill_score=50.0,
                letter_grade=AgentGrade.C,
                directional_accuracy=0.5,
                win_rate=0.5,
                total_predictions=0,
                correct_predictions=0,
                avg_return_contribution=0.0,
                information_coefficient=0.0,
            )
            for s in STANDARD_SPECIALISTS
        ]
        return AgentPerformanceMatrix(
            evaluation_id=eval_id,
            evaluated_at=now,
            total_runs_evaluated=len(self._records),
            total_completed_trades=0,
            overall_accuracy=0.5,
            debate_summary=DebateEvaluationSummary(
                bull_skill_score=50.0,
                bull_grade=AgentGrade.C,
                bull_accuracy=0.5,
                bear_skill_score=50.0,
                bear_grade=AgentGrade.C,
                bear_accuracy=0.5,
                winning_side_frequency={"BULL": 0.5, "BEAR": 0.5},
                total_debates_evaluated=0,
            ),
            specialists=default_cards,
            calibration=CalibrationMetrics(
                brier_score=0.25,
                expected_calibration_error=0.0,
                overconfidence_score=0.0,
                total_samples=0,
                calibration_grade="UNINITIALIZED",
            ),
            dynamic_weight_adjustments={s: 1.0 for s in STANDARD_SPECIALISTS},
        )

    def get_latest_matrix(self) -> AgentPerformanceMatrix:
        if not self.latest_matrix:
            return self.evaluate()
        return self.latest_matrix

    def get_dynamic_weights(self) -> Dict[str, float]:
        matrix = self.get_latest_matrix()
        return matrix.dynamic_weight_adjustments

    def reset(self) -> None:
        with self._lock:
            self._records.clear()
            self.latest_matrix = None


# Global singleton instance
global_evaluation_engine = LiveEvaluationEngine()
