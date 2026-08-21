# Architecture Decision Log (ADR)

> This document records important architectural decisions made during the development of F.R.I.D.A.Y.
>
> The purpose of this log is to explain **why** a decision was made, not just **what** was implemented.
>
> Every major engineering decision should be documented before implementation.

---

## Status

Decision states:

- Proposed
- Accepted
- Deprecated
- Superseded
- Rejected

---

## Decision Template

```md
### ADR-XXX — Title

**Status**

Accepted

**Date**

YYYY-MM-DD

---

#### Context

What problem are we solving?

---

#### Decision

What have we decided?

---

#### Alternatives Considered

Option A

Option B

Option C

---

#### Consequences

Benefits

Drawbacks

Future considerations
```

---

## ADR-001 — Use MCP as the Tool Execution Layer

**Status**

Accepted

---

### Context

F.R.I.D.A.Y. requires an extensible mechanism for interacting with external capabilities such as:

- File system
- Browser
- Operating system
- Calendar
- Email
- Future plugins

The architecture should allow these capabilities to evolve independently from the AI engine.

---

### Decision

FastMCP will remain the primary tool execution layer.

All deterministic capabilities should be exposed as tools instead of being embedded directly inside the AI engine.

---

### Alternatives Considered

#### Native Python function calls

Simple but tightly coupled.

Rejected because tool discovery and future extensibility become difficult.

---

#### LangChain Tools

Too opinionated.

Introduces unnecessary framework dependency.

Rejected.

---

#### Custom RPC Layer

Maximum flexibility.

Unnecessary complexity for the current stage.

Can be reconsidered later.

---

### Consequences

#### Benefits

- Modular tool ecosystem
- Easy feature expansion
- AI remains independent from implementation
- Future plugin support

#### Drawbacks

- Additional abstraction layer
- Slight execution overhead

---

## ADR-002 — AI is a Capability, Not the Foundation

**Status**

Accepted

---

### Context

Many assistant projects route every request through an LLM.

This increases:

- latency
- API usage
- operating cost

and makes deterministic operations unnecessarily dependent on AI.

---

### Decision

F.R.I.D.A.Y. will use AI only when reasoning is required.

Deterministic software will be preferred whenever possible.

---

### Examples

Uses AI:

- Summarization
- Planning
- Explanation
- Ambiguous requests
- Brainstorming

Does NOT use AI:

- Opening applications
- File operations
- Reading battery level
- Launching projects
- Clipboard access

---

### Consequences

#### Benefits

- Lower latency
- Lower API costs
- Better reliability
- Reduced hallucinations

#### Drawbacks

- Requires an Intent Classification layer
- Some commands require additional routing logic

---

## ADR-003 — Separate Planning from Execution

**Status**

Accepted

---

### Context

Reasoning and execution represent different responsibilities.

Combining them tightly couples the AI with system operations.

---

### Decision

Planning and execution will remain separate.

Planner:

Determines what should happen.

Executor:

Performs the work.

---

### Consequences

Benefits:

- Easier testing
- Better debugging
- Replaceable planners
- Deterministic execution

---

## ADR-004 — Memory is Independent from AI

**Status**

Accepted

---

### Context

AI models are stateless.

Persistent knowledge should remain available even if providers change.

---

### Decision

Memory will exist as an independent subsystem.

The AI never accesses storage directly.

Instead:

Memory Manager

↓

Context Pipeline

↓

Prompt Builder

↓

AI

---

### Consequences

Benefits:

- Provider independence
- Easier testing
- Better memory management
- Flexible storage backends

---

## ADR-005 — Hybrid Online/Offline Architecture

**Status**

Accepted

---

### Context

The assistant should remain useful without internet connectivity while taking advantage of cloud services when available.

---

### Decision

Cloud providers will be the primary option.

Local providers will serve as fallbacks.

Examples:

STT

Sarvam

↓

Local Whisper

LLM

Gemini

↓

Ollama

TTS

Cloud Provider

↓

Local Provider

---

### Consequences

Benefits

- Better reliability
- Offline capability
- Lower operational risk

Drawbacks

- Additional provider implementations
- More testing required

---

## ADR-006 — Provider Independence

**Status**

Accepted

---

### Context

Business logic should never depend directly on a specific provider.

---

### Decision

Every external provider will be accessed through a common abstraction.

Examples include:

- LLM
- STT
- TTS
- Vector Database

---

### Consequences

Providers become replaceable without affecting higher-level modules.

---

## ADR-007 — Layered Memory Architecture

**Status**

Accepted

---

### Context

Different types of information require different storage and retrieval strategies.

---

### Decision

Memory will be divided into logical categories rather than using a single storage system.

Current categories include:

- Session State
- Conversation History
- Structured Memory
- Semantic Memory

Storage implementation is intentionally abstracted.

---

### Consequences

Different storage technologies can be introduced without changing business logic.

---

## ADR-008 — Context Pipeline

**Status**

Accepted

---

### Context

As memories and project knowledge grow, sending everything to the LLM becomes inefficient.

---

### Decision

Introduce a Context Pipeline between memory retrieval and prompt construction.

Responsibilities include:

