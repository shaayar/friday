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

**Conversation Compaction and Progressive Disclosure**

A post-Phase-3 refinement proposes moving historical-conversation
handling from per-request runtime shrinking toward threshold-triggered,
background, persistent conversation compaction. This is now implemented behavior (M7.1b.4).

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

Implemented direction (package boundaries locked in `friday/compaction/`):

```text
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

The Knowledge Retrieval branch above remains primary. Compaction MAY
additionally project selected outputs into durable memory as an optional,
downstream step that is separate from context assembly:

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
distinct concepts. Promotion is strictly downstream of successful
compaction persistence and never rolls back successful compaction.

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

- `DECISION_LOG.md` — ADR-024, ADR-025
- `FRIDAY_BUILD_LOG.md` — §61

---

### Runtime Promotion Trigger (M7.1b.4)

The live runtime now executes promotion as a discrete background step strictly after successful compaction persistence:

```text
assistant message persisted
        │
        ├── memory extraction (independent background task)
        │
        └── compaction (independent background task)
                │
                ▼
        persisted compaction
                │
                ▼
        promotion background task
                │
                ▼
             memory.db
```

Key architectural boundaries:

- Memory extraction and compaction are independent background tasks (both scheduled via `AssistantSession._schedule_background`).
- Promotion is downstream of successful compaction persistence only.
- Promotion does not mutate conversation history.
- Promotion does not modify ContextManager.
- No cross-database transaction exists.
- Promotion ledger lives in `conversations.db`.
- Durable memories live in `memory.db`.

Reference ADR-025 for the full policy: category promotion rules, `EXPLICIT` confidence assignment, deterministic `project_id` from the caller, idempotent ledger, failure isolation, and atomic memory batch
application.

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

**Local Machine Control (future direction)**

FRIDAY is intended to eventually interact with the local machine in a controlled way: opening applications, opening URLs, opening files/folders,
inspecting running processes, and executing approved local commands.

Architectural boundary: FRIDAY must NOT initially receive unrestricted arbitrary shell access. Local-machine capabilities are exposed as explicit,
permissioned tools. Example future tools (not a locked final API):

- open_application
- close_application
- open_url
- open_file
- open_folder
- launch_command
- get_running_processes

The future local-system tool layer must support permission boundaries and
distinguish safe application/file operations from potentially dangerous
arbitrary command execution. This is planned direction only; no local-machine
tools are implemented now.

See DECISION_LOG.md ADR-026 (`docs/ADR-026.md`).

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

### 16. Agent Orchestration (Future Direction)

FRIDAY is intended to become more than a voice assistant: a master agent
orchestrator that delegates bounded tasks to specialized worker agents and
independently verifies their results. This is planned direction, not an
implemented behavior.

Intended architecture:

``` text
User
  ↓
FRIDAY
  ├── Memory / Context
  ├── Task understanding
  ├── Planner / Orchestrator
  │      ├── Agent Registry
  │      ├── OpenCode
  │      ├── Hermes
  │      └── future workers
  │
  ├── Verifier
  │
  └── Local System Tools
         ├── application control
         ├── file/folder operations
         ├── URL opening
         └── controlled command execution
```

Role flow:

``` text
User
  ↓
FRIDAY
  ↓
Task understanding / planning
  ↓
Agent selection
  ↓
Worker agent
  ↓
Independent verifier
  ↓
FRIDAY
  ↓
accept / retry / escalate
```

**Agent Registry**

Individual agent implementations are not hard-coded into FRIDAY's core
reasoning layer. Agents are described by manifests and accessed through
adapters; FRIDAY selects agents based on capability. Conceptual layout
(exact implementation OPEN):

``` text
agents/
├── opencode/
│   ├── manifest
│   └── adapter
├── hermes/
│   ├── manifest
│   └── adapter
└── verifier/
    ├── manifest
    └── adapter
