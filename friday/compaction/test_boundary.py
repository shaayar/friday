"""
Tests for Phase 4 M2 compaction boundary computation and window selection.

Pure in-memory deterministic logic. No database access.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest

from friday.compaction.boundary import next_compaction_start, select_compaction_window
from friday.compaction.models import ConversationCompaction

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Msg:
    id: int
    content: str = ""


def make_compaction(
    *,
    compaction_id: str,
    first_message_id: int,
    last_message_id: int,
    conversation_id: int = 1,
) -> ConversationCompaction:
    return ConversationCompaction(
        compaction_id=compaction_id,
        conversation_id=conversation_id,
        first_message_id=first_message_id,
        last_message_id=last_message_id,
        created_at=NOW,
    )


def messages(*ids: int) -> tuple[Msg, ...]:
    return tuple(Msg(message_id) for message_id in ids)


# ---------------------------------------------------------------------------
# next_compaction_start
# ---------------------------------------------------------------------------


def test_no_compactions_returns_none() -> None:
    assert next_compaction_start([]) is None


def test_single_compaction_boundary() -> None:
    compaction = make_compaction(compaction_id="c1", first_message_id=1, last_message_id=20)
    assert next_compaction_start([compaction]) == 21


def test_multiple_compactions_boundary() -> None:
    compactions = [
        make_compaction(compaction_id="c1", first_message_id=1, last_message_id=20),
        make_compaction(compaction_id="c2", first_message_id=21, last_message_id=40),
    ]
    assert next_compaction_start(compactions) == 41


def test_out_of_order_compactions_uses_greatest_boundary() -> None:
    compactions = [
        make_compaction(compaction_id="c2", first_message_id=21, last_message_id=40),
        make_compaction(compaction_id="c1", first_message_id=1, last_message_id=20),
    ]
    assert next_compaction_start(compactions) == 41


def test_duplicate_compactions_tolerated() -> None:
    compaction = make_compaction(compaction_id="c1", first_message_id=1, last_message_id=20)
    assert next_compaction_start([compaction, compaction]) == 21


def test_overlapping_compactions_derive_boundary_conservatively() -> None:
    compactions = [
        make_compaction(compaction_id="c1", first_message_id=1, last_message_id=20),
        make_compaction(compaction_id="c2", first_message_id=10, last_message_id=25),
    ]
    assert next_compaction_start(compactions) == 26


def test_empty_iterable_is_equivalent_to_no_compactions() -> None:
    assert next_compaction_start(()) is None


def test_non_compaction_input_rejected() -> None:
    with pytest.raises(TypeError, match="ConversationCompaction"):
        next_compaction_start(["not-a-compaction"])  # type: ignore[list-item]


def test_invalid_reversed_range_rejected_by_m1_model() -> None:
    with pytest.raises(ValueError, match="first_message_id must be <= last_message_id"):
        make_compaction(compaction_id="bad", first_message_id=30, last_message_id=10)


# ---------------------------------------------------------------------------
# select_compaction_window
# ---------------------------------------------------------------------------


def test_no_boundary_selects_from_first_available_message() -> None:
    selected = select_compaction_window(messages(1, 2, 3, 4, 5), next_start=None, max_window=20)
    assert [msg.id for msg in selected] == [1, 2, 3, 4, 5]


def test_window_starts_at_boundary() -> None:
    selected = select_compaction_window(messages(1, 2, 3, 4, 5), next_start=3, max_window=20)
    assert [msg.id for msg in selected] == [3, 4, 5]


def test_messages_before_boundary_ignored() -> None:
    selected = select_compaction_window(messages(1, 2, 3, 4, 5), next_start=4, max_window=20)
    assert [msg.id for msg in selected] == [4, 5]


def test_exactly_max_window_messages_all_selected() -> None:
    selected = select_compaction_window(messages(1, 2, 3), next_start=None, max_window=3)
    assert [msg.id for msg in selected] == [1, 2, 3]


def test_more_than_max_window_only_max_selected() -> None:
    selected = select_compaction_window(messages(1, 2, 3, 4, 5), next_start=None, max_window=3)
    assert [msg.id for msg in selected] == [1, 2, 3]


def test_fewer_than_max_window_all_remaining_selected() -> None:
    selected = select_compaction_window(messages(1, 2, 3), next_start=None, max_window=10)
    assert [msg.id for msg in selected] == [1, 2, 3]


def test_no_messages_after_boundary_returns_empty() -> None:
    selected = select_compaction_window(messages(1, 2, 3), next_start=4, max_window=10)
    assert selected == ()


def test_empty_message_sequence_returns_empty() -> None:
    assert select_compaction_window((), next_start=None, max_window=10) == ()


def test_input_ordering_preserved() -> None:
    selected = select_compaction_window(messages(1, 2, 3, 4, 5), next_start=2, max_window=3)
    assert [msg.id for msg in selected] == [2, 3, 4]


def test_input_sequence_not_mutated() -> None:
    original = list(messages(1, 2, 3, 4, 5))
    snapshot = list(original)
    select_compaction_window(original, next_start=2, max_window=3)
    assert original == snapshot


def test_gap_in_message_ids_respected() -> None:
    msgs = messages(1, 3, 5, 7)
    selected = select_compaction_window(msgs, next_start=4, max_window=10)
    assert [msg.id for msg in selected] == [5, 7]


@pytest.mark.parametrize("max_window", [0, -1, 1.5, "10"])
def test_invalid_max_window_rejected(max_window) -> None:
    with pytest.raises((TypeError, ValueError)):
        select_compaction_window(messages(1, 2, 3), next_start=None, max_window=max_window)


@pytest.mark.parametrize("next_start", [0, -1, 1.5, "3"])
def test_invalid_boundary_rejected(next_start) -> None:
    with pytest.raises((TypeError, ValueError)):
        select_compaction_window(messages(1, 2, 3), next_start=next_start, max_window=5)


def test_boundary_at_first_message() -> None:
    selected = select_compaction_window(messages(1, 2, 3), next_start=1, max_window=10)
    assert [msg.id for msg in selected] == [1, 2, 3]


def test_boundary_immediately_after_final_message() -> None:
    selected = select_compaction_window(messages(1, 2, 3), next_start=4, max_window=10)
    assert selected == ()


def test_original_message_objects_returned() -> None:
    original = messages(1, 2, 3)
    selected = select_compaction_window(original, next_start=1, max_window=10)
    assert selected == original
    assert all(a is b for a, b in zip(selected, original))


# ---------------------------------------------------------------------------
# Incremental property
# ---------------------------------------------------------------------------


def test_incremental_advance_monotonic() -> None:
    compactions = [
        make_compaction(compaction_id="c1", first_message_id=1, last_message_id=20),
        make_compaction(compaction_id="c2", first_message_id=21, last_message_id=40),
    ]
    boundary = next_compaction_start(compactions)
    assert boundary == 41
    selected = select_compaction_window(messages(*range(1, 61)), next_start=boundary, max_window=20)
    assert [msg.id for msg in selected] == list(range(41, 61))


def test_next_selection_never_includes_covered_messages() -> None:
    compacted = make_compaction(compaction_id="c1", first_message_id=1, last_message_id=20)
    boundary = next_compaction_start([compacted])
    selected = select_compaction_window(messages(*range(1, 50)), next_start=boundary, max_window=20)
    assert min(msg.id for msg in selected) > 20


def test_next_start_derived_not_stored() -> None:
    compaction = make_compaction(compaction_id="c1", first_message_id=1, last_message_id=20)
    assert not hasattr(compaction, "next_start")


def test_replace_preserves_identity_and_boundary_unchanged() -> None:
    compaction = make_compaction(compaction_id="c1", first_message_id=1, last_message_id=20)
    updated = replace(compaction, summary="Changed.")
    assert next_compaction_start([updated]) == 21
    assert updated.compaction_id == "c1"


def test_boundary_with_non_contiguous_compactions() -> None:
    compactions = [
        make_compaction(compaction_id="c1", first_message_id=1, last_message_id=20),
        make_compaction(compaction_id="c2", first_message_id=50, last_message_id=70),
    ]
    boundary = next_compaction_start(compactions)
    assert boundary == 71
    selected = select_compaction_window(messages(*range(1, 81)), next_start=boundary, max_window=20)
    assert [msg.id for msg in selected] == list(range(71, 81))