"""
In-memory Agent Registry for M8.1.

The registry manages agent manifests and provides capability-based lookup.
It is in-memory only, has no persistence, and performs deterministic selection.
"""

from __future__ import annotations

from friday.orchestration.models import AgentManifest, TaskCapability, WorkerAdapter


class AgentRegistry:
    """
    In-memory agent registry.

    Manages agent manifests and provides capability-based deterministic selection.
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentManifest] = {}
        self._adapters: dict[str, WorkerAdapter] = {}

    def register(
        self,
        manifest: AgentManifest,
        adapter: WorkerAdapter,
    ) -> None:
        """
        Register an agent with its manifest and adapter.

        Raises:
            ValueError: If agent_id already exists.
            TypeError: If manifest or adapter is invalid.
        """
        if not isinstance(manifest, AgentManifest):
            raise TypeError("manifest must be an AgentManifest")
        if manifest.agent_id in self._agents:
            raise ValueError(f"Agent with id '{manifest.agent_id}' already registered")

        if not isinstance(adapter, WorkerAdapter):
            raise TypeError("adapter must implement WorkerAdapter protocol")

        # Verify adapter capabilities match manifest
        adapter_caps = set(adapter.capabilities())
        manifest_caps = set(manifest.capabilities)
        if adapter_caps != manifest_caps:
            raise ValueError(
                "Adapter capabilities "
                f"{adapter_caps} do not match manifest capabilities "
                f"{manifest_caps}"
            )

        self._agents[manifest.agent_id] = manifest
        self._adapters[manifest.agent_id] = adapter

    def get(self, agent_id: str) -> AgentManifest | None:
        """Retrieve an agent manifest by ID."""
        return self._agents.get(agent_id)

    def get_adapter(self, agent_id: str) -> WorkerAdapter | None:
        """Retrieve a worker adapter by agent ID."""
        return self._adapters.get(agent_id)

    def list_agents(self) -> tuple[AgentManifest, ...]:
        """List all registered agents in deterministic order."""
        return tuple(self._agents[aid] for aid in sorted(self._agents.keys()))

    def select_by_capabilities(
        self,
        required_capabilities: tuple[TaskCapability, ...],
    ) -> AgentManifest | None:
        """
        Select the best agent for the required capabilities.

        Selection is deterministic:
        1. Agent must have ALL required capabilities.
        2. Among eligible agents, choose the one with the fewest total capabilities
           (most specific).
        3. Tie-break by agent_id (lexicographically).

        Returns None if no agent satisfies the requirements.
        """
        required = set(required_capabilities)
        if not required:
            return None

        eligible = [
            manifest
            for manifest in self._agents.values()
            if required.issubset(set(manifest.capabilities))
        ]

        if not eligible:
            return None

        # Deterministic: fewest capabilities, then lexicographic agent_id
        eligible.sort(key=lambda m: (len(m.capabilities), m.agent_id))
        return eligible[0]

    def is_registered(self, agent_id: str) -> bool:
        """Check if an agent is registered."""
        return agent_id in self._agents

    def unregister(self, agent_id: str) -> bool:
        """
        Unregister an agent.

        Returns True if agent was removed, False if not found.
        """
        if agent_id in self._agents:
            del self._agents[agent_id]
            del self._adapters[agent_id]
            return True
        return False

    def clear(self) -> None:
        """Remove all registered agents (for testing)."""
        self._agents.clear()
        self._adapters.clear()

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._agents


__all__ = ["AgentRegistry"]