```

A manifest describes capabilities, permissions, supported task types, input
contract, output contract, and execution mechanism.

**Initial worker agents**

- **OpenCode** — primary coding/software-engineering worker: repository
  modification, implementation, debugging, testing, refactoring.
- **Hermes** — general-purpose/operator worker: terminal/filesystem work,
  web/browser tasks, broader autonomous operations, delegation where
  appropriate.

These are initial candidate workers, not permanent architectural
dependencies. Adapters/contracts allow additional agents without changing
the core orchestrator.

**Independent verifier**

The worker that performs a task must NOT automatically be trusted to declare
its own work correct. A separate verifier/reviewer agent is first-class. It
receives the original task contract, acceptance criteria, worker
changes/results, test results, and relevant repository state, and returns a
structured result: `PASS`, `FAIL`, or `NEEDS_REVIEW`. Verification is against
acceptance criteria, not worker self-report. A failed verification may cause
FRIDAY to return the task to the worker with feedback, select another worker,
retry, or escalate to the user.

**Task contract**

Workers receive explicit, bounded Task Contracts rather than only free-form
natural-language requests. Conceptual fields: task ID, objective,
repository/workspace, constraints, acceptance criteria, expected outputs,
relevant context, execution permissions. Exact schema OPEN.

**Orchestration loop**

``` text
FRIDAY
  ↓
create Task Contract
  ↓
select worker
  ↓
execute worker
  ↓
collect result
  ↓
independent verifier
  ↓
PASS ───────────────→ accept
  │
  FAIL ──────────────→ retry/reassign
  │
  NEEDS_REVIEW ──────→ human escalation
```

The orchestration system should maintain execution state and results. No
Session model is invented merely to represent this now; task/execution state
is designed during the future orchestration phase.

**Security / permission boundary**

FRIDAY should NOT initially have unrestricted authority over arbitrary shell
commands, filesystem deletion, credentials, system configuration, network
access, or privileged operations. Agent capabilities are permissioned;
workers receive only the permissions their task requires; the verifier has
enough access to inspect and test work but does not automatically inherit
unrestricted worker privileges. Arbitrary unrestricted local command
execution is NOT the initial security model. Sandboxing/permission mechanics
are OPEN.

**Relation to memory / context**

The existing memory/context architecture remains authoritative. The future
orchestration layer eventually uses:

``` text
Memory      → persistent user/project knowledge
Context     → per-invocation working context
Compaction  → persistent conversation knowledge/context
Task state  → future execution state
```

These are NOT collapsed into one storage mechanism. Worker results and
important task outcomes may eventually become inputs to FRIDAY's
memory/compaction systems through explicit pipelines (not implemented now).

Locked principles and open implementation details are separated in
DECISION_LOG.md ADR-026 (`docs/ADR-026.md`).

---

### 16b. M7 → M8 Architectural Boundary

M7 establishes the FRIDAY **assistant-runtime foundation**:

```text
conversation persistence
        ↓
context assembly
        ↓
memory extraction
        ↓
compaction
        ↓
