import pytest

from friday.orchestration.models import (
    AgentManifest,
    TaskCapability,
    TaskContract,
    VerificationResult,
    WorkerResult,
)
from friday.orchestration.registry import AgentRegistry


class TestTaskCapability:
    def test_capability_values(self):
        assert TaskCapability.READ == "read"
        assert TaskCapability.WRITE == "write"
        assert TaskCapability.EXECUTE == "execute"
        assert TaskCapability.NETWORK == "network"


class TestVerificationResult:
    def test_verification_values(self):
        assert VerificationResult.PASS == "pass"
        assert VerificationResult.FAIL == "fail"
        assert VerificationResult.NEEDS_REVIEW == "needs_review"


class TestTaskContract:
    def test_minimal_valid_contract(self):
        contract = TaskContract(
            task_id="task-1",
            objective="Test objective",
            acceptance_criteria=("criterion 1",),
        )
        assert contract.task_id == "task-1"
        assert contract.objective == "Test objective"
        assert contract.acceptance_criteria == ("criterion 1",)
        assert contract.inputs == ()
        assert contract.allowed_capabilities == ()
        assert contract.constraints == ()
        assert contract.timeout == 300.0
        assert contract.project_id is None

    def test_full_contract(self):
        contract = TaskContract(
            task_id="task-2",
            objective="Implement feature",
            acceptance_criteria=("test passes", "lint clean"),
            inputs=("repo path", "context"),
            allowed_capabilities=(TaskCapability.READ, TaskCapability.WRITE),
            constraints=("no external deps",),
            timeout=60.0,
            project_id="proj-123",
        )
        assert contract.task_id == "task-2"
        assert contract.objective == "Implement feature"
        assert contract.acceptance_criteria == ("test passes", "lint clean")
        assert contract.inputs == ("repo path", "context")
        assert contract.allowed_capabilities == (
            TaskCapability.READ,
            TaskCapability.WRITE,
        )
        assert contract.constraints == ("no external deps",)
        assert contract.timeout == 60.0
        assert contract.project_id == "proj-123"

    def test_task_id_whitespace_stripped(self):
        contract = TaskContract(
            task_id="  task-1  ",
            objective="Test",
            acceptance_criteria=("c",),
        )
        assert contract.task_id == "task-1"

    def test_objective_whitespace_stripped(self):
        contract = TaskContract(
            task_id="task-1",
            objective="  Test objective  ",
            acceptance_criteria=("c",),
        )
        assert contract.objective == "Test objective"

    def test_empty_task_id_rejected(self):
        with pytest.raises(ValueError, match="task_id cannot be empty"):
            TaskContract(
                task_id="",
                objective="Test",
                acceptance_criteria=("c",),
            )

    def test_whitespace_only_task_id_rejected(self):
        with pytest.raises(ValueError, match="task_id cannot be empty"):
            TaskContract(
                task_id="   ",
                objective="Test",
                acceptance_criteria=("c",),
            )

    def test_empty_objective_rejected(self):
        with pytest.raises(ValueError, match="objective cannot be empty"):
            TaskContract(
                task_id="task-1",
                objective="",
                acceptance_criteria=("c",),
            )

    def test_empty_acceptance_criteria_rejected(self):
        with pytest.raises(ValueError, match="acceptance_criteria cannot be empty"):
            TaskContract(
                task_id="task-1",
                objective="Test",
                acceptance_criteria=(),
            )

    def test_whitespace_acceptance_criteria_filtered(self):
        contract = TaskContract(
            task_id="task-1",
            objective="Test",
            acceptance_criteria=("  ", "valid", "", "  also valid  "),
        )
        assert contract.acceptance_criteria == ("valid", "also valid")

    def test_inputs_filtered_and_stripped(self):
        contract = TaskContract(
            task_id="task-1",
            objective="Test",
            acceptance_criteria=("c",),
            inputs=("  input1  ", "", "input2", "  "),
        )
        assert contract.inputs == ("input1", "input2")

    def test_allowed_capabilities_validated(self):
        contract = TaskContract(
            task_id="task-1",
            objective="Test",
            acceptance_criteria=("c",),
            allowed_capabilities=(TaskCapability.READ, TaskCapability.WRITE),
        )
        assert contract.allowed_capabilities == (
            TaskCapability.READ,
            TaskCapability.WRITE,
        )

    def test_invalid_capability_rejected(self):
        with pytest.raises(TypeError, match="must be TaskCapability"):
            TaskContract(
                task_id="task-1",
                objective="Test",
                acceptance_criteria=("c",),
                allowed_capabilities=(
                    TaskCapability.READ,
                    "write",
                ),  # mix of enum and string
            )

    def test_constraints_filtered_and_stripped(self):
        contract = TaskContract(
            task_id="task-1",
            objective="Test",
            acceptance_criteria=("c",),
            constraints=("  constraint1  ", "", "constraint2", "  "),
        )
        assert contract.constraints == ("constraint1", "constraint2")

    def test_timeout_validated(self):
        contract = TaskContract(
            task_id="task-1",
            objective="Test",
            acceptance_criteria=("c",),
            timeout=45.5,
        )
        assert contract.timeout == 45.5

    def test_timeout_int_accepted(self):
        contract = TaskContract(
            task_id="task-1",
            objective="Test",
            acceptance_criteria=("c",),
            timeout=60,
        )
        assert contract.timeout == 60.0

    def test_zero_timeout_rejected(self):
        with pytest.raises(ValueError, match="timeout must be positive"):
            TaskContract(
                task_id="task-1",
                objective="Test",
                acceptance_criteria=("c",),
                timeout=0,
            )

    def test_negative_timeout_rejected(self):
        with pytest.raises(ValueError, match="timeout must be positive"):
            TaskContract(
                task_id="task-1",
                objective="Test",
                acceptance_criteria=("c",),
                timeout=-10,
            )

    def test_project_id_stripped(self):
        contract = TaskContract(
            task_id="task-1",
            objective="Test",
            acceptance_criteria=("c",),
            project_id="  proj-123  ",
        )
        assert contract.project_id == "proj-123"

    def test_empty_project_id_rejected(self):
        with pytest.raises(ValueError, match="project_id cannot be empty string"):
            TaskContract(
                task_id="task-1",
                objective="Test",
                acceptance_criteria=("c",),
                project_id="   ",
            )

    def test_created_at_timezone_aware(self):
        contract = TaskContract(
            task_id="task-1",
            objective="Test",
            acceptance_criteria=("c",),
        )
        assert contract.created_at.tzinfo is not None
        assert contract.created_at.utcoffset() is not None

    def test_immutable(self):
        contract = TaskContract(
            task_id="task-1",
            objective="Test",
            acceptance_criteria=("c",),
        )
        with pytest.raises(AttributeError):  # frozen dataclass
            contract.task_id = "new-id"

    def test_default_timeout_300(self):
        contract = TaskContract(
            task_id="task-1",
            objective="Test",
            acceptance_criteria=("c",),
        )
        assert contract.timeout == 300.0


