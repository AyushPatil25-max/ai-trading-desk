import json
import uuid
from typing import Dict, Any, Optional
from datetime import datetime
import os

from backend.domain.agents import BaseAgent
from backend.domain.schemas import AgentInput, AgentOutput, AgentState, AgentError, UnifiedEvidencePackage
from backend.domain.debate_schemas import DebateResult, BullCase, BearCase, RiskAssessment, DebateDecisionState
from backend.domain.investment_committee_schemas import (
    InvestmentDecision, InvestmentDecisionState, InvestmentThesis, ExecutionPlan, PositionSizing, DecisionAudit,
    DecisionGate, InvestmentAction, InvestmentHorizon
)
from backend.infrastructure.llm import LLMClient, LLMParseError, LLMClientError

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "investment_committee_config.json")

class InvestmentCommitteeAgent(BaseAgent):
    """
    InvestmentCommitteeAgent produces the final decision based on deterministic gates
    and uses the LLM solely for qualitative synthesis.
    """
    def __init__(self, llm: LLMClient):
        self._llm = llm
        self._load_config()

    def _load_config(self):
        with open(CONFIG_PATH, "r") as f:
            self.config = json.load(f)

    @property
    def name(self) -> str:
        return "InvestmentCommittee"

    @property
    def version(self) -> str:
        return "1.0.0"

    def _failure_output(self, ctx_id: str, symbol: str, code: str, message: str, ts: datetime) -> AgentOutput:
        return AgentOutput(
            agent_name=self.name,
            version=self.version,
            model=self._llm.model_name,
            status=AgentState.FAILED,
            data_timestamp=ts,
            confidence=0.0,
            conclusion="Failed",
            error=AgentError(code=code, message=message)
        )

    async def execute(self, input_data: AgentInput) -> AgentOutput:
        ctx_id = input_data.market_context.context_id
        symbol = input_data.symbol
        ts = input_data.market_context.data_timestamp

        # 1. & 2. & 3. Validate Inputs
        unified_evidence_dict = input_data.additional_data.get("unified_evidence")
        debate_result_dict = input_data.additional_data.get("debate_result")

        if not unified_evidence_dict or not debate_result_dict:
            return self._failure_output(ctx_id, symbol, "INVALID_INPUT", "Missing evidence or debate result.", ts)

        evidence = UnifiedEvidencePackage.model_validate(unified_evidence_dict)
        debate = DebateResult.model_validate(debate_result_dict)

        # 4. Run Deterministic Decision Gates
        audit, deterministic_state = self._run_deterministic_gates(evidence, debate)

        # 5. & 6. Calculate Position Sizing
        position_sizing = self._calculate_position_sizing(deterministic_state, debate, audit)

        # 7. Build Execution Plan
        execution_plan = self._build_execution_plan(deterministic_state, debate, position_sizing)

        # 8. LLM Synthesis
        # Provide strict boundaries: LLM CANNOT change the decision state.
        system_prompt = (
            "You are the Investment Committee summarizer. Your job is to synthesize the qualitative thesis "
            "based strictly on the deterministic state and execution plan provided. "
            "DO NOT change the state. DO NOT calculate numbers. DO NOT invent prices or position sizes. "
            f"The deterministic state is strictly: {deterministic_state.value}"
        )

        user_prompt = (
            f"Symbol: {symbol}\nContext ID: {ctx_id}\n\n"
            f"Debate Summary:\n{debate.model_dump_json(include={'bull_strength', 'bear_strength', 'risk_score', 'thesis_status', 'key_agreements', 'critical_conflicts', 'confidence'})}\n\n"
            f"Deterministic State: {deterministic_state.value}\n"
            f"Position Sizing: {position_sizing.model_dump_json()}\n\n"
            "Produce an InvestmentThesis explaining this decision. Return valid JSON matching the schema:\n"
            f"{json.dumps(InvestmentThesis.model_json_schema(), indent=2)}"
        )

        try:
            thesis: InvestmentThesis = await self._llm.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=InvestmentThesis
            )

            # 9. Validate LLM Output & Assemble Final Decision
            # We strictly enforce the deterministic state and execution plan regardless of LLM whims.
            
            final_decision = InvestmentDecision(
                decision_id=f"ic-{uuid.uuid4().hex[:8]}",
                context_id=ctx_id,
                symbol=symbol,
                run_id=evidence.run_id,
                generated_at=datetime.utcnow(),
                state=deterministic_state,
                thesis=thesis,
                execution_plan=execution_plan,
                audit_trail=audit,
                confidence=debate.confidence,
                evidence_references=debate.evidence_references
            )

            return AgentOutput(
                agent_name=self.name,
                version=self.version,
                model=self._llm.model_name,
                status=AgentState.SUCCESS,
                data_timestamp=ts,
                confidence=final_decision.confidence,
                conclusion=f"Decision: {final_decision.state.value}. {thesis.synthesis}",
                evidence=[{"source": ref.source, "content": ref.claim} for ref in final_decision.evidence_references],
                risks=thesis.primary_risks,
                invalidation_conditions=thesis.invalidation_conditions,
                raw_data=final_decision.model_dump()
            )

        except LLMParseError as e:
            return self._failure_output(ctx_id, symbol, "LLM_PARSE_ERROR", str(e), ts)
        except LLMClientError as e:
            return self._failure_output(ctx_id, symbol, "LLM_CLIENT_ERROR", str(e), ts)

    def _run_deterministic_gates(self, evidence: UnifiedEvidencePackage, debate: DebateResult) -> tuple[DecisionAudit, InvestmentDecisionState]:
        audit = DecisionAudit(deterministic_state=InvestmentDecisionState.HOLD)
        gates = []

        cfg = self.config["gates"]

        # Gate A: Evidence Sufficiency
        # Example metric: total extracted evidence vs a baseline
        # Here we just use a proxy: if evidence_items is empty or very low.
        evidence_score = len(evidence.evidence_items) / 10.0 # simple normalized proxy
        passed_ev = evidence_score >= cfg["evidence_sufficiency"]["value"]
        gates.append(DecisionGate(
            gate_name=cfg["evidence_sufficiency"]["name"],
            passed=passed_ev,
            threshold_used=cfg["evidence_sufficiency"]["value"],
            input_value=evidence_score,
            reason="Insufficient evidence density" if not passed_ev else "Evidence density OK"
        ))

        # Gate B: Data Quality (using missing data records as proxy if trust score not available)
        dq_score = 1.0 - (len(evidence.missing_data_records) * 0.1)
        passed_dq = dq_score >= cfg["data_quality"]["value"]
        gates.append(DecisionGate(
            gate_name=cfg["data_quality"]["name"],
            passed=passed_dq,
            threshold_used=cfg["data_quality"]["value"],
            input_value=dq_score,
            reason="High missing data" if not passed_dq else "Data quality OK"
        ))

        # Check critical failures
        if not passed_ev:
            audit.gates_evaluated = gates
            audit.missing_data_triggered = True
            audit.deterministic_state = InvestmentDecisionState.INSUFFICIENT_EVIDENCE
            return audit, audit.deterministic_state

        if not passed_dq:
            audit.gates_evaluated = gates
            audit.deterministic_state = InvestmentDecisionState.DATA_QUALITY_VETO
            return audit, audit.deterministic_state

        # Gate C: Risk Veto
        risk_veto_passed = not (debate.risk_assessment and debate.risk_assessment.risk_veto)
        gates.append(DecisionGate(
            gate_name="Hard Risk Veto Gate",
            passed=risk_veto_passed,
            threshold_used=0.0,
            input_value=1.0 if not risk_veto_passed else 0.0,
            reason="Risk Veto Triggered" if not risk_veto_passed else "No Risk Veto"
        ))

        if not risk_veto_passed:
            audit.gates_evaluated = gates
            audit.risk_veto_triggered = True
            audit.deterministic_state = InvestmentDecisionState.RISK_VETO
            return audit, audit.deterministic_state

        # Gate D: Bull/Bear Spread
        spread = debate.bull_strength - debate.bear_strength
        passed_spread = spread >= cfg["bull_bear_spread"]["value"]
        gates.append(DecisionGate(
            gate_name=cfg["bull_bear_spread"]["name"],
            passed=passed_spread,
            threshold_used=cfg["bull_bear_spread"]["value"],
            input_value=spread,
            reason=f"Spread {spread:.2f} insufficient" if not passed_spread else "Spread OK"
        ))

        # Gate E: Conflicts
        conflicts = len(evidence.conflict_summary)
        audit.critical_conflicts_found = conflicts
        passed_conflicts = conflicts == 0
        gates.append(DecisionGate(
            gate_name="Critical Conflict Gate",
            passed=passed_conflicts,
            threshold_used=0.0,
            input_value=conflicts,
            reason=f"{conflicts} material conflicts found" if not passed_conflicts else "No conflicts"
        ))
        
        # Calculate State
        if passed_spread and passed_conflicts and debate.thesis_status == DebateDecisionState.BULL_FAVORED:
            state = InvestmentDecisionState.APPROVE
        elif spread <= -0.2:
            state = InvestmentDecisionState.REJECT
        else:
            state = InvestmentDecisionState.HOLD

        audit.gates_evaluated = gates
        audit.deterministic_state = state
        return audit, state

    def _calculate_position_sizing(self, state: InvestmentDecisionState, debate: DebateResult, audit: DecisionAudit) -> PositionSizing:
        if state not in [InvestmentDecisionState.APPROVE, InvestmentDecisionState.HOLD]:
            return PositionSizing(is_available=False, reason="Position sizing unavailable for non-approved states.")
        
        if audit.missing_data_triggered or audit.risk_veto_triggered:
            return PositionSizing(is_available=False, reason="Position sizing unavailable due to vetos.")
            
        cfg = self.config["position_sizing"]
        
        # Deterministic formula
        base = cfg["base_size_pct"]
        risk_penalty = debate.risk_score * cfg["risk_penalty_multiplier"] * base
        
        size = base - risk_penalty
        # Confidence boost
        size = size * debate.confidence
        
        size = max(0.0, min(size, cfg["max_size_pct"]))
        
        if size == 0.0:
            return PositionSizing(is_available=False, reason="Calculated size is 0.")
            
        return PositionSizing(
            is_available=True,
            recommended_size_pct=round(size, 2),
            max_size_pct=cfg["max_size_pct"],
            volatility_adjusted=False,
            reason="Calculated via deterministic model"
        )
        
    def _build_execution_plan(self, state: InvestmentDecisionState, debate: DebateResult, sizing: PositionSizing) -> ExecutionPlan:
        if state == InvestmentDecisionState.APPROVE:
            action = InvestmentAction.BUY
        elif state == InvestmentDecisionState.REJECT:
            action = InvestmentAction.AVOID
        elif state == InvestmentDecisionState.INSUFFICIENT_EVIDENCE:
            action = InvestmentAction.WATCH
        else:
            action = InvestmentAction.HOLD
            
        return ExecutionPlan(
            action=action,
            horizon=InvestmentHorizon.SWING, # Defaulting for now
            entry_conditions=["Deterministic approval"] if action == InvestmentAction.BUY else [],
            position_sizing=sizing
        )