optional durable-memory promotion
```

M8 builds the **agent-orchestration layer** on top of this foundation.

Orchestration must consume these systems through defined interfaces rather than merging their responsibilities.

Preserve the separation between:

- conversation state
- context state
- durable memory
- compaction state
- promotion state
- task/execution state
- agent state

The architecture communicates:

```text
Memory ≠ Context
Context ≠ Compaction
Compaction ≠ Durable Memory
Promotion ≠ Compaction
Task execution ≠ Memory
```

No Task model or execution schema is introduced here. M8 design is deferred
to the future orchestration phase.

---

### 16c. M7 / M8 Responsibility Summary

| M7 (Assistant Runtime Foundation) | M8 (Agent Orchestration Layer) |
|-----------------------------------|--------------------------------|
| Conversation persistence          | Task understanding             |
| Context assembly                  | Task planning                  |
| Memory extraction                 | Agent selection                |
| Memory resolution                 | Delegation                     |
| Compaction                        | Worker execution               |
| Promotion                         | Independent verification       |
| Background lifecycle              | Retry / reassignment / escalation |
|                                   | Permissioned local-machine actions |

M8 must NOT absorb M7 responsibilities. M8 orchestrates work using M7 capabilities as dependencies.

---

### 16d. M8 Master Agent Orchestration Roadmap

M8 implements the **master agent orchestration layer** on top of the M7 assistant-runtime foundation.

Overall direction:

```text
                    FRIDAY
                 MASTER AGENT
                  ORCHESTRATOR
                       │
             understand → plan
                       │
                       ▼
                select worker
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
         OpenCode             Hermes
             │                   │
             └─────────┬─────────┘
                       ▼
                    result
                       │
                       ▼
                independent verifier
                       │
              ┌────────┼────────┐
              ▼        ▼        ▼
            PASS      FAIL   NEEDS_REVIEW
              │        │        │
              ▼        ▼        ▼
           accept    retry/   escalate
                     reassign
```

Workers remain bounded execution systems. FRIDAY remains responsible for orchestration and acceptance. The verifier remains independent from the worker. M7 subsystems remain separate.

#### M8 Phases

| Phase | Goal | Status |
|-------|------|--------|
| **M8.1** | Single-Worker Orchestration Foundation | NOT STARTED |
| **M8.2** | Multi-Worker Orchestration | FUTURE |
| **M8.3** | Task State & Reliability | FUTURE |
| **M8.4** | Permissioned Local Machine Control | FUTURE |
| **M8.5** | Advanced Orchestration | FUTURE |
| **M8.6** | Local Intelligence | FUTURE |

---

#### M8.1 — Single-Worker Orchestration Foundation

Goal: Build the smallest complete orchestration loop using one worker.

| Milestone | Description | Status |
|-----------|-------------|--------|
| M8.1.1 | Task Contract domain model | NOT STARTED |
| M8.1.2 | In-memory Agent Registry | NOT STARTED |
| M8.1.3 | Worker Adapter protocol + OpenCode adapter | NOT STARTED |
| M8.1.4 | Deterministic Verifier | NOT STARTED |
| M8.1.5 | Orchestration Loop | NOT STARTED |
| M8.1.6 | Retry & Escalation | NOT STARTED |
| M8.1.7 | M8.1 Integration & Verification | NOT STARTED |

**M8.1 Scope:**

- One hard-coded worker (OpenCode adapter selected for M8.1 implementation)
- In-memory registry, no persistence
- Synchronous execution
- Deterministic verifier only
- Runtime-only task state
- Zero automatic memory writes
- One retry, escalate after failure

**M8.1 Explicitly Defers:**

- Hermes integration
- Persistent task state
- Reassignment
- Local machine control
- LLM verifier
- Scheduler
- Multi-worker selection

---

#### M8.2 — Multi-Worker Orchestration

Goal: Move from one worker to multiple bounded workers.

Planned milestones (all FUTURE, no schemas locked):

- M8.2.1 — Hermes Adapter
- M8.2.2 — Capability-Based Agent Selection
- M8.2.3 — Reassignment
- M8.2.4 — Worker Health / Availability
- M8.2.5 — Multi-Worker Verification
- M8.2.6 — Integration & Failure Testing

Exact health checks, retry counts, selection algorithms, and persistence remain OPEN until their milestone readiness reviews.

---

#### M8.3 — Task State & Reliability

Goal: Make orchestration resilient beyond a single in-memory task.

Potential milestones (all FUTURE):

- M8.3.1 — Execution State Model
- M8.3.2 — Task Lifecycle
- M8.3.3 — Task/Result Persistence
- M8.3.4 — Restart Recovery
- M8.3.5 — Retry/Reconciliation
- M8.3.6 — Concurrency Control
- M8.3.7 — Integration & Recovery Testing

**Hard boundaries:** Do NOT place task state in memory.db. Do NOT place task state in compaction tables. Persistence architecture remains OPEN until M8.3 readiness review.

---

#### M8.4 — Permissioned Local Machine Control

Goal: Allow FRIDAY to perform bounded local actions through explicit tools.

Planned milestones (all FUTURE):

- M8.4.1 — Tool Permission Model
- M8.4.2 — File Operations
- M8.4.3 — Command Execution
- M8.4.4 — Network Permissions
- M8.4.5 — Approval Boundaries
- M8.4.6 — Sandboxing / Isolation
- M8.4.7 — Audit Logging
- M8.4.8 — Security Verification

**Hard boundary:** NO unrestricted shell. Local-machine capabilities must be explicit, permissioned, bounded, and auditable. NOT implemented in M8.1.

---

#### M8.5 — Advanced Orchestration

Longer-term direction (FUTURE, no locked design):

- Multi-step task planning
- Task decomposition
- Agent-to-agent delegation
- Parallel workers
- Dependency-aware execution
- Richer verifier strategies
- Human-in-the-loop approval
- Scheduling
- Long-running tasks

No implementation schemas defined yet.

---

#### M8.6 — Local Intelligence

Aligned with FUTURE_IDEAS.md. Potential lightweight models for:

- Task routing
- Memory classification
- Fact/category classification
- Relevance scoring
- Routine compaction decisions
- Result classification
- Model selection

Hierarchy:
```text
deterministic rules
        ↓
