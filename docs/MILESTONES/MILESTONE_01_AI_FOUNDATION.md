# Milestone 01 — AI Foundation

## Goal

Refactor the existing AI subsystem into a modular architecture without changing runtime behavior.

---

## Objectives

- Create the AI package structure.
- Move prompt loading into the AI subsystem.
- Introduce provider abstraction.
- Preserve existing functionality.
- Improve maintainability.

---

## Requirements

- Existing voice pipeline must continue working.
- No behavioral changes.
- No new features.
- No memory implementation.
- No routing implementation.

---

## Deliverables

- AI package
- Provider abstraction
- Prompt loader
- Prompt files
- Updated imports

---

## Acceptance Criteria

- Assistant behaves identically.
- Existing tools continue working.
- Current providers continue working.
- No breaking API changes.

---

## Out of Scope

- SQLite
- ChromaDB
- Context Builder
- Planner
- Intent Classifier
- Desktop UI

---

## Completion Checklist

- [ ] AI package created
- [ ] Provider interface added
- [ ] Prompt loader added
- [ ] Prompt moved from Python strings
- [ ] Tests pass
