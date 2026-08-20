"""
Tests for Phase 4 M1 compaction domain models.

These tests cover the immutable ``CompactionItem`` and
``ConversationCompaction`` records and their structural (domain-level)
provenance validation. Database-level validation (message IDs actually
existing in SQLite) is intentionally out of scope for M1.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, date, datetime, time

import pytest

from friday.compaction.models import CompactionItem, ConversationCompaction

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def make_item(
    *,
    item_id: str = "item-1",
    content: str = "FRIDAY stores durable memory in memory.db.",
    source_message_ids: tuple[int, ...] = (10, 12, 18),
) -> CompactionItem:
    return CompactionItem(
        item_id=item_id,
        content=content,
        source_message_ids=source_message_ids,
    )


def make_compaction(
    *,
    compaction_id: str = "compaction-1",
    conversation_id: int = 7,
    first_message_id: int = 10,
    last_message_id: int = 20,
    created_at: datetime = NOW,
    compaction_version: int = 1,
    summary: str = "The conversation covered durable memory design.",
    facts: tuple[CompactionItem, ...] = (),
    decisions: tuple[CompactionItem, ...] = (),
    changes: tuple[CompactionItem, ...] = (),
    open_questions: tuple[CompactionItem, ...] = (),
) -> ConversationCompaction:
    return ConversationCompaction(
        compaction_id=compaction_id,
        conversation_id=conversation_id,
        first_message_id=first_message_id,
        last_message_id=last_message_id,
        created_at=created_at,
        compaction_version=compaction_version,
        summary=summary,
        facts=facts,
        decisions=decisions,
        changes=changes,
        open_questions=open_questions,
    )


def test_valid_compaction_item() -> None:
    item = make_item()
    assert item.item_id == "item-1"
    assert item.content == "FRIDAY stores durable memory in memory.db."
    assert item.source_message_ids == (10, 12, 18)


@pytest.mark.parametrize("content", ["", "   "])
def test_empty_item_content_rejected(content: str) -> None:
    with pytest.raises(ValueError, match="content cannot be empty"):
        make_item(content=content)


@pytest.mark.parametrize(
    "source_message_ids",
    [(), ("10",), (10.0,), (True,)],
)
def test_invalid_or_empty_source_message_ids_rejected(source_message_ids) -> None:
    with pytest.raises((TypeError, ValueError)):
        make_item(source_message_ids=source_message_ids)


@pytest.mark.parametrize("source_message_ids", [(0,), (-1,)])
def test_non_positive_source_message_ids_rejected(source_message_ids) -> None:
    with pytest.raises(ValueError, match="positive"):
        make_item(source_message_ids=source_message_ids)


@pytest.mark.parametrize("item_id", ["", "   "])
def test_empty_item_id_rejected(item_id: str) -> None:
    with pytest.raises(ValueError, match="item_id cannot be empty"):
        make_item(item_id=item_id)


def test_source_message_id_below_first_message_id_rejected() -> None:
    item = make_item(source_message_ids=(9, 12))
    with pytest.raises(ValueError, match="covered message range"):
        make_compaction(facts=(item,))


def test_source_message_id_above_last_message_id_rejected() -> None:
    item = make_item(source_message_ids=(21,))
    with pytest.raises(ValueError, match="covered message range"):
        make_compaction(decisions=(item,))


def test_valid_provenance_inside_covered_range_accepted() -> None:
    item = make_item(source_message_ids=(10, 12, 18))
    compaction = make_compaction(facts=(item,))
    assert compaction.facts == (item,)


def test_boundary_message_ids_are_valid_provenance() -> None:
    first_item = make_item(item_id="first", source_message_ids=(10,))
    last_item = make_item(item_id="last", source_message_ids=(20,))
    compaction = make_compaction(facts=(first_item, last_item))
    assert compaction.facts == (first_item, last_item)


@pytest.mark.parametrize(
    ("first", "last"),
    [(21, 20), (20, 19)],
)
def test_invalid_first_last_range_rejected(first: int, last: int) -> None:
    with pytest.raises(ValueError, match="first_message_id.*last_message_id"):
        make_compaction(first_message_id=first, last_message_id=last)


def test_valid_compaction_with_all_categories() -> None:
    compaction = make_compaction(
        summary="Designed the compaction subsystem.",
        facts=(
            make_item(item_id="f1", content="Fact one.", source_message_ids=(10,)),
            make_item(item_id="f2", content="Fact two.", source_message_ids=(12,)),
        ),
        decisions=(make_item(item_id="d1", content="Use SQLite.", source_message_ids=(14,)),),
        changes=(make_item(item_id="c1", content="Added compactions.db.", source_message_ids=(16,)),),
        open_questions=(make_item(item_id="q1", content="Async? Open.", source_message_ids=(18,)),),
    )
    assert len(compaction.facts) == 2
    assert len(compaction.decisions) == 1
    assert len(compaction.changes) == 1
    assert len(compaction.open_questions) == 1


def test_empty_categories_accepted_at_domain_level() -> None:
    compaction = make_compaction()
    assert compaction.facts == ()
    assert compaction.decisions == ()
    assert compaction.changes == ()
    assert compaction.open_questions == ()


@pytest.mark.parametrize(
    "category",
    ["facts", "decisions", "changes", "open_questions"],
)
def test_invalid_category_cannot_enter_structured_collections(category: str) -> None:
    with pytest.raises(TypeError, match="CompactionItem"):
        make_compaction(**{category: ("not a compaction item",)})


def test_no_generic_fifth_structured_category() -> None:
    field_names = {field.name for field in fields(ConversationCompaction)}
    assert "facts" in field_names
    assert "decisions" in field_names
    assert "changes" in field_names
    assert "open_questions" in field_names
    assert not {"items", "records", "knowledge"} & field_names


def test_immutability_frozen_behavior() -> None:
    item = make_item()
    compaction = make_compaction(facts=(item,))
    with pytest.raises(FrozenInstanceError):
        item.content = "mutated"
    with pytest.raises(FrozenInstanceError):
        compaction.summary = "mutated"


def test_stable_identity_remains_unchanged() -> None:
    item = make_item(item_id="stable-item")
    compaction = make_compaction(compaction_id="stable-compaction", facts=(item,))
    copied = replace(compaction, summary="Updated summary.")
    assert copied.compaction_id == "stable-compaction"
    assert copied.facts[0].item_id == "stable-item"


def test_duplicate_source_ids_deduplicated_deterministically() -> None:
    item = make_item(source_message_ids=(18, 10, 18, 12, 10))
    assert item.source_message_ids == (10, 12, 18)


def test_multiple_source_message_ids_accepted() -> None:
    item = make_item(source_message_ids=(10, 12, 15, 18, 20))
    compaction = make_compaction(facts=(item,))
    assert compaction.facts[0].source_message_ids == (10, 12, 15, 18, 20)


@pytest.mark.parametrize("conversation_id", [0, -1, "7", 7.0])
def test_invalid_conversation_id_rejected(conversation_id) -> None:
    with pytest.raises((TypeError, ValueError)):
        make_compaction(conversation_id=conversation_id)


@pytest.mark.parametrize("compaction_version", [0, -1, "1"])
def test_invalid_compaction_version_rejected(compaction_version) -> None:
    with pytest.raises((TypeError, ValueError)):
        make_compaction(compaction_version=compaction_version)


@pytest.mark.parametrize("compaction_id", ["", "   "])
def test_empty_compaction_id_rejected(compaction_id: str) -> None:
    with pytest.raises(ValueError, match="compaction_id cannot be empty"):
        make_compaction(compaction_id=compaction_id)


def test_naive_created_at_rejected() -> None:
    naive = datetime.combine(date(2026, 8, 15), time(12, 0, 0))
    with pytest.raises(ValueError, match="timezone-aware"):
        make_compaction(created_at=naive)


def test_created_at_round_trip_preserved() -> None:
    compaction = make_compaction(created_at=NOW)
    assert compaction.created_at == NOW


def test_required_fields_are_present() -> None:
    field_names = {field.name for field in fields(ConversationCompaction)}
    for required in (
        "compaction_id",
        "conversation_id",
        "first_message_id",
        "last_message_id",
        "created_at",
        "compaction_version",
        "summary",
        "facts",
        "decisions",
        "changes",
        "open_questions",
    ):
        assert required in field_names


def test_next_start_not_stored_in_model() -> None:
    field_names = {field.name for field in fields(ConversationCompaction)}
    assert "next_start" not in field_names


def test_summary_is_plain_string() -> None:
    compaction = make_compaction(summary="A narrative summary.")
    assert isinstance(compaction.summary, str)