"""
FRIDAY Orchestrator - M8.1 Minimal Orchestration Loop.

Connects TaskContract -> AgentRegistry -> WorkerAdapter -> WorkerResult
-> Verifier -> VerificationResult -> OrchestrationResult.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from friday.orchestration.models import (
    OrchestrationConfig,
    OrchestrationResult,
    OrchestrationStatus,
)
from friday.orchestration.registry import AgentRegistry
from friday.orchestration.verifiers.deterministic import DeterministicVerifier

if TYPE_CHECKING:
    from friday.orchestration.models import (
        TaskContract,
        VerificationResult,
    )

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Minimal FRIDAY Orchestrator for M8.1.

    Connects the orchestration pipeline:
    TaskContract -> AgentRegistry -> WorkerAdapter -> WorkerResult
    -> Verifier -> VerificationResultDetail -> OrchestrationResult

    Does NOT:
    - Implement LLM-based planning
    - Persist state (runtime-only)
    - Bypass AgentRegistry or Verifier
    """

    MAX_RETRIES = 1

    def __init__(
        self,
        registry: AgentRegistry,
        verifier: DeterministicVerifier,
        config: OrchestrationConfig | None = None,
    ) -> None:
        self._registry = registry
        self._verifier = verifier
        self._config = config or OrchestrationConfig()

    async def orchestrate(
        self,
        task: TaskContract,
    ) -> OrchestrationResult:
        """
        Execute a complete orchestration cycle for a single task with retry/escalation.

        Flow:
        1. UNDERSTAND - parse task (already provided as TaskContract)
        2. PLAN - determine required capabilities (from TaskContract)
        3. SELECT - find suitable worker via AgentRegistry
        4. DELEGATE - execute via WorkerAdapter
        5. EXECUTE - worker runs task
        6. VERIFY - independent verification
        7. RETRY/ESCALATE if needed
        8. RETURN - OrchestrationResult

        Args:
            task: The task contract to orchestrate.

        Returns:
            OrchestrationResult with full execution and verification details.
        """
        started_at = datetime.now(UTC)
        logger.info("Orchestrator starting task %s: %s", task.task_id, task.objective)

        # UNDERSTAND & PLAN - TaskContract already provides objective and capabilities
        required_capabilities = task.allowed_capabilities
        logger.debug("Task %s requires capabilities: %s", task.task_id, required_capabilities)

        # SELECT - find suitable worker via AgentRegistry
        selected_agent = self._registry.select_by_capabilities(required_capabilities)
        if selected_agent is None:
            logger.warning(
                "No worker found for task %s with capabilities %s",
                task.task_id,
                required_capabilities,
            )
            return OrchestrationResult(
                task_id=task.task_id,
                objective=task.objective,
                selected_agent_id=None,
                worker_result=None,
                verification_detail=None,
                status=OrchestrationStatus.NO_WORKER,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                notes=f"No worker registered for required capabilities: {required_capabilities}",
            )

        # Check for unknown capabilities
        missing_caps = set(required_capabilities) - set(selected_agent.capabilities)
        if missing_caps:
            logger.warning(
                "Selected worker %s missing capabilities: %s",
                selected_agent.agent_id,
                missing_caps,
            )
            return OrchestrationResult(
                task_id=task.task_id,
                objective=task.objective,
                selected_agent_id=selected_agent.agent_id,
                worker_result=None,
                verification_detail=None,
                status=OrchestrationStatus.UNKNOWN_CAPABILITY,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                notes=(
                    f"Worker {selected_agent.agent_id} missing required "
                    f"capabilities: {missing_caps}"
                ),
            )

        logger.info("Selected worker %s for task %s", selected_agent.agent_id, task.task_id)

        # DELEGATE & EXECUTE - get adapter and execute
        adapter = self._registry.get_adapter(selected_agent.agent_id)
        if adapter is None:
            logger.error("No adapter found for registered agent %s", selected_agent.agent_id)
            return OrchestrationResult(
                task_id=task.task_id,
                objective=task.objective,
                selected_agent_id=selected_agent.agent_id,
                worker_result=None,
                verification_detail=None,
                status=OrchestrationStatus.WORKER_FAILURE,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                notes=f"Adapter not found for agent {selected_agent.agent_id}",
            )

        # Execute with retry/escalation logic
        return await self._execute_with_retry(
            task=task,
            selected_agent=selected_agent,
            adapter=adapter,
            started_at=started_at,
        )

    async def _execute_with_retry(
        self,
        task: TaskContract,
        selected_agent,
        adapter,
        started_at: datetime,
    ) -> OrchestrationResult:
        """
        Execute task with retry/escalation logic.

        Flow:
        EXECUTE
           ↓
        VERIFY
           ├── PASS → ACCEPT
           ├── NEEDS_REVIEW → ESCALATE
           └── FAIL
                ↓
              retry once (if retries < MAX_RETRIES)
                ↓
              EXECUTE
                ↓
              VERIFY
                ├── PASS → ACCEPT
                ├── FAIL → ESCALATE
                └── NEEDS_REVIEW → ESCALATE
        """
        retries = 0

        while True:
            logger.info(
                "Executing task %s with worker %s (attempt %d)",
                task.task_id,
                selected_agent.agent_id,
                retries + 1,
            )

            # EXECUTE
            worker_result = await adapter.execute(task)
            logger.info(
                "Worker %s completed task %s with status: %s",
                selected_agent.agent_id,
                task.task_id,
                worker_result.status,
            )

            # Check for worker failure
            if worker_result.status in ("failed", "timeout"):
                completed_at = datetime.now(UTC)
                return OrchestrationResult(
                    task_id=task.task_id,
                    objective=task.objective,
                    selected_agent_id=selected_agent.agent_id,
                    worker_result=worker_result,
                    verification_detail=None,
                    status=OrchestrationStatus.WORKER_FAILURE,
                    started_at=started_at,
                    completed_at=completed_at,
                    notes=(
                        f"Worker {selected_agent.agent_id} failed with "
                        f"status: {worker_result.status}"
                    ),
                )

            # VERIFY - independent verification
            logger.info("Verifying task %s (attempt %d)", task.task_id, retries + 1)
            artifacts = {}
            if hasattr(adapter, "get_staged_changes"):
                artifacts = adapter.get_staged_changes()

            try:
                verification_detail = self._verifier.verify(
                    task=task,
                    result=worker_result,
                    artifacts=artifacts,
                )
            except Exception as exc:
                logger.exception("Verifier failed for task %s", task.task_id)
                completed_at = datetime.now(UTC)
                return OrchestrationResult(
                    task_id=task.task_id,
                    objective=task.objective,
                    selected_agent_id=selected_agent.agent_id,
                    worker_result=worker_result,
                    verification_detail=None,
                    status=OrchestrationStatus.VERIFIER_FAILURE,
                    started_at=started_at,
                    completed_at=completed_at,
                    notes=f"Verifier raised exception: {exc}",
                )

            # Determine status from verification
            verification_overall = verification_detail.overall

            # PASS -> ACCEPT immediately
            if verification_overall == "pass":
                completed_at = datetime.now(UTC)
                notes = f"Verification: {verification_overall.value} (attempt {retries + 1})"
                return OrchestrationResult(
                    task_id=task.task_id,
                    objective=task.objective,
                    selected_agent_id=selected_agent.agent_id,
                    worker_result=worker_result,
                    verification_detail=verification_detail,
                    status=OrchestrationStatus.PASS,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    notes=notes,
                )

            # NEEDS_REVIEW -> ESCALATE immediately (no retry)
            if verification_overall == "needs_review":
                completed_at = datetime.now(UTC)
                return OrchestrationResult(
                    task_id=task.task_id,
                    objective=task.objective,
                    selected_agent_id=selected_agent.agent_id,
                    worker_result=worker_result,
                    verification_detail=verification_detail,
                    status=OrchestrationStatus.ESCALATED,
                    started_at=started_at,
                    completed_at=completed_at,
                    notes=(
                        f"Escalated after verification NEEDS_REVIEW "
                        f"(attempt {retries + 1}): {verification_detail.notes}"
                    ),
                )

            # FAIL - check if we can retry
            if verification_overall == "fail":
                if retries >= self.MAX_RETRIES:
                    # No more retries - ESCALATE
                    completed_at = datetime.now(UTC)
                    return OrchestrationResult(
                        task_id=task.task_id,
                        objective=task.objective,
                        selected_agent_id=selected_agent.agent_id,
                        worker_result=worker_result,
                        verification_detail=verification_detail,
                        status=OrchestrationStatus.ESCALATED,
                        started_at=started_at,
                        completed_at=completed_at,
                        notes=(
                            f"Escalated after {retries + 1} attempt(s) "
                            f"with FAIL: {verification_detail.notes}"
                        ),
                    )
                else:
                    # Retry - same worker, increment counter
                    retries += 1
                    logger.info(
                        "Verification FAIL, retrying task %s (retry %d of %d)",
                        task.task_id,
                        retries,
                        self.MAX_RETRIES,
                    )
                    # Clear staged changes for retry to avoid duplicate application
                    if hasattr(adapter, "clear_staged_changes"):
                        adapter.clear_staged_changes()
                    # Continue loop for retry
                    continue

            # Fallback - should not reach here
            completed_at = datetime.now(UTC)
            return OrchestrationResult(
                task_id=task.task_id,
                objective=task.objective,
                selected_agent_id=selected_agent.agent_id,
                worker_result=worker_result,
                verification_detail=verification_detail,
                status=OrchestrationStatus.FAIL,
                started_at=started_at,
                completed_at=completed_at,
                notes=f"Unexpected verification result: {verification_overall.value}",
            )

    def _map_verification_status(
        self, verification_result: VerificationResult
    ) -> OrchestrationStatus:
        """Map VerificationResult to OrchestrationStatus (legacy method)."""
        mapping = {
            "pass": OrchestrationStatus.PASS,
            "fail": OrchestrationStatus.FAIL,
            "needs_review": OrchestrationStatus.NEEDS_REVIEW,
        }
        return mapping.get(verification_result.value, OrchestrationStatus.FAIL)


__all__ = ["Orchestrator"]