class TestAgentManifest:
    def test_minimal_valid_manifest(self):
        manifest = AgentManifest(
            agent_id="opencode",
            name="OpenCode",
            description="Coding agent",
            capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
            input_contract="TaskContract",
            output_contract="WorkerResult",
            execution_protocol="subprocess",
        )
        assert manifest.agent_id == "opencode"
        assert manifest.name == "OpenCode"
        assert manifest.description == "Coding agent"
        assert manifest.capabilities == (
            TaskCapability.READ,
            TaskCapability.WRITE,
            TaskCapability.EXECUTE,
        )
        assert manifest.input_contract == "TaskContract"
        assert manifest.output_contract == "WorkerResult"
        assert manifest.execution_protocol == "subprocess"

    def test_empty_agent_id_rejected(self):
        with pytest.raises(ValueError, match="agent_id cannot be empty"):
            AgentManifest(
                agent_id="",
                name="Test",
                description="Test",
                capabilities=(TaskCapability.READ,),
                input_contract="in",
                output_contract="out",
                execution_protocol="proto",
            )

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError, match="name cannot be empty"):
            AgentManifest(
                agent_id="test",
                name="",
                description="Test",
                capabilities=(TaskCapability.READ,),
                input_contract="in",
                output_contract="out",
                execution_protocol="proto",
            )

    def test_empty_description_rejected(self):
        with pytest.raises(ValueError, match="description cannot be empty"):
            AgentManifest(
                agent_id="test",
                name="Test",
                description="",
                capabilities=(TaskCapability.READ,),
                input_contract="in",
                output_contract="out",
                execution_protocol="proto",
            )

    def test_empty_capabilities_rejected(self):
        with pytest.raises(ValueError, match="capabilities cannot be empty"):
            AgentManifest(
                agent_id="test",
                name="Test",
                description="Test",
                capabilities=(),
                input_contract="in",
                output_contract="out",
                execution_protocol="proto",
            )

    def test_invalid_capability_rejected(self):
        with pytest.raises(TypeError, match="must be TaskCapability"):
            AgentManifest(
                agent_id="test",
                name="Test",
                description="Test",
                capabilities=(TaskCapability.READ, "write"),
                input_contract="in",
                output_contract="out",
                execution_protocol="proto",
            )

    def test_empty_input_contract_rejected(self):
        with pytest.raises(ValueError, match="input_contract cannot be empty"):
            AgentManifest(
                agent_id="test",
                name="Test",
                description="Test",
                capabilities=(TaskCapability.READ,),
                input_contract="",
                output_contract="out",
                execution_protocol="proto",
            )

    def test_empty_output_contract_rejected(self):
        with pytest.raises(ValueError, match="output_contract cannot be empty"):
            AgentManifest(
                agent_id="test",
                name="Test",
                description="Test",
                capabilities=(TaskCapability.READ,),
                input_contract="in",
                output_contract="",
                execution_protocol="proto",
            )

    def test_empty_execution_protocol_rejected(self):
        with pytest.raises(ValueError, match="execution_protocol cannot be empty"):
            AgentManifest(
                agent_id="test",
                name="Test",
                description="Test",
                capabilities=(TaskCapability.READ,),
                input_contract="in",
                output_contract="out",
                execution_protocol="",
            )

    def test_whitespace_stripped(self):
        manifest = AgentManifest(
            agent_id="  test  ",
            name="  Test  ",
            description="  Test desc  ",
            capabilities=(TaskCapability.READ,),
            input_contract="  in  ",
            output_contract="  out  ",
            execution_protocol="  proto  ",
        )
        assert manifest.agent_id == "test"
        assert manifest.name == "Test"
        assert manifest.description == "Test desc"
        assert manifest.input_contract == "in"
        assert manifest.output_contract == "out"
        assert manifest.execution_protocol == "proto"


