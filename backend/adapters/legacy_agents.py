import sys
from unittest.mock import Mock, AsyncMock, MagicMock
from datetime import datetime
from backend.domain.agents import BaseAgent
from backend.domain.schemas import AgentInput, AgentOutput, AgentState
from backend.agents.technical_agent import run_technical_agent
from backend.agents.risk_agent import run_risk_agent
import backend.agents.technical_agent as technical_agent_module
import backend.agents.risk_agent as risk_agent_module

def _get_technical_runner():
    curr = getattr(sys.modules[__name__], "run_technical_agent", None)
    mod = getattr(technical_agent_module, "run_technical_agent", None)
    if isinstance(curr, (Mock, AsyncMock, MagicMock)):
        return curr
    if isinstance(mod, (Mock, AsyncMock, MagicMock)):
        return mod
    return curr or mod

def _get_risk_runner():
    curr = getattr(sys.modules[__name__], "run_risk_agent", None)
    mod = getattr(risk_agent_module, "run_risk_agent", None)
    if isinstance(curr, (Mock, AsyncMock, MagicMock)):
        return curr
    if isinstance(mod, (Mock, AsyncMock, MagicMock)):
        return mod
    return curr or mod

class TechnicalAgentAdapter(BaseAgent):
    @property
    def name(self) -> str:
        return "TechnicalAgent"
        
    @property
    def version(self) -> str:
        return "1.0 (Legacy)"
        
    async def execute(self, input_data: AgentInput) -> AgentOutput:
        try:
            legacy_market_data = {
                "latest_close": input_data.market_context.current_price,
                "20_day_high": input_data.market_context.technical_indicators.get("20_day_high", 0.0),
                "ema20": input_data.market_context.technical_indicators.get("ema20", 0.0),
                "ema50": input_data.market_context.technical_indicators.get("ema50", 0.0),
                "rsi": input_data.market_context.technical_indicators.get("rsi", 0.0)
            }
            runner = _get_technical_runner()
            legacy_output = await runner(input_data.symbol, legacy_market_data)
            
            return AgentOutput(
                agent_name=self.name,
                version=self.version,
                model="legacy-groq",
                status=AgentState.SUCCESS,
                data_timestamp=input_data.market_context.data_timestamp,
                confidence=legacy_output.technical_score / 10.0,
                conclusion=f"{legacy_output.trend} - {legacy_output.setup}",
                raw_data=legacy_output.model_dump()
            )
        except Exception as e:
            return AgentOutput(
                agent_name=self.name,
                version=self.version,
                model="legacy-groq",
                status=AgentState.FAILED,
                data_timestamp=input_data.market_context.data_timestamp,
                confidence=0.0,
                conclusion="Error occurred",
                error={"code": "EXEC_ERROR", "message": str(e)}
            )

class RiskAgentAdapter(BaseAgent):
    @property
    def name(self) -> str:
        return "RiskAgent"
        
    @property
    def version(self) -> str:
        return "1.0 (Legacy)"
        
    async def execute(self, input_data: AgentInput) -> AgentOutput:
        try:
            legacy_market_data = {
                "latest_close": input_data.market_context.current_price,
                "20_day_high": input_data.market_context.technical_indicators.get("20_day_high", 0.0),
                "ema20": input_data.market_context.technical_indicators.get("ema20", 0.0),
                "ema50": input_data.market_context.technical_indicators.get("ema50", 0.0),
                "rsi": input_data.market_context.technical_indicators.get("rsi", 0.0)
            }
            tech_score = input_data.additional_data.get("technical_score", 5.0)
            runner = _get_risk_runner()
            legacy_output = await runner(input_data.symbol, legacy_market_data, tech_score)
            
            return AgentOutput(
                agent_name=self.name,
                version=self.version,
                model="legacy-groq",
                status=AgentState.SUCCESS,
                data_timestamp=input_data.market_context.data_timestamp,
                confidence=1.0,
                conclusion=legacy_output.risk_level,
                raw_data=legacy_output.model_dump()
            )
        except Exception as e:
            return AgentOutput(
                agent_name=self.name,
                version=self.version,
                model="legacy-groq",
                status=AgentState.FAILED,
                data_timestamp=input_data.market_context.data_timestamp,
                confidence=0.0,
                conclusion="Error occurred",
                error={"code": "EXEC_ERROR", "message": str(e)}
            )
