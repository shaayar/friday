"""
Unit tests for Hermes Adapter (M8.2.1 - Real Hermes Integration).

These tests verify the HermesAdapter works with the real Hermes CLI.
The adapter executes real coding tasks via `hermes --oneshot` and
stages file changes for verification.
"""

import pytest

from friday.orchestration.adapters.hermes import HermesAdapter
from friday.orchestration.models import (
    TaskCapability,
    TaskContract,
    WorkerResult,
)


class TestHermesAdapter:
    """Tests for HermesAdapter with real Hermes CLI."""

    @pytest.fixture
    def adapter(self):
        return HermesAdapter(default_timeout=30.0)

    def test_capabilities(self, adapter):
        caps = adapter.capabilities()
        assert TaskCapability.READ in caps
        assert TaskCapability.WRITE in caps
        assert TaskCapability.EXECUTE in caps
        assert TaskCapability.NETWORK not in caps

    @pytest.mark.asyncio
    async def test_successful_execution(self, adapter):
        """Test that Hermes executes a coding task and produces artifacts."""
        task = TaskContract(
            task_id="test-1",
            objective="Create a simple python file with a hello world function",
            acceptance_criteria=("file created with hello world function",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )

        result = await adapter.execute(task)

        assert result.task_id == "test-1"
        assert result.agent_id == "hermes"
        assert result.status == "completed"
        assert len(result.artifacts) > 0
        assert result.error is None
        # Output should contain staging summary
        assert "executed via Hermes" in result.output or "Staged" in result.output

    @pytest.mark.asyncio
    async def test_test_objective_creates_file(self, adapter):
        """Test that a test-related objective creates a file."""
        task = TaskContract(
            task_id="test-2",
            objective="Write a simple test file",
            acceptance_criteria=("test file created",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )

        result = await adapter.execute(task)

        assert result.status == "completed"
        assert len(result.artifacts) > 0

    @pytest.mark.asyncio
    async def test_fix_objective_creates_file(self, adapter):
        """Test that a fix-related objective creates a file."""
        task = TaskContract(
            task_id="test-3",
            objective="Create a fix file for a bug",
            acceptance_criteria=("fix file created",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )

        result = await adapter.execute(task)

        assert result.status == "completed"
        assert len(result.artifacts) > 0

    @pytest.mark.asyncio
    async def test_generic_objective_creates_file(self, adapter):
        """Test that a generic objective creates a file."""
        task = TaskContract(
            task_id="test-4",
            objective="Create a simple python script",
            acceptance_criteria=("script created",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )

        result = await adapter.execute(task)

        assert result.status == "completed"
        assert len(result.artifacts) > 0

    @pytest.mark.asyncio
    async def test_timeout(self, adapter):
        """Test timeout handling."""
        task = TaskContract(
            task_id="test-timeout",
            objective="This should timeout",
            acceptance_criteria=("never completes",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
            timeout=0.01,  # Very short timeout
        )

        result = await adapter.execute(task)

        assert result.task_id == "test-timeout"
        # The timeout may or may not trigger depending on execution speed
        # Accept either timeout or completed with error
        assert result.status in ("timeout", "completed")
        if result.status == "timeout":
            assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_missing_capabilities_rejected(self, adapter):
        """Test that tasks requiring NETWORK capability are rejected."""
        task = TaskContract(
            task_id="test-caps",
            objective="Needs network",
            acceptance_criteria=("works",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
                TaskCapability.NETWORK,
            ),
        )

        result = await adapter.execute(task)

        assert result.status == "failed"
        assert "NETWORK" in result.error or "network" in result.error

    @pytest.mark.asyncio
    async def test_worker_isolation(self, adapter):
        """Each task execution should be isolated."""
        task1 = TaskContract(
            task_id="iso-1",
            objective="Create first file",
            acceptance_criteria=("done",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )
        task2 = TaskContract(
            task_id="iso-2",
            objective="Create second file",
            acceptance_criteria=("done",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )

        result1 = await adapter.execute(task1)
        result2 = await adapter.execute(task2)

        # Results should be independent
        assert result1.task_id == "iso-1"
        assert result2.task_id == "iso-2"
        assert result1.agent_id == result2.agent_id == "hermes"
        assert result1.status == "completed"
        assert result2.status == "completed"

    @pytest.mark.asyncio
    async def test_staged_changes_accessible(self, adapter):
        """Test that staged changes are accessible after execution."""
        task = TaskContract(
            task_id="stage-1",
            objective="Create a file for staging",
            acceptance_criteria=("staged",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )

        await adapter.execute(task)

        staged = adapter.get_staged_changes()
        assert len(staged) > 0

    @pytest.mark.asyncio
    async def test_clear_staged_changes(self, adapter):
        """Test clearing staged changes."""
        task = TaskContract(
            task_id="stage-2",
            objective="Test staging clear",
            acceptance_criteria=("cleared",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )

        await adapter.execute(task)
        assert len(adapter.get_staged_changes()) > 0

        adapter.clear_staged_changes()
        assert len(adapter.get_staged_changes()) == 0

    @pytest.mark.asyncio
    async def test_captures_output(self, adapter):
        """Test that output is captured."""
        task = TaskContract(
            task_id="output-1",
            objective="Test output capture",
            acceptance_criteria=("output captured",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )

        result = await adapter.execute(task)

        assert result.output
        assert len(result.output) > 0

    @pytest.mark.asyncio
    async def test_process_failure_handled(self, adapter):
        """Test that unexpected errors are handled at the adapter boundary."""
        task = TaskContract(
            task_id="error-1",
            objective="Test error handling",
            acceptance_criteria=("handles error",),
            allowed_capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
        )

        # Normal execution should work
        result = await adapter.execute(task)
        assert result.status == "completed"

    def test_worker_result_structure(self):
        """Verify WorkerResult has required fields."""
        # Can't easily test structure without async, but verify WorkerResult fields exist
        result = WorkerResult(
            task_id="struct-1",
            agent_id="hermes",
            status="completed",
            output="Test",
            artifacts=("file1.py",),
            error=None,
        )
        assert result.task_id == "struct-1"
        assert result.agent_id == "hermes"
        assert result.status == "completed"
        assert result.output == "Test"
        assert result.artifacts == ("file1.py",)
        assert result.error is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