class TestWorkerResult:
    def test_minimal_valid_result(self):
        result = WorkerResult(
            task_id="task-1",
            agent_id="opencode",
            status="completed",
            output="Success",
        )
        assert result.task_id == "task-1"
        assert result.agent_id == "opencode"
        assert result.status == "completed"
        assert result.output == "Success"
        assert result.artifacts == ()
        assert result.error is None

    def test_full_result(self):
        result = WorkerResult(
            task_id="task-1",
            agent_id="opencode",
            status="completed",
            output="Done",
            artifacts=("file1.py", "file2.py"),
            error=None,
        )
        assert result.artifacts == ("file1.py", "file2.py")

    def test_artifacts_filtered(self):
        result = WorkerResult(
            task_id="task-1",
            agent_id="opencode",
            status="completed",
            output="Done",
            artifacts=("  file1.py  ", "", "file2.py", "  "),
        )
        assert result.artifacts == ("file1.py", "file2.py")

    def test_error_none_when_empty(self):
        result = WorkerResult(
            task_id="task-1",
            agent_id="opencode",
            status="completed",
            output="Done",
            error="  ",
        )
        assert result.error is None


class TestAgentRegistry:
    def test_register_and_get(self):
        registry = AgentRegistry()
        manifest = AgentManifest(
            agent_id="opencode",
            name="OpenCode",
            description="Coding agent",
            capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
            input_contract="TaskContract",
            output_contract="WorkerResult",
            execution_protocol="subprocess",
        )

        class MockAdapter:
            def capabilities(self):
                return (
                    TaskCapability.READ,
                    TaskCapability.WRITE,
                    TaskCapability.EXECUTE,
                )

            async def execute(self, task):
                return WorkerResult(
                    task_id=task.task_id,
                    agent_id="opencode",
                    status="completed",
                    output="Done",
                )

        registry.register(manifest, MockAdapter())

        retrieved = registry.get("opencode")
        assert retrieved is not None
        assert retrieved.agent_id == "opencode"
        assert retrieved.name == "OpenCode"

    def test_duplicate_registration_rejected(self):
        registry = AgentRegistry()
        manifest = AgentManifest(
            agent_id="opencode",
            name="OpenCode",
            description="Coding agent",
            capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
            input_contract="TaskContract",
            output_contract="WorkerResult",
            execution_protocol="subprocess",
        )

        class MockAdapter:
            def capabilities(self):
                return (
                    TaskCapability.READ,
                    TaskCapability.WRITE,
                    TaskCapability.EXECUTE,
                )

            async def execute(self, task):
                return WorkerResult(
                    task_id=task.task_id,
                    agent_id="opencode",
                    status="completed",
                    output="Done",
                )

        registry.register(manifest, MockAdapter())

        with pytest.raises(ValueError, match="already registered"):
            registry.register(manifest, MockAdapter())

    def test_unknown_agent_returns_none(self):
        registry = AgentRegistry()
        assert registry.get("unknown") is None
        assert registry.get_adapter("unknown") is None

    def test_capability_matching_exact(self):
        registry = AgentRegistry()

        manifest1 = AgentManifest(
            agent_id="opencode",
            name="OpenCode",
            description="Coding agent",
            capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
            input_contract="TaskContract",
            output_contract="WorkerResult",
            execution_protocol="subprocess",
        )

        class MockAdapter1:
            def capabilities(self):
                return (
                    TaskCapability.READ,
                    TaskCapability.WRITE,
                    TaskCapability.EXECUTE,
                )

            async def execute(self, task):
                return WorkerResult(
                    task_id=task.task_id,
                    agent_id="opencode",
                    status="completed",
                    output="Done",
                )

        registry.register(manifest1, MockAdapter1())

        selected = registry.select_by_capabilities(
            (TaskCapability.READ, TaskCapability.WRITE)
        )
        assert selected is not None
        assert selected.agent_id == "opencode"

    def test_capability_matching_no_match(self):
        registry = AgentRegistry()

        manifest = AgentManifest(
            agent_id="opencode",
            name="OpenCode",
            description="Coding agent",
            capabilities=(TaskCapability.READ, TaskCapability.WRITE),
            input_contract="TaskContract",
            output_contract="WorkerResult",
            execution_protocol="subprocess",
        )

        class MockAdapter:
            def capabilities(self):
                return (TaskCapability.READ, TaskCapability.WRITE)

            async def execute(self, task):
                return WorkerResult(
                    task_id=task.task_id,
                    agent_id="opencode",
                    status="completed",
                    output="Done",
                )

        registry.register(manifest, MockAdapter())

        # Requires EXECUTE which opencode doesn't have
        selected = registry.select_by_capabilities((TaskCapability.EXECUTE,))
        assert selected is None

    def test_capability_matching_requires_all(self):
        registry = AgentRegistry()

        manifest = AgentManifest(
            agent_id="opencode",
            name="OpenCode",
            description="Coding agent",
            capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
            input_contract="TaskContract",
            output_contract="WorkerResult",
            execution_protocol="subprocess",
        )

        class MockAdapter:
            def capabilities(self):
                return (
                    TaskCapability.READ,
                    TaskCapability.WRITE,
                    TaskCapability.EXECUTE,
                )

            async def execute(self, task):
                return WorkerResult(
                    task_id=task.task_id,
                    agent_id="opencode",
                    status="completed",
                    output="Done",
                )

        registry.register(manifest, MockAdapter())

        # Requires all three
        selected = registry.select_by_capabilities(
            (TaskCapability.READ, TaskCapability.WRITE, TaskCapability.EXECUTE)
        )
        assert selected is not None
        assert selected.agent_id == "opencode"

        # Requires NETWORK which opencode doesn't have
        selected = registry.select_by_capabilities(
            (
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
                TaskCapability.NETWORK,
            )
        )
        assert selected is None

    def test_deterministic_selection_fewest_capabilities(self):
        registry = AgentRegistry()

        manifest1 = AgentManifest(
            agent_id="agent-a",
            name="Agent A",
            description="General agent",
            capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
                TaskCapability.NETWORK,
            ),
            input_contract="TaskContract",
            output_contract="WorkerResult",
            execution_protocol="subprocess",
        )

        manifest2 = AgentManifest(
            agent_id="agent-b",
            name="Agent B",
            description="Specialized agent",
            capabilities=(
                TaskCapability.READ,
                TaskCapability.WRITE,
                TaskCapability.EXECUTE,
            ),
            input_contract="TaskContract",
            output_contract="WorkerResult",
            execution_protocol="subprocess",
        )

        class MockAdapter:
            def capabilities(self):
                return (
                    TaskCapability.READ,
                    TaskCapability.WRITE,
                    TaskCapability.EXECUTE,
                )

            async def execute(self, task):
                return WorkerResult(
                    task_id=task.task_id,
                    agent_id="agent-b",
                    status="completed",
                    output="Done",
                )

        class MockAdapter1:
            def capabilities(self):
                return (
                    TaskCapability.READ,
                    TaskCapability.WRITE,
                    TaskCapability.EXECUTE,
                    TaskCapability.NETWORK,
                )

            async def execute(self, task):
                return WorkerResult(
                    task_id=task.task_id,
                    agent_id="agent-a",
                    status="completed",
                    output="Done",
                )

        registry.register(manifest1, MockAdapter1())
        registry.register(manifest2, MockAdapter())

        # Both have READ, WRITE, EXECUTE - agent-b has fewer capabilities
        selected = registry.select_by_capabilities(
            (TaskCapability.READ, TaskCapability.WRITE, TaskCapability.EXECUTE)
        )
        assert selected.agent_id == "agent-b"

    def test_deterministic_selection_tiebreak_by_id(self):
        registry = AgentRegistry()

        manifest1 = AgentManifest(
            agent_id="aaa-agent",
            name="Agent AAA",
            description="Agent AAA",
            capabilities=(TaskCapability.READ, TaskCapability.WRITE),
            input_contract="TaskContract",
            output_contract="WorkerResult",
            execution_protocol="subprocess",
        )

        manifest2 = AgentManifest(
            agent_id="zzz-agent",
            name="Agent ZZZ",
            description="Agent ZZZ",
            capabilities=(TaskCapability.READ, TaskCapability.WRITE),
            input_contract="TaskContract",
            output_contract="WorkerResult",
            execution_protocol="subprocess",
        )

        class MockAdapter:
            def capabilities(self):
                return (TaskCapability.READ, TaskCapability.WRITE)

            async def execute(self, task):
                return WorkerResult(
                    task_id=task.task_id, agent_id="", status="completed", output="Done"
                )

        registry.register(manifest1, MockAdapter())
        registry.register(manifest2, MockAdapter())

        # Both have same capabilities - tiebreak by agent_id (lexicographically)
        selected = registry.select_by_capabilities(
            (TaskCapability.READ, TaskCapability.WRITE)
        )
        assert selected.agent_id == "aaa-agent"

    def test_empty_required_capabilities_returns_none(self):
        registry = AgentRegistry()
        selected = registry.select_by_capabilities(())
        assert selected is None

    def test_list_agents_deterministic_order(self):
        registry = AgentRegistry()

        for agent_id in ["z-agent", "a-agent", "m-agent"]:
            manifest = AgentManifest(
                agent_id=agent_id,
                name=f"Agent {agent_id}",
                description=f"Description {agent_id}",
                capabilities=(TaskCapability.READ,),
                input_contract="TaskContract",
                output_contract="WorkerResult",
                execution_protocol="subprocess",
            )

            class MockAdapter:
                def capabilities(self):
                    return (TaskCapability.READ,)

                async def execute(self, task, current_agent_id=agent_id):
                    return WorkerResult(
                        task_id=task.task_id,
                        agent_id=current_agent_id,
                        status="completed",
                        output="Done",
                    )

            registry.register(manifest, MockAdapter())

        agents = registry.list_agents()
        assert len(agents) == 3
        assert [a.agent_id for a in agents] == ["a-agent", "m-agent", "z-agent"]

    def test_registry_isolation(self):
        registry1 = AgentRegistry()
        registry2 = AgentRegistry()

        manifest = AgentManifest(
            agent_id="opencode",
            name="OpenCode",
            description="Coding agent",
            capabilities=(TaskCapability.READ, TaskCapability.WRITE),
            input_contract="TaskContract",
            output_contract="WorkerResult",
            execution_protocol="subprocess",
        )

        class MockAdapter:
            def capabilities(self):
                return (TaskCapability.READ, TaskCapability.WRITE)

            async def execute(self, task):
                return WorkerResult(
                    task_id=task.task_id,
                    agent_id="opencode",
                    status="completed",
                    output="Done",
                )

        registry1.register(manifest, MockAdapter())
        assert "opencode" in registry1
        assert "opencode" not in registry2

    def test_unregister(self):
        registry = AgentRegistry()

        manifest = AgentManifest(
            agent_id="opencode",
            name="OpenCode",
            description="Coding agent",
            capabilities=(TaskCapability.READ, TaskCapability.WRITE),
            input_contract="TaskContract",
            output_contract="WorkerResult",
            execution_protocol="subprocess",
        )

        class MockAdapter:
            def capabilities(self):
                return (TaskCapability.READ, TaskCapability.WRITE)

            async def execute(self, task):
                return WorkerResult(
                    task_id=task.task_id,
                    agent_id="opencode",
                    status="completed",
                    output="Done",
                )

        registry.register(manifest, MockAdapter())
        assert registry.unregister("opencode") is True
        assert registry.get("opencode") is None
        assert "opencode" not in registry

    def test_unregister_nonexistent(self):
        registry = AgentRegistry()
        assert registry.unregister("nonexistent") is False

    def test_clear(self):
        registry = AgentRegistry()

        manifest = AgentManifest(
            agent_id="opencode",
            name="OpenCode",
            description="Coding agent",
            capabilities=(TaskCapability.READ, TaskCapability.WRITE),
            input_contract="TaskContract",
            output_contract="WorkerResult",
            execution_protocol="subprocess",
        )

        class MockAdapter:
            def capabilities(self):
                return (TaskCapability.READ, TaskCapability.WRITE)

            async def execute(self, task):
                return WorkerResult(
                    task_id=task.task_id,
                    agent_id="opencode",
                    status="completed",
                    output="Done",
                )

        registry.register(manifest, MockAdapter())
        registry.clear()
        assert len(registry) == 0
        assert "opencode" not in registry

    def test_adapter_capabilities_must_match_manifest(self):
        registry = AgentRegistry()

        manifest = AgentManifest(
            agent_id="opencode",
            name="OpenCode",
            description="Coding agent",
            capabilities=(TaskCapability.READ, TaskCapability.WRITE),
            input_contract="TaskContract",
            output_contract="WorkerResult",
            execution_protocol="subprocess",
        )

        class MismatchedAdapter:
            def capabilities(self):
                return (
                    TaskCapability.READ,
                    TaskCapability.WRITE,
                    TaskCapability.EXECUTE,
                )  # Extra capability

            async def execute(self, task):
                return WorkerResult(
                    task_id=task.task_id,
                    agent_id="opencode",
                    status="completed",
                    output="Done",
                )

        with pytest.raises(ValueError, match="do not match"):
            registry.register(manifest, MismatchedAdapter())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
