"""
Orchestration domain models.

These types define the task-orchestration vocabulary used by the M8
master-agent layer. They are intentionally independent from any database,
provider, or transport implementation.

Domain validation here is structural only. Runtime/execution concerns are
out of scope for the domain model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid4().hex


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


class TaskCapability(str, Enum):
    """Capabilities a worker may require to execute a task."""
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"


class VerificationResult(str, Enum):
    """Result of independent verification."""
    PASS = "pass"
    FAIL = "fail"
    NEEDS_REVIEW = "needs_review"


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


__all__ = [
    "TaskCapability",
    "TaskContract",
    "VerificationResult",
]