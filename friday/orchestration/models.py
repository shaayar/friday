"""
Orchestration domain models for M8.1.

These types define the task-orchestration vocabulary used by the M8
master-agent layer. They are intentionally independent from any database,
provider, or transport implementation.

Domain validation here is structural only. Runtime/execution concerns are
out of scope for the domain model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class TaskCapability(StrEnum):
    """Capabilities a worker may require to execute a task."""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"


class VerificationResult(StrEnum):
    """Result of independent verification."""

    PASS = "pass"
    FAIL = "fail"
    NEEDS_REVIEW = "needs_review"


class OrchestrationStatus(StrEnum):
    """Final status of an orchestration."""

    PASS = "pass"
    FAIL = "fail"
    NEEDS_REVIEW = "needs_review"
    NO_WORKER = "no_worker"
    UNKNOWN_CAPABILITY = "unknown_capability"
    WORKER_FAILURE = "worker_failure"
    VERIFIER_FAILURE = "verifier_failure"
    ESCALATED = "escalated"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_aware_timestamp(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _validate_timeout(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return float(value)


@dataclass(frozen=True, slots=True)
class TaskContract:
    """
    Immutable, bounded task contract for worker execution.

    Workers receive explicit, bounded contracts rather than free-form requests.
    This is the single source of truth for what a task requires and accepts.
    """

    task_id: str
    objective: str
    acceptance_criteria: tuple[str, ...]
    inputs: tuple[str, ...] = ()
    allowed_capabilities: tuple[TaskCapability, ...] = ()
    constraints: tuple[str, ...] = ()
    timeout: float = 300.0
    project_id: str | None = None
    created_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        # task_id
        task_id = str(self.task_id).strip()
        if not task_id:
            raise ValueError("task_id cannot be empty")
        object.__setattr__(self, "task_id", task_id)

        # objective
        objective = str(self.objective).strip()
        if not objective:
            raise ValueError("objective cannot be empty")
        object.__setattr__(self, "objective", objective)

        # acceptance_criteria
        ac = tuple(str(c).strip() for c in self.acceptance_criteria if c and str(c).strip())
        if not ac:
            raise ValueError("acceptance_criteria cannot be empty")
        object.__setattr__(self, "acceptance_criteria", ac)

        # inputs (optional)
        inputs = tuple(str(i).strip() for i in self.inputs if i and str(i).strip())
        object.__setattr__(self, "inputs", inputs)

        # allowed_capabilities
        caps = tuple(self.allowed_capabilities)
        for cap in caps:
            if not isinstance(cap, TaskCapability):
                raise TypeError(f"allowed_capabilities must be TaskCapability, got {type(cap)}")
        object.__setattr__(self, "allowed_capabilities", caps)

        # constraints (optional)
        constraints = tuple(str(c).strip() for c in self.constraints if c and str(c).strip())
        object.__setattr__(self, "constraints", constraints)

        # timeout
        timeout = _validate_timeout("timeout", self.timeout)
        object.__setattr__(self, "timeout", timeout)

        # project_id (optional)
        project_id = None if self.project_id is None else str(self.project_id).strip()
        if project_id == "":
            raise ValueError("project_id cannot be empty string")
        object.__setattr__(self, "project_id", project_id)

        # created_at
        created_at = _require_aware_timestamp("created_at", self.created_at)
        object.__setattr__(self, "created_at", created_at)


@dataclass(frozen=True, slots=True)
class AgentManifest:
    """
    Immutable manifest describing an agent's capabilities and execution contract.

    This is the registry's source of truth for what an agent can do.
    """

    agent_id: str
    name: str
    description: str
    capabilities: tuple[TaskCapability, ...]
    input_contract: str
    output_contract: str
    execution_protocol: str
    created_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        # agent_id
        agent_id = str(self.agent_id).strip()
        if not agent_id:
            raise ValueError("agent_id cannot be empty")
        object.__setattr__(self, "agent_id", agent_id)

        # name
        name = str(self.name).strip()
        if not name:
            raise ValueError("name cannot be empty")
        object.__setattr__(self, "name", name)

        # description
        description = str(self.description).strip()
        if not description:
            raise ValueError("description cannot be empty")
        object.__setattr__(self, "description", description)

        # capabilities
        caps = tuple(self.capabilities)
        if not caps:
            raise ValueError("capabilities cannot be empty")
        for cap in caps:
            if not isinstance(cap, TaskCapability):
                raise TypeError(f"capabilities must be TaskCapability, got {type(cap)}")
        object.__setattr__(self, "capabilities", caps)

        # input_contract
        input_contract = str(self.input_contract).strip()
        if not input_contract:
            raise ValueError("input_contract cannot be empty")
        object.__setattr__(self, "input_contract", input_contract)

        # output_contract
        output_contract = str(self.output_contract).strip()
        if not output_contract:
            raise ValueError("output_contract cannot be empty")
        object.__setattr__(self, "output_contract", output_contract)

        # execution_protocol
        execution_protocol = str(self.execution_protocol).strip()
        if not execution_protocol:
            raise ValueError("execution_protocol cannot be empty")
        object.__setattr__(self, "execution_protocol", execution_protocol)

        # created_at
        created_at = _require_aware_timestamp("created_at", self.created_at)
        object.__setattr__(self, "created_at", created_at)


@runtime_checkable
class WorkerAdapter(Protocol):
    """
    Protocol for worker adapters.

    M8.1 uses a single hard-coded adapter. This protocol defines the
    execution boundary without committing to a specific implementation.
    """

    def capabilities(self) -> tuple[TaskCapability, ...]:
        """Return the capabilities this adapter provides."""
        ...

    async def execute(self, task: TaskContract) -> WorkerResult:
        """Execute a task and return the result."""
        ...


@dataclass(frozen=True, slots=True)
class WorkerResult:
    """
    Result of a worker execution.

    Immutable domain object representing what a worker produced.
    """

    task_id: str
    agent_id: str
    status: str  # "completed", "failed", "timeout"
    output: str
    artifacts: tuple[str, ...] = ()
    error: str | None = None
    started_at: datetime = field(default_factory=_utc_now)
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        task_id = str(self.task_id).strip()
        if not task_id:
            raise ValueError("task_id cannot be empty")
        object.__setattr__(self, "task_id", task_id)

        agent_id = str(self.agent_id).strip()
        if not agent_id:
            raise ValueError("agent_id cannot be empty")
        object.__setattr__(self, "agent_id", agent_id)

        status = str(self.status).strip()
        if not status:
            raise ValueError("status cannot be empty")
        object.__setattr__(self, "status", status)

        if not isinstance(self.output, str):
            raise TypeError("output must be a string")
        object.__setattr__(self, "output", self.output)

        artifacts = tuple(str(a).strip() for a in self.artifacts if a and str(a).strip())
        object.__setattr__(self, "artifacts", artifacts)

        error = None if self.error is None else str(self.error).strip()
        if error == "":
            error = None
        object.__setattr__(self, "error", error)

        started_at = _require_aware_timestamp("started_at", self.started_at)
        object.__setattr__(self, "started_at", started_at)

        completed_at = (
            None
            if self.completed_at is None
            else _require_aware_timestamp("completed_at", self.completed_at)
        )
        if completed_at is not None and completed_at < started_at:
            raise ValueError("completed_at cannot be earlier than started_at")
        object.__setattr__(self, "completed_at", completed_at)


@dataclass(frozen=True, slots=True)
class VerificationResultDetail:
    """
    Detailed result of an independent verification.

    Contains the overall verification result plus detailed breakdown of
    which criteria passed/failed for auditability.
    """

    overall: VerificationResult
    passed_criteria: tuple[str, ...] = ()
    failed_criteria: tuple[str, ...] = ()
    insufficient_evidence: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        # Validate overall
        if not isinstance(self.overall, VerificationResult):
            raise TypeError("overall must be a VerificationResult")

        # Normalize tuples
        passed = tuple(str(c).strip() for c in self.passed_criteria if c and str(c).strip())
        failed = tuple(str(c).strip() for c in self.failed_criteria if c and str(c).strip())
        insufficient = tuple(
            str(c).strip() for c in self.insufficient_evidence if c and str(c).strip()
        )
        object.__setattr__(self, "passed_criteria", passed)
        object.__setattr__(self, "failed_criteria", failed)
        object.__setattr__(self, "insufficient_evidence", insufficient)

        # Notes
        notes = str(self.notes).strip()
        object.__setattr__(self, "notes", notes)


@runtime_checkable
class Verifier(Protocol):
    """
    Protocol for independent verifiers.

    The verifier evaluates a worker's result against the task contract
    acceptance criteria. It must NOT trust the worker's self-reported status.

    Implementations must be deterministic and reproducible.
    """

    def verify(
        self,
        task: TaskContract,
        result: WorkerResult,
        artifacts: dict[str, str] | None = None,
    ) -> VerificationResultDetail:
        """
        Verify a worker result against the task contract.

        Args:
            task: The task contract with acceptance criteria.
            result: The worker's execution result.
            artifacts: Optional dict of artifact file paths to their content.

        Returns:
            VerificationResultDetail with overall result and detailed breakdown.
        """
        ...


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """
    Result of a complete orchestration cycle.

    Contains all information about the task execution and verification.
    """

    task_id: str
    objective: str
    selected_agent_id: str | None
    worker_result: WorkerResult | None
    verification_detail: VerificationResultDetail | None
    status: OrchestrationStatus
    started_at: datetime
    completed_at: datetime | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        task_id = str(self.task_id).strip()
        if not task_id:
            raise ValueError("task_id cannot be empty")
        object.__setattr__(self, "task_id", task_id)

        objective = str(self.objective).strip()
        if not objective:
            raise ValueError("objective cannot be empty")
        object.__setattr__(self, "objective", objective)

        if self.selected_agent_id is not None:
            agent_id = str(self.selected_agent_id).strip()
            if agent_id == "":
                object.__setattr__(self, "selected_agent_id", None)
            else:
                object.__setattr__(self, "selected_agent_id", agent_id)

        if not isinstance(self.status, OrchestrationStatus):
            raise TypeError("status must be an OrchestrationStatus")

        notes = str(self.notes).strip()
        object.__setattr__(self, "notes", notes)

        started_at = self.started_at
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise ValueError("started_at must be timezone-aware")

        completed_at = self.completed_at
        if completed_at is not None:
            if completed_at.tzinfo is None or completed_at.utcoffset() is None:
                raise ValueError("completed_at must be timezone-aware")
            if completed_at < started_at:
                raise ValueError("completed_at cannot be earlier than started_at")


@dataclass(frozen=True, slots=True)
class OrchestrationConfig:
    """Configuration for the orchestrator."""

    default_timeout: float = 300.0


__all__ = [
    "AgentManifest",
    "OrchestrationConfig",
    "OrchestrationResult",
    "OrchestrationStatus",
    "TaskCapability",
    "TaskContract",
    "VerificationResult",
    "VerificationResultDetail",
    "Verifier",
    "WorkerAdapter",
    "WorkerResult",
]
