"""
Unit tests for TaskContract domain model.
"""

import pytest

from friday.orchestration.models import TaskCapability, TaskContract, VerificationResult


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
