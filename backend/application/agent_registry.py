"""
AgentRegistry — Phase 3.1

Maintains a registry of named BaseAgent instances.
Does not contain business logic.
Prevents duplicate registrations.
Validates conformance to BaseAgent contract.
"""

from typing import Dict, List, Type
from backend.domain.agents import BaseAgent


class AgentRegistrationError(Exception):
    """Raised when agent registration fails."""


class AgentNotFoundError(Exception):
    """Raised when a requested agent is not in the registry."""


class AgentRegistry:
    """
    Registry for specialist agents.

    Agents are keyed by their `.name` property.
    Only objects that are instances of BaseAgent are accepted.

    Usage
    -----
    registry = AgentRegistry()
    registry.register(MyAgent())
    agent = registry.get("MyAgent")
    """

    def __init__(self) -> None:
        self._agents: Dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        """
        Register an agent.

        Raises AgentRegistrationError if:
        - agent does not subclass BaseAgent
        - an agent with the same name is already registered
        """
        if not isinstance(agent, BaseAgent):
            raise AgentRegistrationError(
                f"Cannot register object of type '{type(agent).__name__}': "
                "must be an instance of BaseAgent."
            )
        key = agent.name
        if key in self._agents:
            raise AgentRegistrationError(
                f"Agent '{key}' is already registered. "
                "Unregister it first or use a unique name."
            )
        self._agents[key] = agent

    def get(self, name: str) -> BaseAgent:
        """Return agent by name. Raises AgentNotFoundError if absent."""
        if name not in self._agents:
            raise AgentNotFoundError(
                f"No agent registered with name '{name}'. "
                f"Available: {list(self._agents.keys())}"
            )
        return self._agents[name]

    def unregister(self, name: str) -> None:
        """Remove an agent by name. No-ops silently if absent."""
        self._agents.pop(name, None)

    def list_agents(self) -> List[str]:
        """Return sorted list of registered agent names."""
        return sorted(self._agents.keys())

    def all_agents(self) -> List[BaseAgent]:
        """Return all registered agents in name-sorted order."""
        return [self._agents[k] for k in sorted(self._agents.keys())]

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, name: str) -> bool:
        return name in self._agents
