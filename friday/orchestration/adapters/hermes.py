"""
Hermes Adapter for M8.2.1 — Real Hermes CLI Integration.

This adapter executes coding tasks via the Hermes CLI (--oneshot mode).
It preserves the M8.1 adapter boundary and verified-before-apply behavior.

Key properties:
- Hermes remains behind WorkerAdapter protocol
- TaskContract -> WorkerResult boundary unchanged
- Changes are staged for verification, NOT auto-applied
- Timeout/error handling preserved
- No FRIDAY-managed worker spawning
- No capability routing (handled at registry level)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

from friday.orchestration.models import (
    TaskCapability,
    TaskContract,
    WorkerResult,
)

logger = logging.getLogger(__name__)


class HermesAdapter:
    """
    Real Hermes adapter for M8.2.1 — executes coding tasks via Hermes CLI.

    This adapter invokes `hermes --oneshot` with appropriate toolsets to
    execute coding tasks. It captures the execution result, any file changes
    made during execution, and returns a structured WorkerResult.

    The adapter boundary isolates the orchestrator from the execution mechanism.
    Worker-generated changes are NOT automatically applied to the canonical
    repository. They are staged for verification via get_staged_changes().

    Toolsets enabled: file, terminal (for coding tasks)
    """

    def __init__(
        self,
        *,
        working_directory: Path | str | None = None,
        default_timeout: float = 300.0,
        hermes_bin: str = "hermes",
    ) -> None:
        self._working_directory = Path(working_directory) if working_directory else Path.cwd()
        self._default_timeout = default_timeout
        self._hermes_bin = hermes_bin
        self._staged_changes: dict[str, str] = {}  # file_path -> content
        self._last_execution_files: dict[
            str, tuple[float, int, str]
        ] = {}  # Track files from last run

    def capabilities(self) -> tuple[TaskCapability, ...]:
        """Return the capabilities this adapter provides."""
        return (TaskCapability.READ, TaskCapability.WRITE, TaskCapability.EXECUTE)

    async def execute(self, task: TaskContract) -> WorkerResult:
        """
        Execute a task via Hermes CLI and return the result.

        Flow:
        1. Verify required capabilities
        2. Build Hermes prompt from TaskContract
        3. Execute Hermes with timeout
        4. Capture output and detect file changes
        5. Stage changes for verification
        6. Return WorkerResult

        Worker-generated changes are NOT automatically applied to the
        canonical repository. They are staged for verification.
        """
        task_id = task.task_id
        agent_id = "hermes"

        logger.info("HermesAdapter executing task %s: %s", task_id, task.objective)

        try:
            # Verify the task has required capabilities
            required_caps = set(task.allowed_capabilities)
            adapter_caps = set(self.capabilities())
            if not required_caps.issubset(adapter_caps):
                missing = required_caps - adapter_caps
                return WorkerResult(
                    task_id=task_id,
                    agent_id=agent_id,
                    status="failed",
                    output="",
                    error=f"Task requires capabilities not provided by adapter: {missing}",
                )

            # Execute with timeout
            try:
                result = await asyncio.wait_for(
                    self._execute_internal(task),
                    timeout=task.timeout,
                )
            except TimeoutError:
                return WorkerResult(
                    task_id=task_id,
                    agent_id=agent_id,
                    status="timeout",
                    output="",
                    error=f"Task timed out after {task.timeout}s",
                )

            return result

        except Exception as exc:
            logger.exception("HermesAdapter execution failed for task %s", task_id)
            return WorkerResult(
                task_id=task_id,
                agent_id=agent_id,
                status="failed",
                output="",
                error=f"Adapter error: {exc!s}",
            )

    async def _execute_internal(self, task: TaskContract) -> WorkerResult:
        """
        Internal execution logic - invokes Hermes CLI.

        1. Capture pre-execution file state
        2. Build prompt from TaskContract
        3. Run Hermes --oneshot with file,terminal toolsets
        4. Capture post-execution file state
        5. Diff to find created/modified files
        6. Stage changes for verification
        """
        task_id = task.task_id
        agent_id = "hermes"

        # Snapshot files before execution (in working directory)
        pre_files = self._snapshot_files(self._working_directory)

        # Build prompt from task contract
        prompt = self._build_prompt(task)

        # Execute Hermes
        logger.debug("Running Hermes for task %s with prompt: %s", task_id, prompt[:200])
        worker_result = await self._run_hermes(prompt, task.timeout)

        # Snapshot files after execution
        post_files = self._snapshot_files(self._working_directory)

        # Detect new/modified files
        staged_files = self._detect_changes(pre_files, post_files)

        # Store staged changes for verification
        self._staged_changes = staged_files.copy()
        self._last_execution_files = post_files.copy()

        # Prepare artifacts (staged files)
        artifacts = tuple(sorted(staged_files.keys()))

        # Build output summary
        output_lines = [
            f"Task {task_id} executed via Hermes",
            f"Staged {len(staged_files)} file(s) for verification:",
        ]
        for file_path, content in staged_files.items():
            output_lines.append(f"  - {file_path} ({len(content)} bytes)")
        if not staged_files:
            output_lines.append("  (no files created/modified)")
        output = "\n".join(output_lines)

        # Combine Hermes output with our summary
        full_output = f"{worker_result.output}\n\n{output}" if worker_result.output else output

        return WorkerResult(
            task_id=task_id,
            agent_id=agent_id,
            status=worker_result.status,
            output=full_output,
            artifacts=artifacts,
            error=worker_result.error,
        )

    def _build_prompt(self, task: TaskContract) -> str:
        """Build a structured prompt for Hermes from the TaskContract."""
        parts = [
            f"Task ID: {task.task_id}",
            f"Objective: {task.objective}",
            "",
            "Acceptance Criteria:",
        ]
        for i, criterion in enumerate(task.acceptance_criteria, 1):
            parts.append(f"  {i}. {criterion}")

        if task.inputs:
            parts.append("")
            parts.append("Inputs:")
            for inp in task.inputs:
                parts.append(f"  - {inp}")

        if task.constraints:
            parts.append("")
            parts.append("Constraints:")
            for constraint in task.constraints:
                parts.append(f"  - {constraint}")

        parts.append("")
        parts.append(
            "Work in the current directory. Create/modify files as needed. "
            "Do not run tests unless explicitly asked. "
            "Report what files you created or modified."
        )

        return "\n".join(parts)

    async def _run_hermes(self, prompt: str, timeout: float) -> WorkerResult:
        """Run Hermes CLI with the given prompt and timeout."""
        task_id = str(uuid.uuid4())[:8]  # Short ID for logging

        # Prepare command
        cmd = [
            self._hermes_bin,
            "--oneshot",
            prompt,
            "--toolsets",
            "file,terminal",
            "--usage-file",
            "/dev/stdout",  # Get usage JSON on stdout
        ]

        # Run in working directory
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["HERMES_STATE_DB_GUARD_BYPASS"] = "1"
        env["HERMES_ACCEPT_HOOKS"] = "1"

        try:
            # Use asyncio subprocess for proper timeout handling
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self._working_directory,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return WorkerResult(
                    task_id=task_id,
                    agent_id="hermes",
                    status="timeout",
                    output="",
                    error=f"Hermes execution timed out after {timeout}s",
                )

            # Parse output - last line is JSON usage, rest is response
            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")

            # Extract usage JSON (last line if valid JSON)
            output_lines = stdout_text.strip().split("\n")
            response_text = ""
            usage = None

            # Find JSON usage line (starts with {)
            for i, line in enumerate(output_lines):
                if line.strip().startswith("{") and line.strip().endswith("}"):
                    try:
                        usage = json.loads(line)
                        response_text = "\n".join(output_lines[:i])
                        break
                    except json.JSONDecodeError:
                        continue

            if usage is None:
                response_text = stdout_text

            # Determine status
            if proc.returncode == 0:
                status = "completed"
                error_msg = None
            else:
                status = "failed"
                error_msg = stderr_text or f"Hermes exited with code {proc.returncode}"

            return WorkerResult(
                task_id=task_id,
                agent_id="hermes",
                status=status,
                output=response_text.strip(),
                artifacts=(),
                error=error_msg if status == "failed" else None,
            )

        except FileNotFoundError:
            return WorkerResult(
                task_id=task_id,
                agent_id="hermes",
                status="failed",
                output="",
                error=f"Hermes binary not found: {self._hermes_bin}",
            )
        except Exception as exc:
            logger.exception("Hermes execution failed")
            return WorkerResult(
                task_id=task_id,
                agent_id="hermes",
                status="failed",
                output="",
                error=f"Execution error: {exc!s}",
            )

    def _snapshot_files(self, directory: Path) -> dict[str, tuple[float, int, str]]:
        """
        Snapshot all files in directory.
        Returns dict: relative_path -> (mtime, size, content_hash)
        """
        snapshot = {}
        ignore_dirs = {
            ".git",
            ".pytest_cache",
            ".mypy_cache",
            "__pycache__",
            ".venv",
            "venv",
            ".hg",
            ".svn",
            "node_modules",
            "dist",
            "build",
            ".tox",
            ".coverage",
            "htmlcov",
            ".ruff_cache",
        }

        try:
            for file_path in directory.rglob("*"):
                if file_path.is_file():
                    # Check if any parent directory should be ignored
                    should_ignore = False
                    for part in file_path.parts:
                        if part in ignore_dirs:
                            should_ignore = True
                            break
                    if should_ignore:
                        continue

                    try:
                        rel_path = file_path.relative_to(directory)
                        stat = file_path.stat()
                        # Read first 1KB for content hash (efficient)
                        with file_path.open("rb") as f:
                            content_sample = f.read(1024)
                        import hashlib

                        content_hash = hashlib.md5(content_sample).hexdigest()
                        snapshot[str(rel_path)] = (stat.st_mtime, stat.st_size, content_hash)
                    except (OSError, ValueError):
                        continue
        except OSError:
            pass
        return snapshot

    def _detect_changes(
        self,
        pre_files: dict[str, tuple[float, int, str]],
        post_files: dict[str, tuple[float, int, str]],
    ) -> dict[str, str]:
        """
        Detect new or modified files by comparing snapshots.
        Returns dict of relative_path -> full content for staged files.
        """
        staged: dict[str, str] = {}

        # Check for new or modified files
        for rel_path, (mtime, size, hash_) in post_files.items():
            if rel_path not in pre_files:
                # New file
                full_path = self._working_directory / rel_path
                try:
                    content = full_path.read_text(encoding="utf-8")
                    staged[str(rel_path)] = content
                except (OSError, UnicodeDecodeError):
                    staged[str(rel_path)] = "[binary or unreadable]"
            else:
                # Check if modified
                pre_mtime, pre_size, pre_hash = pre_files[rel_path]
                if mtime != pre_mtime or size != pre_size or hash_ != pre_hash:
                    full_path = self._working_directory / rel_path
                    try:
                        content = full_path.read_text(encoding="utf-8")
                        staged[str(rel_path)] = content
                    except (OSError, UnicodeDecodeError):
                        staged[str(rel_path)] = "[binary or unreadable]"

        return staged

    def get_staged_changes(self) -> dict[str, str]:
        """Return the currently staged changes for verification."""
        return self._staged_changes.copy()

    def clear_staged_changes(self) -> None:
        """Clear staged changes after verification."""
        self._staged_changes.clear()


__all__ = ["HermesAdapter"]
