"""
Deterministic Verifier for M8.1.

The verifier evaluates a worker's result against the task contract
acceptance criteria. It is independent from the worker and does not
trust the worker's self-reported status.

Verification is deterministic and based on:
- WorkerResult status (completed/failed/timeout)
- Artifact presence
- Acceptance criteria evaluation (deterministic checks)
- Worker execution status
"""

from __future__ import annotations

import logging

from friday.orchestration.models import (
    TaskContract,
    VerificationResult,
    VerificationResultDetail,
    WorkerResult,
)

logger = logging.getLogger(__name__)


class DeterministicVerifier:
    """
    Deterministic verifier for M8.1.

    The verifier evaluates a worker's result against the task contract
    acceptance criteria. It is independent from the worker and does not
    trust the worker's self-reported status.

    Verification is deterministic and reproducible:
    - PASS: All required criteria satisfied with sufficient evidence
    - FAIL: Any required criterion explicitly failed
    - NEEDS_REVIEW: Insufficient evidence to determine PASS/FAIL
    """

    def __init__(self) -> None:
        pass

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
        artifacts = artifacts or {}

        passed: list[str] = []
        failed: list[str] = []
        insufficient: list[str] = []

        # 1. Check worker execution status
        if result.status == "timeout":
            failed.append("worker_timeout: task execution timed out")
        elif result.status == "failed":
            failed.append(f"worker_failed: {result.error or 'unknown error'}")
        elif result.status != "completed":
            failed.append(f"worker_unexpected_status: {result.status}")

        # 2. Check artifact presence
        if result.artifacts:
            passed.append("artifacts_present: worker produced artifacts")
            # Verify artifacts actually exist in provided artifacts dict
            for artifact in result.artifacts:
                if artifact in artifacts:
                    passed.append(f"artifact_exists: {artifact}")
                else:
                    failed.append(f"artifact_missing: {artifact} not in provided artifacts")
        # Check if any acceptance criteria imply artifacts should exist
        elif self._criteria_require_artifacts(task.acceptance_criteria):
            failed.append("no_artifacts: worker produced no artifacts but criteria require them")
        else:
            passed.append("no_artifacts_expected: no artifacts produced (acceptable for this task)")

        # 3. Evaluate acceptance criteria
        for criterion in task.acceptance_criteria:
            self._evaluate_criterion(criterion, result, artifacts, passed, failed, insufficient)

        # 4. Check worker error
        if result.error:
            failed.append(f"worker_error: {result.error}")

        # 5. Determine overall result
        overall = self._determine_overall(failed, insufficient)

        notes = self._build_notes(task, result, artifacts)

        return VerificationResultDetail(
            overall=overall,
            passed_criteria=tuple(passed),
            failed_criteria=tuple(failed),
            insufficient_evidence=tuple(insufficient),
            notes=notes,
        )

    def _criteria_require_artifacts(self, criteria: tuple[str, ...]) -> bool:
        """Check if any criteria imply artifacts should be produced."""
        artifact_keywords = (
            "file",
            "files",
            "create",
            "generate",
            "produce",
            "output",
            "artifact",
            "implement",
            "feature",
            "fix",
            "add",
        )
        for criterion in criteria:
            criterion_lower = criterion.lower()
            if any(keyword in criterion_lower for keyword in artifact_keywords):
                return True
        return False

    def _evaluate_criterion(
        self,
        criterion: str,
        result: WorkerResult,
        artifacts: dict[str, str],
        passed: list[str],
        failed: list[str],
        insufficient: list[str],
    ) -> None:
        """Evaluate a single acceptance criterion."""
        criterion_lower = criterion.lower()

        # Check for file existence criteria
        if self._matches_file_criterion(criterion_lower):
            self._handle_file_criterion(result.artifacts, criterion, passed, failed)
            return

        # Check for test passing criteria
        if self._matches_test_criterion(criterion_lower):
            self._handle_test_criterion(result.artifacts, criterion, passed, insufficient)
            return

        # Check for lint/clean criteria
        if self._matches_lint_criterion(criterion_lower):
            insufficient.append(
                f"criterion_insufficient_evidence: {criterion} (cannot verify without running lint)"
            )
            return

        # Check for specific output/content criteria
        if self._matches_content_criterion(criterion_lower):
            if self._content_matches_criterion(criterion, result.output, artifacts):
                passed.append(f"criterion: {criterion}")
            else:
                failed.append(
                    f"criterion_failed: {criterion} (content not found in output/artifacts)"
                )
            return

        # Check for process/exit status criteria
        if self._matches_process_criterion(criterion_lower):
            self._handle_process_criterion(result.status, criterion, passed, failed)
            return

        # Check for explicit completion criteria
        if self._matches_completion_criterion(criterion_lower):
            self._handle_completion_criterion(result.status, criterion, passed, failed)
            return

        # Generic criterion - conservative: only PASS if explicit evidence in artifacts
        insufficient.append(
            f"criterion_insufficient_evidence: {criterion} (cannot deterministically verify)"
        )

    def _matches_file_criterion(self, criterion_lower: str) -> bool:
        return any(
            keyword in criterion_lower
            for keyword in ("file exists", "file present", "file created")
        )

    def _handle_file_criterion(
        self,
        artifacts: tuple[str, ...],
        criterion: str,
        passed: list[str],
        failed: list[str],
    ) -> None:
        if artifacts:
            passed.append(f"criterion: {criterion}")
        else:
            failed.append(f"criterion_failed: {criterion} (no artifacts produced)")

    def _matches_test_criterion(self, criterion_lower: str) -> bool:
        return any(
            keyword in criterion_lower for keyword in ("test pass", "tests pass", "all tests")
        )

    def _handle_test_criterion(
        self,
        artifacts: tuple[str, ...],
        criterion: str,
        passed: list[str],
        insufficient: list[str],
    ) -> None:
        test_artifacts = [a for a in artifacts if "test" in a.lower()]
        if test_artifacts:
            passed.append(f"criterion: {criterion}")
        else:
            insufficient.append(
                f"criterion_insufficient_evidence: {criterion} (no test artifacts found)"
            )

    def _matches_lint_criterion(self, criterion_lower: str) -> bool:
        return any(
            keyword in criterion_lower for keyword in ("lint clean", "lint passes", "no lint")
        )

    def _matches_content_criterion(self, criterion_lower: str) -> bool:
        return any(
            keyword in criterion_lower for keyword in ("output contains", "contains", "includes")
        )

    def _matches_process_criterion(self, criterion_lower: str) -> bool:
        return any(
            keyword in criterion_lower
            for keyword in ("exit code", "exit status", "process", "command")
        )

    def _handle_process_criterion(
        self,
        status: str,
        criterion: str,
        passed: list[str],
        failed: list[str],
    ) -> None:
        if status == "completed":
            passed.append(f"criterion: {criterion}")
        else:
            failed.append(f"criterion_failed: {criterion} (process did not complete successfully)")

    def _matches_completion_criterion(self, criterion_lower: str) -> bool:
        explicit_completion = ("complete", "completes", "finish", "task completes")
        return criterion_lower in explicit_completion

    def _handle_completion_criterion(
        self,
        status: str,
        criterion: str,
        passed: list[str],
        failed: list[str],
    ) -> None:
        if status == "completed":
            passed.append(f"criterion: {criterion}")
        else:
            failed.append(f"criterion_failed: {criterion} (task did not complete)")

    def _content_matches_criterion(
        self, criterion: str, output: str, artifacts: dict[str, str]
    ) -> bool:
        """Check if criterion content matches output/artifacts (simple deterministic matching)."""
        # Extract keywords from criterion (simple heuristic)
        criterion_lower = criterion.lower()

        # Remove common words (including structural words that don't carry content meaning)
        stop_words = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "to",
            "of",
            "in",
            "on",
            "at",
            "by",
            "for",
            "with",
            "about",
            # Structural/content-agnostic words
            "output",
            "outputs",
            "contain",
            "contains",
            "include",
            "includes",
            "show",
            "shows",
            "display",
            "displays",
            "print",
            "prints",
            "return",
            "returns",
            "produce",
            "produces",
            "generate",
            "generates",
            "create",
            "creates",
            "make",
            "makes",
        }
        words = [w for w in criterion_lower.split() if w not in stop_words and len(w) > 2]

        if not words:
            return False

        # Search in output
        output_lower = output.lower()
        for word in words:
            if word in output_lower:
                return True

        # Search in artifacts
        for content in artifacts.values():
            content_lower = content.lower()
            for word in words:
                if word in content_lower:
                    return True

        return False

    def _determine_overall(
        self,
        failed: list[str],
        insufficient: list[str],
    ) -> VerificationResult:
        """Determine overall verification result."""
        if failed:
            return VerificationResult.FAIL
        if insufficient:
            return VerificationResult.NEEDS_REVIEW
        return VerificationResult.PASS

    def _build_notes(
        self,
        task: TaskContract,
        result: WorkerResult,
        artifacts: dict[str, str],
    ) -> str:
        """Build verification notes."""
        notes = []
        notes.append(f"Task: {task.task_id} ({task.objective})")
        notes.append(f"Worker: {result.agent_id} (status: {result.status})")
        notes.append(f"Artifacts: {len(result.artifacts)} file(s)")
        if result.error:
            notes.append(f"Worker error: {result.error}")
        if artifacts:
            notes.append(f"Artifact content provided: {len(artifacts)} file(s)")
        return " | ".join(notes)


__all__ = ["DeterministicVerifier"]
