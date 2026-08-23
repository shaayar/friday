"""Tests for Phase 4 M5 deterministic compaction trigger (should_compact)."""

from __future__ import annotations

import inspect

import pytest

from friday.compaction.trigger import should_compact


def compact(
    *,
    count: int = 0,
    units: int = 0,
    force: bool = False,
    message: int = 20,
    size: int | None = 4000,
) -> bool:
    return should_compact(
        count, units, force=force, message_threshold=message, unit_threshold=size
    )


class TestMessageTrigger:
    def test_below_threshold_no_compaction(self) -> None:
        assert compact(count=19, message=20) is False

    def test_at_threshold_compacts(self) -> None:
        assert compact(count=20, message=20) is True

    def test_above_threshold_compacts(self) -> None:
        assert compact(count=21, message=20) is True

    def test_zero_count_no_compaction(self) -> None:
        assert compact(count=0) is False

    def test_size_trigger_disabled_uses_message_only(self) -> None:
        assert compact(count=5, units=10_000, size=None) is False
        assert compact(count=20, units=10_000, size=None) is True


class TestSizeTrigger:
    def test_below_size_threshold_no_compaction(self) -> None:
        assert compact(count=3, units=3_999, size=4000) is False

    def test_at_size_threshold_compacts(self) -> None:
        assert compact(count=3, units=4_000, size=4000) is True

    def test_above_size_threshold_compacts(self) -> None:
        assert compact(count=3, units=4_001, size=4000) is True

    def test_size_fires_below_message_threshold(self) -> None:
        assert compact(count=5, units=10_000, message=20, size=4000) is True


class TestForce:
    def test_force_compacts_below_threshold(self) -> None:
        assert compact(count=1, units=0, force=True, message=20, size=4000) is True

    def test_force_with_no_uncompacted_messages_is_noop(self) -> None:
        assert compact(count=0, units=0, force=True, message=20, size=4000) is False

    def test_force_ignores_size_threshold(self) -> None:
        assert compact(count=2, units=0, force=True, message=20, size=1) is True


class TestValidation:
    @pytest.mark.parametrize("count", [-1, 1.5, "10", True])
    def test_invalid_message_count_rejected(self, count) -> None:
        with pytest.raises((TypeError, ValueError)):
            should_compact(
                count, 0, force=False, message_threshold=20, unit_threshold=4000
            )

    @pytest.mark.parametrize("units", [-1, 1.5, "10", True])
    def test_invalid_units_rejected(self, units) -> None:
        with pytest.raises((TypeError, ValueError)):
            should_compact(
                0, units, force=False, message_threshold=20, unit_threshold=4000
            )

    @pytest.mark.parametrize("threshold", [0, -5, 1.5, "20", True])
    def test_invalid_message_threshold_rejected(self, threshold) -> None:
        with pytest.raises((TypeError, ValueError)):
            should_compact(
                5, 0, force=False, message_threshold=threshold, unit_threshold=None
            )

    @pytest.mark.parametrize("size", [0, -5, 1.5, "4000", True])
    def test_invalid_size_threshold_rejected(self, size) -> None:
        with pytest.raises((TypeError, ValueError)):
            should_compact(5, 0, force=False, message_threshold=20, unit_threshold=size)

    def test_non_bool_force_rejected(self) -> None:
        with pytest.raises(TypeError):
            should_compact(5, 0, force="yes", message_threshold=20, unit_threshold=None)


class TestPurity:
    @staticmethod
    def _import_lines() -> list[str]:
        source = inspect.getsource(inspect.getmodule(should_compact))
        return [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
            and "__future__" not in line
        ]

    def test_no_llm_import(self) -> None:
        assert not any(
            line.startswith(("import ", "from ")) for line in self._import_lines()
        )

    def test_no_storage_import(self) -> None:
        assert not any(
            "sqlite" in line or "store" in line for line in self._import_lines()
        )

    def test_no_context_import(self) -> None:
        assert not any(
            "context" in line or "estimate_units" in line
            for line in self._import_lines()
        )
