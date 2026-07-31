# Coding Guidelines

## General Principles

- Readability over cleverness.
- Simplicity over abstraction.
- Explicit over implicit.
- Deterministic first.

---

## Architecture

- One component = one responsibility.
- Components communicate using domain models.
- Avoid circular dependencies.
- Keep providers replaceable.

---

## Imports

- Never import provider-specific code outside providers/.
- Prefer absolute imports.

---

## State

- Avoid global state.
- Configuration only through config.

---

## Error Handling

- Fail explicitly.
- Never silently ignore exceptions.
- Return structured errors.

---

## Logging

- Every important operation should be logged.
- Never print debugging information.

---

## Type Safety

- Type every public interface.
- Prefer dataclasses or Pydantic models for domain objects.
- Avoid passing dictionaries between components.

---

## AI

- AI should only reason.
- AI should never directly execute tools.
- AI should never directly access storage.

---

## Memory

- Memory must remain provider-independent.
- Storage implementation is hidden behind Memory Manager.

---

## Providers

Business logic must never depend on:

- Gemini
- Ollama
- SQLite
- ChromaDB
- Sarvam
- OpenAI

---

## Documentation

Every public module should contain:

- Purpose
- Responsibilities
- Inputs
- Outputs

before implementation begins.
