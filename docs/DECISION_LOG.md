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
