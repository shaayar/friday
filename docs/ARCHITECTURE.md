# F.R.I.D.A.Y.

## System Architecture

---

### 1. Purpose

What is FRIDAY?

Why does it exist?

What problems does it solve?

---

### 2. Design Philosophy

Core engineering principles.

Examples:

- AI is a capability, not the foundation.
- Deterministic software first.
- Modular architecture.
- Single responsibility.
- Provider independence.
- Local-first where practical.

---

### 3. Guiding Principles

Engineering rules.

Examples:

- Prefer composition over inheritance.
- Separate planning from execution.
- Memory is independent from AI.
- Providers are implementation details.
- Every subsystem owns one responsibility.

---

### 4. System Overview

High-level description.

Include the complete system diagram.

---

### 5. Architectural Layers

Describe each layer.

Interfaces

↓

Core

↓

Execution

↓

Providers

Explain why each exists.

---

### 6. Core Subsystems

Brief description of every subsystem.

Input Layer

Intent Classification

Planner

Task Manager

Executor

Memory Manager

Context Pipeline

Prompt Builder

AI Engine

Observation

Response Builder

Do NOT explain implementation.

Only responsibilities.

---

### 7. Data Flow

Brief explanation.

Reference:

REQUEST_LIFECYCLE.md

---

### 8. Shared Domain Language

Explain that every subsystem communicates through domain models.

Reference:

DOMAIN_MODEL.md

---

### 9. Storage Strategy

Explain what types of information exist.

Examples:

Working Memory

Conversation History

Structured Data

Semantic Knowledge

Do NOT discuss SQLite schema.

Do NOT discuss Chroma internals.

Only architectural decisions.

---

### 10. AI Architecture

Explain:

AI only reasons.

AI never owns:

- memory
- execution
- tools
- operating system

---

### 11. Tool Architecture

Explain MCP.

Why tools exist.

Responsibilities.

Future plugin system.

---

### 12. Provider Abstraction

Explain why providers are hidden behind interfaces.

Future replacements should never affect higher layers.

---

### 13. Scalability

How the architecture supports:

- desktop
- CLI
- API
- vision
- automation
- multi-agent
- plugins

without redesign.

---

### 14. Non-goals

Examples:

Not a chatbot.

Not an LLM wrapper.

Not tightly coupled to Gemini.

Not cloud dependent.

---

### 15. Referenced Documents

[REQUEST_LIFECYCLE.md](./REQUEST_LIFECYCLE.md)

[DOMAIN_MODEL.md](./DOMAIN_MODEL.md)

[COMPONENTS.md](./COMPONENTS.md)

[DECISION_LOG.md](./DECISION_LOG.md)

[MILESTONES](./MILESTONES/)

---

## Architectural Principles

### Separation of Concerns

Every subsystem owns exactly one responsibility.

---

### Deterministic First

If a problem can be solved without an LLM, it should be.

---

### Explicit Data Flow

Subsystems communicate through well-defined domain objects.

Avoid hidden state.

---

### Provider Independence

Business logic must never depend directly on Gemini, Ollama, Sarvam, or any external service.

---

### Observability

Every major operation should produce an observation or event.

The system should always be explainable and debuggable.

---

### Evolvability

Architecture should support adding new capabilities without modifying unrelated subsystems.