small local ML
        ↓
main reasoning model
```

No model architecture selected. Candidates include logistic regression, decision trees, small neural networks, other lightweight classifiers/rankers. Do NOT connect to M8.1.

---

### 16e. M8.1 Decision State

| Decision | Status |
|----------|--------|
| FRIDAY as master orchestrator | LOCKED (ADR-026) |
| Bounded delegation | LOCKED (ADR-026) |
| Independent verifier | LOCKED (ADR-026) |
| Verification against acceptance criteria | LOCKED (ADR-026) |
| Adapter/registry architecture | LOCKED (ADR-026) |
| No unrestricted shell | LOCKED (ADR-026) |
| Subsystem separation | LOCKED (ADR-026 + §16b) |
| Single-task M8.1 milestone | REQUIRED FOR M8.1 |
| OpenCode adapter for M8.1 | REQUIRED FOR M8.1 |
| In-memory Agent Registry | REQUIRED FOR M8.1 |
| Synchronous execution | REQUIRED FOR M8.1 |
| Deterministic verifier | REQUIRED FOR M8.1 |
| Runtime-only task state | REQUIRED FOR M8.1 |
| Zero automatic memory writes | REQUIRED FOR M8.1 |
| No new database | REQUIRED FOR M8.1 |
| Exact TaskContract schema | OPEN |
| Repository/workspace representation | OPEN |
| Adapter internals / execution protocol | OPEN |
| Verifier implementation details | OPEN |
| Evidence model | OPEN |
| Permission model | OPEN |
| Worker health model | OPEN |
| Persistence model | OPEN |
| Hermes integration | FUTURE (M8.2) |
| Multi-worker selection | FUTURE (M8.2) |
| Reassignment | FUTURE (M8.2) |
| Persistent task state | FUTURE (M8.3) |
| Local machine control | FUTURE (M8.4) |
| LLM verifier | FUTURE (M8.5) |
| Agent-to-agent delegation | FUTURE (M8.5) |
| Scheduler | FUTURE (M8.5) |
| Advanced planning | FUTURE (M8.5) |
| Tiny/local ML | FUTURE (M8.6) |

**IMPORTANT:** ADR-026 describes OpenCode and Hermes as "initial candidate workers" not permanent dependencies. OpenCode selection for M8.1 is an M8.1 implementation milestone decision, not an ADR-026 strengthening.

---

### 17. Referenced Documents

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