- Filtering
- Ranking
- Deduplication
- Compression
- Token budgeting

The pipeline may use deterministic algorithms or AI-assisted compression when necessary.

---

### Consequences

Benefits

- Smaller prompts
- Better relevance
- Reduced token usage
- Improved scalability

---

## ADR-009 — Event-Driven Observability

**Status**

Proposed

---

### Context

The system should be observable, debuggable, and extensible.

---

### Proposed Decision

Every significant operation should emit an Event.

Examples:

- Request received
- Intent classified
- Plan created
- Task started
- Task completed
- Memory saved
- Tool executed

These events may later support:

- Logging
- Analytics
- Automation
- Plugin hooks

---

## ADR-010 — Request Pipeline as the Core Architecture

**Status**

Accepted

---

### Context

Rather than centering the architecture around the AI model, the system should be organized around how requests flow through it.

---

### Decision

The request lifecycle becomes the backbone of the architecture.

Every feature integrates into the existing lifecycle instead of introducing parallel execution paths.

See:

- `REQUEST_LIFECYCLE.md`
- `DOMAIN_MODEL.md`

---

## ADR-021 — Unify Project Registry with Filesystem Root Registry

**Status**

Accepted

**Date**

2026-08-13

---

### Context

The Project Workspace subsystem needs persistent project identity
(name, root) while the filesystem subsystem already persists
authorization grants for external roots. Two separate stores could
drift: a project could be "known" but not "authorized", or vice versa.

---

### Decision

Unify `ProjectRootRegistry` into a single project registry. A
registered project IS an authorized root. The registry stays in
`friday/filesystem/` as the security boundary consumed by `PathPolicy`,
and also serves as the source of project identity for the projects
layer. Storage path remains `~/.friday/project_roots.json` with
backward-compatible loading.

---

### Alternatives Considered

Separate project registry referencing grant IDs: cleaner separation of
security vs semantics, but introduces two sources of truth that must
stay in sync.

---

### Consequences

Benefits:

- Single source of truth, no drift
- Satisfies "do not duplicate the existing filesystem root registry"
- Rename/revoke cannot desynchronize authorization and identity

Drawbacks:

- Filesystem subsystem now carries the project identity concept

---

## ADR-022 — Project Workspace Content Format

**Status**

Accepted

**Date**

2026-08-13

---

### Context

The private FRIDAY project workspace stores assistant-maintained
context, facts, decisions, changelog, and state. The storage format
affects inspectability, diffs, rebuildability, and future querying.

---

### Decision

Use plain Markdown files for prose (`context.md`, `facts.md`,
`decisions.md`, `changelog.md`) and JSON for machine-readable state
(`state.json`). Migrate to SQLite later when retrieval/querying becomes
a real requirement. Do not use binary or custom encodings without a
demonstrated benefit.

---

### Alternatives Considered

SQLite now: premature schema and less human-inspectable; conflicts with
the "do not over-engineer the formats yet" guidance.

---

### Consequences

Benefits:

- Human-inspectable, diffable, rebuildable
- Zero schema in the first implementation
- Derived knowledge can be reconstructed if lost

Drawbacks:

- No querying until migration to a structured store

---

## ADR-023 — Active Project Precedence

**Status**

Accepted

**Date**

2026-08-13

---

### Context

Both explicit activation and CWD detection can produce an active
project. Without a precedence rule, CWD changes would silently override
an explicit user choice, and the two mechanisms would conflict.

---

### Decision

Explicit activation has the highest priority. CWD detection never
overrides an explicit pointer. With no explicit pointer, CWD detection
drives the active project: inside a registered root it becomes active
with `source="detected"`; leaving all roots clears it. `clear()` clears
the explicit pointer then immediately falls back to CWD detection.
Unregistering an explicitly active project invalidates the pointer and
falls back to detection.

---

### Alternatives Considered

CWD detection always wins: simple but makes explicit activation
meaningless. Session-only active state: no persistence across restarts.

---

### Consequences

Benefits:

- Predictable, deterministic transitions
- Explicit user intent survives CWD changes
- Persists across restarts

Drawbacks:

- Requires source tracking (`explicit` vs `detected`) on the pointer

---

## ADR-024 — Conversation Compaction and Progressive Disclosure (Post-Phase-3)

**Status**

Proposed

**Date**

2026-08-15

---

### Context

Phase 3 introduced `ContextManager` and `ContextShrinker`. The shrinker
summarizes the older window with an LLM, but the resulting summary lives
only in one `ContextSnapshot.compressed_history` and is regenerated on
every LLM request. Repeating this summarization per request is
unnecessarily expensive and adds latency.

A post-Phase-3 discussion reconsidered how historical conversation
should be handled, and distinguished several related-but-distinct
concepts that were previously conflated.

---

### Decision

Move historical-conversation compression from per-request runtime
behavior toward **conversation compaction**: threshold-triggered,
preferably background, persistent compaction that produces reusable
historical knowledge. Runtime context shrinking may eventually be
reduced or eliminated in normal operation.

Adopt an explicit separation of concepts:

