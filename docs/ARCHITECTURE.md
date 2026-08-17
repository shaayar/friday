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

**Interface Separation**

The assistant core is independent from any specific user interface.

Conceptually:

```
Assistant Core
├── Memory
├── Tools
├── Files
├── Projects
├── Planning
└── Persona
```

Interfaces:

```
LiveKit Voice
CLI
Web UI
```

Architectural rule:

- `agent_friday.py` is a voice/interface adapter, not the assistant core.
- The system must be designed so additional interfaces can interact with the same core capabilities without duplicating business logic.

**Web Interface (planned)**

A Web UI is planned as a future interface.

It is intentionally deferred until the assistant core, memory, tools, and filesystem capabilities are stable.

UI implementation, framework, and design are intentionally not specified.

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

**Project Workspace (planned)**

The planned concept of an internal project workspace stores assistant-maintained project context, decisions, facts, state, and history needed to work effectively on a project.

```
~/.friday/projects/<project-id>/
├── context
├── facts
├── decisions
├── changelog
└── state
```

These files are internal assistant state and are not intended to be treated as normal user-facing documents.

**Memory Distillation**

Architectural memory distinguishes raw conversation history from durable memory:

```
Conversation
    ↓
Memory Extraction
    ↓
Facts / Preferences / Decisions / Tasks
    ↓
Long-term Memory
```

Project-related information should be distinguishable from general long-term user memory.

Project information should eventually feed the project workspace/context layer rather than storing every raw conversation indefinitely.

This is architectural direction only. The extraction algorithm, LLM model, and database schema are intentionally not defined.

**Conversation Compaction and Progressive Disclosure (future direction)**

A post-Phase-3 refinement proposes moving historical-conversation
handling from per-request runtime shrinking toward threshold-triggered,
background, persistent conversation compaction. This is a proposed future
architecture, not an implemented behavior.

A strict distinction is maintained between:

```
Raw conversation        → source of truth, complete historical record
Conversation summary    → compact continuity (what happened earlier?)
Conversation decisions  → explicit agreements (what did we decide?)
Durable memory          → cross-conversation knowledge worth retaining
Runtime context         → temporary working set for one LLM call
Skills                  → how FRIDAY performs an operation
Knowledge blocks        → what FRIDAY knows about a subject/project
```

Intended direction (approximate; package boundaries not locked):

```
Raw conversation
    ↓
ConversationCompactor
    ├── Conversation Summary
    ├── Conversation Decisions
    └── Topic/knowledge metadata
             ↓
        Knowledge Retrieval
             ↓
        ContextManager
             ↓
             LLM
```

Knowledge is intended to follow a progressive-disclosure model: small
addressable blocks carry retrieval metadata (title, description, topic,
project, type, updated_at, keywords); the runtime first identifies
relevant knowledge and only then loads relevant content. Initial retrieval
remains deterministic/simple. Vector search and embeddings are explicitly
out of scope for now.

Exact thresholds, summary format, decision schema, knowledge-block schema,
retrieval mechanism, and the final context-degradation algorithm remain
OPEN. Raw conversation remains the source of truth; compacted forms are
regenerable indexes/caches of meaning.

See:

- `DECISION_LOG.md` — ADR-024
- `FRIDAY_BUILD_LOG.md` — §42

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

**Filesystem Capability (planned)**

Filesystem access will be exposed through controlled tools rather than unrestricted operating-system access.

Planned capabilities:

- read_file
- write_file
- list_directory
- create_directory
- move_file
- copy_file
- delete_file
- search_files

The assistant must not receive unrestricted filesystem access. Filesystem operations must pass through an explicit capability/policy boundary.

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

The following are planned/deferred capabilities, not current implementation goals:

- Web UI implementation
- final assistant naming
- unrestricted filesystem access
- memory distillation implementation
- project workspace implementation

---

### 15. Current Development Priority

Current priority is stabilizing the assistant core and its capabilities before building presentation layers.

Recommended progression:

Core runtime
→ Filesystem tools
→ Project workspace
→ Memory distillation
→ Expanded tool/action capabilities
→ Web interface
→ Final assistant identity

---

### 16. Referenced Documents

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

---

### Identity Independence

The assistant's final name and identity are intentionally undecided.

The implementation must not hard-code the eventual public identity into architectural assumptions.

The assistant name should eventually be configuration/persona data rather than something that affects core architecture.

Naming is DEFERRED.
