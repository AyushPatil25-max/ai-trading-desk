from abc import ABC, abstractmethod
from backend.domain.schemas import AgentInput, AgentOutput

class BaseAgent(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass
        
    @property
    @abstractmethod
    def version(self) -> str:
        pass

    @abstractmethod
    async def execute(self, input_data: AgentInput) -> AgentOutput:
        pass