``` text
Raw conversation        source of truth; complete historical record
Conversation summary    compact continuity — what happened earlier?
Conversation decisions  explicit agreements — what did we decide?
Durable memory          cross-conversation knowledge worth retaining
Runtime context         temporary working set for one LLM call
Skills                  how FRIDAY performs an operation
Knowledge               what FRIDAY knows about a subject/project
```

Future context architecture (approximate; package boundaries not locked):

``` text
Raw conversation
    ↓
ConversationCompactor
    ├── Conversation Summary
    ├── Conversation Decisions
    └── Topic/knowledge metadata
             ↓
        Knowledge Retrieval
             ↓
system instructions
current user message
recent conversation
relevant project context
relevant durable memories
relevant conversation summary
relevant conversation decisions
relevant knowledge/skills
             ↓
        ContextManager
             ↓
             LLM
```

The Knowledge Retrieval branch above remains the primary path. Compaction
MAY additionally project selected outputs into durable memory as an
optional, downstream step that is separate from context assembly:

``` text
ConversationCompactor
    └── optional memory promotion
            ↓
        MemoryCandidate
            ↓
        MemoryResolver
            ↓
          memory.db
```

Promotion is an optional projection, not a conversion of the compaction
record into memory. Conversation knowledge and durable memory remain
distinct concepts. See ADR-025.

Knowledge should follow a progressive-disclosure model: small addressable
blocks carry metadata (title, description, topic, project, type,
updated_at, keywords) and only the content of relevant blocks is loaded.
Initial retrieval remains deterministic/simple; no vector search or
embeddings for now.

Context priority policy: system and current message remain
non-negotiable; recent conversation should be much harder to discard than
low-priority project/memory material; individual messages are never
partially truncated — remove complete oldest messages/turns if reduction
is needed.

Raw conversation remains the source of truth. Compaction must not
initially delete raw history to save storage; the compact representation
is an index/cache of meaning regenerable from raw history.

---

### Alternatives Considered

Keep per-request runtime shrinking: simple and already implemented, but
expensive and latency-adding.

One generic document/knowledge system for all four concepts: rejected
because it would conflate skills, knowledge, decisions, and memory.

Vector/embedding retrieval now: deferred; initial retrieval stays
deterministic.

---

### Consequences

Benefits:

- Lower per-request latency and cost for long conversations
- Reusable, persisted summaries and decision records instead of
  regeneration
- Clear separation of raw history, summary, decisions, memory, skills,
  and knowledge

Drawbacks:

- New compaction subsystem not yet implemented; additional design needed
- Requires resolving threshold, schema, format, and retrieval questions
- The exact context-degradation algorithm remains undecided

Future considerations:

- Conversation compaction may become the primary mechanism for
  historical context, potentially reducing or eliminating the need for
  runtime `ContextShrinker` in normal operation.

---

### ADR-024 Status Update (Post-M7)

ADR-024 proposed the compaction subsystem as future direction. As of M7.1b.4, the compaction subsystem is fully implemented in `friday/compaction/` and wired into the live runtime (`AssistantSession`). The promotion path defined by ADR-025 is also implemented and running.

The remaining items from the ADR-024 "Drawbacks" section that remain OPEN:

- Exact context-degradation algorithm remains undecided (may simplify or eliminate runtime `ContextShrinker` in normal operation)
- Knowledge-block schema, retrieval mechanism, and progressive-disclosure metadata remain OPEN

---

## ADR-025 — Compaction Memory Promotion

**Status**

Accepted

**Date**

2026-08-18

---

Promotion of conversation compaction into durable memory is locked
architecturally: compaction is context, NOT durable memory; promotion is an
optional downstream projection through the existing memory pipeline
(`MemoryCandidate` → `MemoryResolver` → `DurableMemoryManager.apply_batch`
→ memory.db), with category eligibility, deterministic confidence/project
identity, and a promotion ledger keyed by `CompactionItem.item_id`.

Full decision: see `docs/ADR-025.md`.

---

## ADR-026 — Master Agent Orchestration and Local Machine Control

**Status**

Accepted

**Date**

2026-08-19

---

FRIDAY's future direction is recorded as master agent orchestration:
FRIDAY is the decision-maker/orchestrator that delegates bounded tasks to
specialized worker agents (initial candidates: OpenCode for coding,
Hermes for general/operator work) via an Agent Registry and adapters rather
than hard-coded implementations, and independently verifies results through
a separate verifier agent against explicit Task Contracts. Local-machine
interaction (applications, URLs, files/folders, process inspection, approved
commands) will be exposed through explicit, permissioned tools — NOT
unrestricted arbitrary shell access. Memory/context/compaction/task state
remain conceptually separate.

Full decision, including the LOCKED vs OPEN split: see `docs/ADR-026.md`.

---

## Future Decisions

Reserved IDs:
- ADR-011 — Desktop Interface
- ADR-012 — Memory Storage Backend
- ADR-013 — Provider Configuration
- ADR-014 — Plugin System
- ADR-015 — Vision Architecture
- ADR-016 — Workflow Engine
- ADR-017 — Multi-Agent Support
- ADR-018 — Authentication
- ADR-019 — Synchronization
- ADR-020 — Deployment Strategy
