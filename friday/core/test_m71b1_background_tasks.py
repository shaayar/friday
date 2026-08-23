"""M7.1b.1 Tests — Background Task Coordination in AssistantSession.

Focused tests for the post-turn background task coordination layer.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from friday.core.session import AssistantSession

if TYPE_CHECKING:
    from _pytest.logging import LogCaptureFixture


# ======================================================================
# Fixtures
# ======================================================================


class FakeCoro:
    """A fake coroutine that completes or fails based on configuration."""

    def __init__(
        self,
        *,
        delay: float = 0.01,
        should_fail: bool = False,
        fail_after: float = 0.0,
        name: str = "fake_coro",
    ) -> None:
        self.delay = delay
        self.should_fail = should_fail
        self.fail_after = fail_after
        self.name = name
        self.started = False
        self.completed = False
        self.cancelled = False

    async def __call__(self) -> str:
        self.started = True
        try:
            if self.should_fail and self.fail_after > 0:
                await asyncio.sleep(self.fail_after)
                raise RuntimeError(f"Intentional failure in {self.name}")
            await asyncio.sleep(self.delay)
            if self.should_fail:
                raise RuntimeError(f"Intentional failure in {self.name}")
            self.completed = True
            return f"result from {self.name}"
        except asyncio.CancelledError:
            self.cancelled = True
            raise


# ======================================================================
# Test: Background Task Is Tracked
# ======================================================================


class TestBackgroundTaskTracking:
    """Test that background tasks are properly tracked by AssistantSession."""

    @pytest.mark.asyncio
    async def test_background_task_is_tracked(self) -> None:
        """Schedule a fake coroutine and verify task becomes owned."""
        session = AssistantSession()

        coro = FakeCoro(name="tracked_task")
        task = session._schedule_background(coro())

        assert task is not None
        assert task in session._background_tasks
        assert len(session._background_tasks) == 1

        await task  # Wait for completion
        assert coro.completed
        # Task should be removed from tracking after completion
        assert len(session._background_tasks) == 0

    @pytest.mark.asyncio
    async def test_completed_task_is_removed(self) -> None:
        """Schedule task, let it finish, verify it is no longer tracked."""
        session = AssistantSession()

        coro = FakeCoro(delay=0.01, name="completed_task")
        session._schedule_background(coro())

        assert len(session._background_tasks) == 1
        await asyncio.sleep(0.05)  # Let task complete

        assert len(session._background_tasks) == 0
        assert coro.completed

    @pytest.mark.asyncio
    async def test_multiple_background_tasks_are_independent(self) -> None:
        """One fails, another succeeds - both tracked independently."""
        session = AssistantSession()

        failing_coro = FakeCoro(delay=0.01, should_fail=True, name="failing")
        succeeding_coro = FakeCoro(delay=0.01, name="succeeding")

        failing_task = session._schedule_background(failing_coro())
        succeeding_task = session._schedule_background(succeeding_coro())

        assert failing_task is not None
        assert succeeding_task is not None
        assert len(session._background_tasks) == 2

        # Wait for both to complete
        await asyncio.gather(failing_task, succeeding_task, return_exceptions=True)

        # Both should be removed from tracking
        assert len(session._background_tasks) == 0
        assert succeeding_coro.completed
        assert failing_coro.started


# ======================================================================
# Test: Exception Handling
# ======================================================================


class TestBackgroundTaskExceptions:
    """Test that background task exceptions are observed and isolated."""

    @pytest.mark.asyncio
    async def test_background_task_exception_is_observed(
        self,
        caplog: LogCaptureFixture,
    ) -> None:
        """Task raises - verify exception is logged/consumed, no unhandled warning."""
        session = AssistantSession()

        coro = FakeCoro(delay=0.01, should_fail=True, name="exception_task")
        task = session._schedule_background(coro())

        assert task is not None
        # Wait for task to complete (with exception)
        await asyncio.gather(task, return_exceptions=True)

        # Verify task was tracked and completed
        assert len(session._background_tasks) == 0

        # Verify exception was logged (not unhandled)
        # The done_callback logs with exc_info; task name is auto-generated
        assert any(
            "Background task" in record.message and "failed" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_background_task_failure_does_not_affect_session(self) -> None:
        """Failing background task - session remains usable."""
        session = AssistantSession()

        failing_coro = FakeCoro(delay=0.01, should_fail=True, name="failing")
        session._schedule_background(failing_coro())

        await asyncio.sleep(0.05)  # Let it fail

        # Session should still be functional
        assert not session._stopping
        assert session.conversation_id is None  # Not started yet
        # Can still schedule new tasks
        new_coro = FakeCoro(name="new_task")
        new_task = session._schedule_background(new_coro())
        assert new_task is not None
        await new_task


# ======================================================================
# Test: Shutdown Behavior
# ======================================================================


class TestBackgroundTaskShutdown:
    """Test stop() correctly handles background tasks."""

    @pytest.mark.asyncio
    async def test_stop_cancels_background_tasks(self) -> None:
        """Long-running task - stop() - task receives cancellation."""
        session = AssistantSession()

        # Long-running task that can be cancelled
        coro = FakeCoro(delay=10.0, name="long_running")
        task = session._schedule_background(coro())

        assert task is not None
        assert len(session._background_tasks) == 1
        assert not task.done()

        await session.stop()

        # Task should be cancelled (cancelled() returns True after cancel())
        assert task.cancelled()
        assert len(session._background_tasks) == 0
        assert session._stopping

    @pytest.mark.asyncio
    async def test_stop_awaits_background_tasks(self) -> None:
        """Verify no owned task remains running after stop()."""
        session = AssistantSession()

        coro1 = FakeCoro(delay=10.0, name="task1")
        coro2 = FakeCoro(delay=10.0, name="task2")
        task1 = session._schedule_background(coro1())
        task2 = session._schedule_background(coro2())

        assert task1 is not None
        assert task2 is not None
        assert len(session._background_tasks) == 2

        await session.stop()

        # Both tasks should be cancelled and awaited
        assert task1.cancelled()
        assert task2.cancelled()
        assert len(session._background_tasks) == 0

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self) -> None:
        """Call stop() twice - no error."""
        session = AssistantSession()

        coro = FakeCoro(delay=10.0, name="idempotent_task")
        session._schedule_background(coro())

        await session.stop()
        # Second call should not raise
        await session.stop()

        assert session._stopping
        assert len(session._background_tasks) == 0

    @pytest.mark.asyncio
    async def test_new_tasks_rejected_after_stop(self) -> None:
        """Stop session - attempt scheduling - verify task is not created."""
        session = AssistantSession()

        await session.stop()

        coro = FakeCoro(name="rejected_task")
        task = session._schedule_background(coro())

        assert task is None
        assert not coro.started
        assert len(session._background_tasks) == 0

    @pytest.mark.asyncio
    async def test_completed_tasks_do_not_break_stop(self) -> None:
        """Completed task exists in tracking - stop() - no error."""
        session = AssistantSession()

        coro = FakeCoro(delay=0.01, name="quick_task")
        session._schedule_background(coro())

        await asyncio.sleep(0.05)  # Let it complete

        # Task should be auto-removed from tracking
        assert len(session._background_tasks) == 0

        # stop() should still work
        await session.stop()
        assert session._stopping

    @pytest.mark.asyncio
    async def test_cancellation_is_not_logged_as_failure(
        self,
        caplog: LogCaptureFixture,
    ) -> None:
        """Cancellation should be treated as normal shutdown behavior."""
        session = AssistantSession()

        coro = FakeCoro(delay=10.0, name="cancelled_task")
        session._schedule_background(coro())

        await session.stop()

        # The done_callback logs cancelled tasks at DEBUG level
        # It should NOT log at WARNING level
        warning_records = [r for r in caplog.records if r.levelno >= 30]
        failure_warnings = [
            r
            for r in warning_records
            if "failed" in r.message.lower() and "cancelled_task" in r.message
        ]
        assert len(failure_warnings) == 0


# ======================================================================
# Test: Store Cleanup
# ======================================================================


class TestStoreCleanup:
    """Test that existing conversation/memory store cleanup still happens."""

    @pytest.mark.asyncio
    async def test_store_cleanup_still_occurs(self) -> None:
        """Verify existing conversation/memory store cleanup still happens."""
        session = AssistantSession()

        await session.start()
        conv_id = session.conversation_id
        assert conv_id is not None

        # Verify stores are accessible
        assert session.conversation_store is not None
        assert session.memory_manager is not None

        await session.stop()

        # Stores should be closed
        # Verify we can't use them (they're closed)
        # This is a basic check - the actual close() is verified by not raising
        assert session._stopping

    @pytest.mark.asyncio
    async def test_start_then_stop_with_background_task(self) -> None:
        """Full lifecycle: start -> schedule task -> stop."""
        session = AssistantSession()

        await session.start()

        coro = FakeCoro(delay=0.01, name="lifecycle_task")
        session._schedule_background(coro())

        await asyncio.sleep(0.05)  # Let task complete

        await session.stop()

        assert coro.completed
        assert session._stopping
        assert len(session._background_tasks) == 0


# ======================================================================
# Test: Integration with existing context assembly
# ======================================================================


class TestContextAssemblyStillWorks:
    """Test that M7.1b.1 changes don't break existing context assembly."""

    @pytest.mark.asyncio
    async def test_context_assembly_still_works(self) -> None:
        """Verify assemble_context_for_turn still functions."""
        session = AssistantSession()
        await session.start()

        from livekit.agents.llm import ChatContext, ChatMessage

        turn_ctx = ChatContext.empty()
        new_message = ChatMessage(role="user", content=["Hello"])

        # This should not raise
        result_ctx = session.assemble_context_for_turn(turn_ctx, new_message)

        assert result_ctx is not None
        assert len(result_ctx.items) >= 1  # At least system message

        await session.stop()


# ======================================================================
# Run verification
# ======================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
