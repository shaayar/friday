"""Deterministic compaction trigger evaluation (M5).

A pure decision function with no I/O: it never calls the LLM and never
touches storage. It answers one question — "should this conversation be
compacted now?" — given the uncompacted traffic since the last boundary.

Hybrid model (locked in the Phase 4 design):

- message trigger: compact when the number of uncompacted messages reaches
    ``message_threshold`` (locked default 20).
- size trigger: compact when the estimated units of uncompacted messages
    reach ``unit_threshold``. Units use the repository's character-unit
    estimation convention (``friday.context.models.estimate_units``); the exact
    default threshold value was left OPEN in the design and is provisional.

The two triggers are OR'd: whichever is reached first triggers compaction.
``force=True`` bypasses both thresholds and compacts whatever valid
uncompacted window exists — it only requires that at least one uncompacted
message remains.
"""

from __future__ import annotations


def _validate_non_negative(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _validate_positive(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def should_compact(
    message_count_since_boundary: int,
    estimated_units_since_boundary: int,
    *,
    force: bool = False,
    message_threshold: int,
    unit_threshold: int | None,
) -> bool:
    """Decide whether compaction should run, without side effects.

    Args:
        message_count_since_boundary: number of uncompacted messages.
        estimated_units_since_boundary: estimated units of uncompacted traffic
            (character-unit convention, provider-agnostic).
        force: bypass thresholds and compact whenever at least one
            uncompacted message remains.
        message_threshold: message-count trigger threshold (positive int).
        unit_threshold: size trigger threshold in units, or ``None`` to
            disable the size trigger.

    Returns ``True`` when compaction should run.
    """
    message_count_since_boundary = _validate_non_negative("message_count_since_boundary", message_count_since_boundary)
    estimated_units_since_boundary = _validate_non_negative(
        "estimated_units_since_boundary", estimated_units_since_boundary
    )
    if not isinstance(force, bool):
        raise TypeError("force must be a bool")
    message_threshold = _validate_positive("message_threshold", message_threshold)
    if unit_threshold is not None:
        unit_threshold = _validate_positive("unit_threshold", unit_threshold)

    if force:
        return message_count_since_boundary > 0
    if unit_threshold is not None and estimated_units_since_boundary >= unit_threshold:
        return True
    return message_count_since_boundary >= message_threshold


__all__ = ["should_compact"]