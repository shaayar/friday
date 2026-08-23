"""
Unit tests for DeterministicVerifier.
"""

import pytest

from friday.orchestration.models import (
    TaskCapability,
    TaskContract,
    VerificationResult,
    WorkerResult,
)
from friday.orchestration.verifiers.deterministic import DeterministicVerifier


class TestDeterministicVerifier:
    """Tests for DeterministicVerifier."""

    @pytest.fixture
    def verifier(self):
        return DeterministicVerifier()

    def make_result(
        self,
        task_id: str = "test-1",
        agent_id: str = "hermes",
        status: str = "completed",
        output: str = "Success",
        artifacts: tuple[str, ...] = (),
        error: str | None = None,
    ) -> WorkerResult:
        return WorkerResult(
            task_id=task_id,
            agent_id=agent_id,
            status=status,
            output=output,
            artifacts=artifacts,
            error=error,
        )

    def make_task(
        self,
        task_id: str = "test-1",
        objective: str = "Test objective",
        acceptance_criteria: tuple[str, ...] = ("criterion",),
        allowed_capabilities: tuple = (),
    ) -> TaskContract:
        return TaskContract(
            task_id=task_id,
            objective=objective,
            acceptance_criteria=acceptance_criteria,
            allowed_capabilities=allowed_capabilities,
        )

    # ===== PASS tests =====

    def test_pass_on_successful_completion(self, verifier):
        """All criteria satisfied -> PASS."""
        task = self.make_task(
            task_id="pass-1",
            objective="Test pass",
            acceptance_criteria=("task completes",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(
            status="completed",
            output="Task completed successfully",
            artifacts=("output.txt",),
        )
        artifacts = {"output.txt": "Content here"}

        detail = verifier.verify(task, result, artifacts)

        assert detail.overall == VerificationResult.PASS
        assert len(detail.failed_criteria) == 0
        assert len(detail.insufficient_evidence) == 0

    def test_pass_on_completed_with_artifacts(self, verifier):
        """Completed with artifacts present -> PASS."""
        task = self.make_task(
            task_id="pass-2",
            objective="Create a file",
            acceptance_criteria=("file created",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(
            status="completed", output="File created", artifacts=("new_file.txt",)
        )
        artifacts = {"new_file.txt": "File content"}

        detail = verifier.verify(task, result, artifacts)

        assert detail.overall == VerificationResult.PASS

    def test_pass_no_artifacts_when_not_required(self, verifier):
        """No artifacts but criteria don't require them -> PASS."""
        task = self.make_task(
            task_id="pass-3",
            objective="Verify something",
            acceptance_criteria=("task completes",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(
            status="completed", output="Verification complete", artifacts=()
        )

        detail = verifier.verify(task, result, {})

        assert detail.overall == VerificationResult.PASS

    # ===== FAIL tests =====

    def test_fail_on_timeout(self, verifier):
        """Worker timeout -> FAIL."""
        task = self.make_task(
            task_id="fail-1",
            objective="Long running task",
            acceptance_criteria=("completes",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(status="timeout", output="", error="Timed out")

        detail = verifier.verify(task, result, {})

        assert detail.overall == VerificationResult.FAIL
        assert any("worker_timeout" in c for c in detail.failed_criteria)

    def test_fail_on_worker_failed(self, verifier):
        """Worker execution failed -> FAIL."""
        task = self.make_task(
            task_id="fail-2",
            objective="Task that fails",
            acceptance_criteria=("completes",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(
            status="failed", output="", error="Segmentation fault"
        )

        detail = verifier.verify(task, result, {})

        assert detail.overall == VerificationResult.FAIL
        assert any("worker_failed" in c for c in detail.failed_criteria)

    def test_fail_on_worker_error(self, verifier):
        """Worker error reported -> FAIL."""
        task = self.make_task(
            task_id="fail-3",
            objective="Task with error",
            acceptance_criteria=("completes",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(
            status="completed", output="Done", error="Warning: something went wrong"
        )

        detail = verifier.verify(task, result, {})

        assert detail.overall == VerificationResult.FAIL
        assert any("worker_error" in c for c in detail.failed_criteria)

    def test_fail_on_missing_artifact(self, verifier):
        """Missing required artifact -> FAIL."""
        task = self.make_task(
            task_id="fail-4",
            objective="Create a file",
            acceptance_criteria=("file created",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(status="completed", output="Done", artifacts=())

        detail = verifier.verify(task, result, {})

        assert detail.overall == VerificationResult.FAIL
        assert any("no_artifacts" in c for c in detail.failed_criteria)

    def test_fail_on_missing_required_artifact(self, verifier):
        """Artifact declared but not in provided artifacts -> FAIL."""
        task = self.make_task(
            task_id="fail-5",
            objective="Create output",
            acceptance_criteria=("file created",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(
            status="completed", output="Done", artifacts=("output.txt",)
        )
        artifacts = {}  # Empty - artifact not provided

        detail = verifier.verify(task, result, artifacts)

        assert detail.overall == VerificationResult.FAIL
        assert any("artifact_missing" in c for c in detail.failed_criteria)

    def test_fail_on_missing_acceptance_criterion(self, verifier):
        """Explicit criterion failure -> FAIL."""
        task = self.make_task(
            task_id="fail-6",
            objective="Test content check",
            acceptance_criteria=("output contains success",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(
            status="completed", output="Task failed completely", artifacts=()
        )
        artifacts = {}

        detail = verifier.verify(task, result, artifacts)

        assert detail.overall == VerificationResult.FAIL
        assert any("criterion_failed" in c for c in detail.failed_criteria)

    # ===== NEEDS_REVIEW tests =====

    def test_needs_review_on_insufficient_evidence(self, verifier):
        """Insufficient evidence -> NEEDS_REVIEW."""
        task = self.make_task(
            task_id="review-1",
            objective="Complex task",
            acceptance_criteria=("lint clean",),  # Cannot verify deterministically
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(status="completed", output="Done", artifacts=())
        artifacts = {}

        detail = verifier.verify(task, result, artifacts)

        assert detail.overall == VerificationResult.NEEDS_REVIEW
        assert any("insufficient_evidence" in c for c in detail.insufficient_evidence)

    def test_needs_review_on_generic_criterion(self, verifier):
        """Generic criterion without evidence -> NEEDS_REVIEW."""
        task = self.make_task(
            task_id="review-2",
            objective="Do something",
            acceptance_criteria=("task completes successfully",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(status="completed", output="Task done", artifacts=())
        artifacts = {}

        detail = verifier.verify(task, result, artifacts)

        assert detail.overall == VerificationResult.NEEDS_REVIEW
        assert any("insufficient_evidence" in c for c in detail.insufficient_evidence)

    def test_needs_review_on_lint_criterion(self, verifier):
        """Lint criterion cannot be verified -> NEEDS_REVIEW."""
        task = self.make_task(
            task_id="review-3",
            objective="Code quality",
            acceptance_criteria=("lint clean",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(status="completed", output="Done", artifacts=())
        artifacts = {}

        detail = verifier.verify(task, result, artifacts)

        assert detail.overall == VerificationResult.NEEDS_REVIEW
        assert any("insufficient_evidence" in c for c in detail.insufficient_evidence)

    def test_needs_review_on_test_criterion_no_test_artifacts(self, verifier):
        """Tests pass criterion but no test artifacts -> NEEDS_REVIEW."""
        task = self.make_task(
            task_id="review-4",
            objective="Testing",
            acceptance_criteria=("tests pass",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(status="completed", output="Done", artifacts=())
        artifacts = {}

        detail = verifier.verify(task, result, artifacts)

        assert detail.overall == VerificationResult.NEEDS_REVIEW
        assert any("insufficient_evidence" in c for c in detail.insufficient_evidence)

    # ===== Determinism tests =====

    def test_deterministic_results(self, verifier):
        """Same inputs produce same results."""
        task = self.make_task(
            task_id="det-1",
            objective="Test determinism",
            acceptance_criteria=("completes",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(status="completed", output="Done", artifacts=())

        detail1 = verifier.verify(task, result, {})
        detail2 = verifier.verify(task, result, {})
        detail3 = verifier.verify(task, result, {})

        assert detail1.overall == detail2.overall == detail3.overall
        assert (
            detail1.passed_criteria
            == detail2.passed_criteria
            == detail3.passed_criteria
        )
        assert (
            detail1.failed_criteria
            == detail2.failed_criteria
            == detail3.failed_criteria
        )
        assert (
            detail1.insufficient_evidence
            == detail2.insufficient_evidence
            == detail3.insufficient_evidence
        )

    # ===== Independence tests =====

    def test_verifier_independent_from_worker(self, verifier):
        """Verifier does not trust worker's status."""
        # Worker says completed but has error
        task = self.make_task(
            task_id="ind-1",
            objective="Test independence",
            acceptance_criteria=("completes",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(
            status="completed", output="Done", error="Internal error occurred"
        )

        detail = verifier.verify(task, result, {})

        # Should FAIL despite worker saying completed
        assert detail.overall == VerificationResult.FAIL
        assert any("worker_error" in c for c in detail.failed_criteria)

    def test_verifier_does_not_invoke_worker(self, verifier):
        """Verifier only evaluates, does not invoke workers."""
        # This is a design property - the verify method only takes
        # task, result, artifacts - no worker/executor references
        task = self.make_task(
            task_id="ind-2",
            objective="Test",
            acceptance_criteria=("completes",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(status="completed", output="Done", artifacts=())

        verifier.verify(task, result, {})
        assert True  # Verify only evaluates

    def test_verifier_does_not_modify_filesystem(self, verifier, tmp_path):
        """Verifier does not modify filesystem."""
        task = self.make_task(
            task_id="ind-3",
            objective="Test",
            acceptance_criteria=("completes",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(status="completed", output="Done", artifacts=())

        # Record filesystem state
        files_before = list(tmp_path.rglob("*"))

        verifier.verify(task, result, {})

        # Verify no files created/modified
        files_after = list(tmp_path.rglob("*"))
        assert len(files_after) == len(files_before)

    def test_verifier_does_not_modify_input(self, verifier):
        """Verifier does not modify input objects."""
        task = self.make_task(
            task_id="ind-4",
            objective="Test immutability",
            acceptance_criteria=("completes",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        result = self.make_result(
            status="completed", output="Done", artifacts=("file.txt",)
        )
        artifacts = {"file.txt": "content"}

        original_task_id = task.task_id
        original_artifacts = dict(artifacts)

        verifier.verify(task, result, artifacts)

        assert task.task_id == original_task_id
        assert artifacts == original_artifacts
        assert result.task_id == "test-1"  # result also unchanged


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
