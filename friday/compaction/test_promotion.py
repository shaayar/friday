"""
Tests for Phase 4 M6.1 promotion-ledger domain models (ADR-025).

Covers the immutable ``CompactionPromotion`` record, its validation rules,
and the PENDING/PROMOTED/REJECTED lifecycle. Storage, memory-pipeline
integration, and orchestration are intentionally out of scope.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, date, datetime, time

import pytest

from friday.compaction.promotion import (
    CompactionItemCategory,
    CompactionPromotion,
    PromotionResolutionKind,
    PromotionStatus,
)

NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 1, 15, 12, 30, 0, tzinfo=UTC)
CATEGORIES = tuple(CompactionItemCategory)


def make_pending(
    *,
    item_id: str = "item-1",
    compaction_id: str = "compaction-1",
    category: CompactionItemCategory = CompactionItemCategory.FACTS,
    created_at: datetime = NOW,
) -> CompactionPromotion:
    return CompactionPromotion.pending(
        item_id=item_id,
        compaction_id=compaction_id,
        category=category,
        created_at=created_at,
    )


class TestConstruction:
    def test_valid_pending_record(self) -> None:
        promotion = make_pending()
        assert promotion.item_id == "item-1"
        assert promotion.compaction_id == "compaction-1"
        assert promotion.category is CompactionItemCategory.FACTS
        assert promotion.status is PromotionStatus.PENDING
        assert promotion.resolved_memory_ids == ()
        assert promotion.resolution_kind is None
        assert promotion.resolution_reason is None
        assert promotion.retry_count == 0
        assert promotion.last_error is None
        assert promotion.created_at == NOW
        assert promotion.updated_at == NOW

    @pytest.mark.parametrize("item_id", ["", "   "])
    def test_empty_item_id_rejected(self, item_id: str) -> None:
        with pytest.raises(ValueError, match="item_id cannot be empty"):
            make_pending(item_id=item_id)

    @pytest.mark.parametrize("compaction_id", ["", "   "])
    def test_empty_compaction_id_rejected(self, compaction_id: str) -> None:
        with pytest.raises(ValueError, match="compaction_id cannot be empty"):
            make_pending(compaction_id=compaction_id)

    @pytest.mark.parametrize("category", ["facts", "FACTS", None, object()])
    def test_invalid_category_rejected(self, category) -> None:
        with pytest.raises(TypeError, match="Invalid category"):
            CompactionPromotion(
                item_id="item-1",
                compaction_id="compaction-1",
                category=category,
            )

    @pytest.mark.parametrize("status", ["pending", "PENDING", None, object()])
    def test_invalid_status_rejected(self, status) -> None:
        with pytest.raises(TypeError, match="Invalid status"):
            CompactionPromotion(
                item_id="item-1",
                compaction_id="compaction-1",
                category=CompactionItemCategory.FACTS,
                status=status,
            )

    @pytest.mark.parametrize("retry_count", [-1, 1.5, "1", True])
    def test_invalid_retry_count_rejected(self, retry_count) -> None:
        with pytest.raises((TypeError, ValueError)):
            CompactionPromotion(
                item_id="item-1",
                compaction_id="compaction-1",
                category=CompactionItemCategory.FACTS,
                retry_count=retry_count,
            )

    @pytest.mark.parametrize("value", [0, 3])
    def test_non_negative_retry_count_accepted(self, value: int) -> None:
        promotion = CompactionPromotion(
            item_id="item-1",
            compaction_id="compaction-1",
            category=CompactionItemCategory.FACTS,
            retry_count=value,
        )
        assert promotion.retry_count == value

    def test_naive_created_at_rejected(self) -> None:
        naive = datetime.combine(date(2026, 8, 18), time(12, 0, 0))
        with pytest.raises(ValueError, match="timezone-aware"):
            make_pending(created_at=naive)

    def test_naive_updated_at_rejected(self) -> None:
        naive = datetime.combine(date(2026, 8, 18), time(13, 0, 0))
        with pytest.raises(ValueError, match="timezone-aware"):
            CompactionPromotion(
                item_id="item-1",
                compaction_id="compaction-1",
                category=CompactionItemCategory.FACTS,
                created_at=NOW,
                updated_at=naive,
            )

    def test_updated_at_before_created_at_rejected(self) -> None:
        with pytest.raises(ValueError, match="earlier than created_at"):
            CompactionPromotion(
                item_id="item-1",
                compaction_id="compaction-1",
                category=CompactionItemCategory.FACTS,
                created_at=LATER,
                updated_at=NOW,
            )

    def test_pending_cannot_contain_resolved_memory_ids(self) -> None:
        with pytest.raises(ValueError, match="non-PROMOTED.*cannot claim"):
            CompactionPromotion(
                item_id="item-1",
                compaction_id="compaction-1",
                category=CompactionItemCategory.FACTS,
                resolved_memory_ids=("mem-1",),
            )

    def test_resolution_kind_only_valid_when_promoted(self) -> None:
        with pytest.raises(ValueError, match="resolution_kind.*PROMOTED"):
            CompactionPromotion(
                item_id="item-1",
                compaction_id="compaction-1",
                category=CompactionItemCategory.FACTS,
                resolution_kind=PromotionResolutionKind.CREATE,
            )

    def test_rejected_requires_reason_at_construction(self) -> None:
        with pytest.raises(ValueError, match="REJECTED.*resolution reason"):
            CompactionPromotion(
                item_id="item-1",
                compaction_id="compaction-1",
                category=CompactionItemCategory.FACTS,
                status=PromotionStatus.REJECTED,
            )

    @pytest.mark.parametrize("category", CATEGORIES)
    def test_all_categories_accepted(self, category: CompactionItemCategory) -> None:
        promotion = make_pending(category=category)
        assert promotion.category is category

    def test_required_fields_are_present(self) -> None:
        field_names = {field.name for field in fields(CompactionPromotion)}
        for required in (
            "item_id",
            "compaction_id",
            "category",
            "status",
            "resolved_memory_ids",
            "resolution_kind",
            "resolution_reason",
            "retry_count",
            "last_error",
            "created_at",
            "updated_at",
        ):
            assert required in field_names

    def test_immutability_frozen_behavior(self) -> None:
        promotion = make_pending()
        with pytest.raises(FrozenInstanceError):
            promotion.status = PromotionStatus.PROMOTED


class TestPromotedValidation:
    def test_promoted_requires_memory_ids(self) -> None:
        with pytest.raises(ValueError, match="PROMOTED.*requires resolved memory ID"):
            make_pending().mark_promoted(())

    def test_promoted_requires_memory_ids_at_construction(self) -> None:
        with pytest.raises(ValueError, match="PROMOTED.*requires resolved memory ID"):
            CompactionPromotion(
                item_id="item-1",
                compaction_id="compaction-1",
                category=CompactionItemCategory.FACTS,
                status=PromotionStatus.PROMOTED,
            )

    def test_empty_memory_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty values"):
            make_pending().mark_promoted(("mem-1", "   "))

    def test_scalar_memory_ids_rejected(self) -> None:
        with pytest.raises(TypeError, match="iterable of strings"):
            make_pending().mark_promoted("mem-1")

    def test_memory_ids_deduplicated_and_sorted(self) -> None:
        promoted = make_pending().mark_promoted(("mem-2", "mem-1", "mem-2"))
        assert promoted.resolved_memory_ids == ("mem-1", "mem-2")

    def test_invalid_resolution_kind_rejected(self) -> None:
        with pytest.raises(TypeError, match="Invalid resolution kind"):
            CompactionPromotion(
                item_id="item-1",
                compaction_id="compaction-1",
                category=CompactionItemCategory.FACTS,
                resolution_kind="create",
            )

    def test_valid_resolution_kind_accepted(self) -> None:
        promoted = make_pending().mark_promoted(
            ("mem-1",),
            resolution_kind=PromotionResolutionKind.SUPERSEDE,
        )
        assert promoted.resolution_kind is PromotionResolutionKind.SUPERSEDE


class TestRejectedValidation:
    def test_rejected_requires_reason(self) -> None:
        with pytest.raises(ValueError, match="REJECTED.*resolution reason"):
            make_pending().mark_rejected(None)

    @pytest.mark.parametrize("reason", ["", "   "])
    def test_empty_reason_rejected(self, reason: str) -> None:
        with pytest.raises(ValueError, match="resolution_reason cannot be empty"):
            make_pending().mark_rejected(reason)

    def test_rejected_cannot_claim_memory_ids(self) -> None:
        with pytest.raises(ValueError, match="non-PROMOTED.*cannot claim"):
            CompactionPromotion(
                item_id="item-1",
                compaction_id="compaction-1",
                category=CompactionItemCategory.FACTS,
                status=PromotionStatus.REJECTED,
                resolution_reason="duplicate",
                resolved_memory_ids=("mem-1",),
            )


class TestTransitions:
    def test_pending_to_promoted(self) -> None:
        promoted = make_pending().mark_promoted(("mem-1", "mem-2"), updated_at=LATER)
        assert promoted.status is PromotionStatus.PROMOTED
        assert promoted.resolved_memory_ids == ("mem-1", "mem-2")
        assert promoted.updated_at == LATER
        assert promoted.created_at == NOW

    def test_pending_to_rejected(self) -> None:
        rejected = make_pending().mark_rejected("duplicate of existing memory", updated_at=LATER)
        assert rejected.status is PromotionStatus.REJECTED
        assert rejected.resolution_reason == "duplicate of existing memory"
        assert rejected.updated_at == LATER

    def test_rejected_to_pending_only_through_reconsideration(self) -> None:
        rejected = make_pending().mark_rejected("duplicate")
        reconsidered = rejected.request_reconsideration(updated_at=LATER)
        assert reconsidered.status is PromotionStatus.PENDING
        assert reconsidered.updated_at == LATER
        assert reconsidered.resolved_memory_ids == ()
        assert reconsidered.retry_count == 0

    def test_rejected_cannot_go_to_promoted_without_reconsideration(self) -> None:
        rejected = make_pending().mark_rejected("duplicate")
        with pytest.raises(ValueError, match="only PENDING may become PROMOTED"):
            rejected.mark_promoted(("mem-1",))

    def test_rejected_cannot_be_rejected_again_without_reconsideration(self) -> None:
        rejected = make_pending().mark_rejected("duplicate")
        with pytest.raises(ValueError, match="only PENDING may become REJECTED"):
            rejected.mark_rejected("still duplicate")

    def test_reconsideration_then_promoted(self) -> None:
        promoted = (
            make_pending()
            .mark_rejected("duplicate")
            .request_reconsideration()
            .mark_promoted(("mem-1",))
        )
        assert promoted.status is PromotionStatus.PROMOTED
        assert promoted.resolved_memory_ids == ("mem-1",)

    def test_reconsideration_then_rejected(self) -> None:
        rejected = (
            make_pending()
            .mark_rejected("duplicate")
            .request_reconsideration()
            .mark_rejected("still duplicate")
        )
        assert rejected.status is PromotionStatus.REJECTED
        assert rejected.resolution_reason == "still duplicate"

    def test_promoted_cannot_return_to_pending(self) -> None:
        promoted = make_pending().mark_promoted(("mem-1",))
        with pytest.raises(ValueError, match="only REJECTED may be reconsidered"):
            promoted.request_reconsideration()

    def test_promoted_cannot_become_rejected(self) -> None:
        promoted = make_pending().mark_promoted(("mem-1",))
        with pytest.raises(ValueError, match="only PENDING may become REJECTED"):
            promoted.mark_rejected("nope")

    def test_promoted_cannot_be_promoted_again(self) -> None:
        promoted = make_pending().mark_promoted(("mem-1",))
        with pytest.raises(ValueError, match="only PENDING may become PROMOTED"):
            promoted.mark_promoted(("mem-2",))

    def test_pending_cannot_be_reconsidered(self) -> None:
        with pytest.raises(ValueError, match="only REJECTED may be reconsidered"):
            make_pending().request_reconsideration()

    def test_promoted_is_terminal_across_all_mutations(self) -> None:
        promoted = make_pending().mark_promoted(("mem-1",))
        with pytest.raises(ValueError):
            promoted.mark_promoted(("mem-2",))
        with pytest.raises(ValueError):
            promoted.mark_rejected("nope")
        with pytest.raises(ValueError):
            promoted.request_reconsideration()
        with pytest.raises(ValueError):
            promoted.record_transient_failure("boom")

    def test_transition_returns_new_object(self) -> None:
        pending = make_pending()
        promoted = pending.mark_promoted(("mem-1",))
        assert promoted is not pending
        assert pending.status is PromotionStatus.PENDING


class TestTransientFailures:
    def test_retry_count_increments_and_stays_pending(self) -> None:
        promotion = make_pending()
        after_first = promotion.record_transient_failure("memory.db unavailable", updated_at=LATER)
        assert after_first.status is PromotionStatus.PENDING
        assert after_first.retry_count == 1
        assert after_first.last_error == "memory.db unavailable"
        assert promotion.retry_count == 0

        after_second = after_first.record_transient_failure("timeout")
        assert after_second.retry_count == 2
        assert after_second.last_error == "timeout"
        assert after_second.status is PromotionStatus.PENDING

    def test_empty_failure_error_rejected(self) -> None:
        with pytest.raises(ValueError, match="last_error cannot be empty"):
            make_pending().record_transient_failure("   ")

    def test_transient_failure_rejected_when_not_pending(self) -> None:
        rejected = make_pending().mark_rejected("duplicate")
        with pytest.raises(ValueError, match="only PENDING may be retried"):
            rejected.record_transient_failure("boom")
        promoted = make_pending().mark_promoted(("mem-1",))
        with pytest.raises(ValueError, match="only PENDING may be retried"):
            promoted.record_transient_failure("boom")

    def test_failure_does_not_advance_status_lifecycle(self) -> None:
        promotion = make_pending().record_transient_failure("boom")
        promoted = promotion.mark_promoted(("mem-1",))
        assert promoted.status is PromotionStatus.PROMOTED


class TestAudit:
    def test_audit_information_survives_transitions(self) -> None:
        promotion = make_pending()
        promoted = (
            promotion.mark_rejected("duplicate", updated_at=LATER)
            .request_reconsideration(updated_at=LATER)
            .mark_promoted(("mem-1",), updated_at=LATER)
        )
        assert promoted.item_id == "item-1"
        assert promoted.compaction_id == "compaction-1"
        assert promoted.category is CompactionItemCategory.FACTS
        assert promoted.created_at == NOW
        assert promoted.updated_at == LATER

    def test_deterministic_item_id_remains_unchanged(self) -> None:
        item_id = "d7b33d2c6f0e4f7f9b1a3c5d7e9f0a1b"
        promotion = make_pending(item_id=item_id)
        rejected = promotion.mark_rejected("duplicate")
        reconsidered = rejected.request_reconsideration()
        promoted = reconsidered.mark_promoted(("mem-1",))
        assert promotion.item_id == item_id
        assert rejected.item_id == item_id
        assert reconsidered.item_id == item_id
        assert promoted.item_id == item_id

    def test_rejection_reason_and_error_preserved_as_history(self) -> None:
        promotion = make_pending().mark_rejected("duplicate").request_reconsideration()
        assert promotion.status is PromotionStatus.PENDING
        assert promotion.resolution_reason == "duplicate"