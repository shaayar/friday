# Future Ideas

Ideas that are intentionally deferred.

---

## Planned

### Context Pipeline

Status: Planned

Description:

Optimize retrieved context through filtering, ranking, compression and token budgeting.

---

### Local AI Providers

Status: Planned

Examples:

- Ollama
- llama.cpp

---

### Local STT

Status: Planned

Examples:

- Faster Whisper

---

### Local TTS

Status: Planned

Examples:

- Piper

---

### Desktop Application

Status: Planned

Native desktop interface.

---

### Local Web Interface

Status: Planned

Browser-based local dashboard.

---

### Vision

Status: Research

Screen understanding.

OCR.

Image reasoning.

---

### Plugin System

Status: Research

Third-party capability extensions.

---

### Event Bus

Status: Planned

Internal publish/subscribe architecture.

---

### Workflow Engine

Status: Planned

Long-running workflows.

---

### Multi-Agent Collaboration

Status: Future

Specialized agents collaborating on complex tasks.

---

### Master Agent Orchestration

Status: Future

FRIDAY is intended to become a master agent orchestrator: it understands
and plans a task, selects a worker agent from an Agent Registry, delegates a
bounded task, and independently verifies the result before accepting,
retrying, or escalating.

Key direction:

- Workers receive explicit Task Contracts (objective, repository, constraints,
  acceptance criteria, expected outputs) rather than free-form requests.
- Initial worker candidates: **OpenCode** (coding/software engineering) and
  **Hermes** (general-purpose/operator work) — not permanent dependencies.
- Agent implementations are described by manifests and accessed through
  adapters in a registry; FRIDAY selects by capability, not by hard-coding.
- An independent verifier evaluates results against acceptance criteria
  (PASS / FAIL / NEEDS_REVIEW) rather than trusting worker self-report.
- Task/execution state is designed in the future orchestration phase; no
  Session model is invented now.

Phased roadmap:

M8.1 — Single-Worker Orchestration Foundation (NOT STARTED)
- Task Contract domain model
- In-memory Agent Registry
- Worker Adapter protocol + OpenCode adapter
- Deterministic Verifier
- Orchestration Loop
- Retry & Escalation
- Single-task vertical slice

M8.2 — Multi-Worker Orchestration (Future)
- Hermes Adapter
- Capability-Based Agent Selection
- Reassignment
- Worker Health / Availability
- Multi-Worker Verification

M8.3 — Task State & Reliability (Future)
- Execution State Model
- Task Lifecycle
- Task/Result Persistence
- Restart Recovery
- Retry/Reconciliation
- Concurrency Control

M8.4 — Permissioned Local Machine Control (Future)
- Tool Permission Model
- File Operations
- Command Execution
- Network Permissions
- Approval Boundaries
- Sandboxing / Isolation
- Audit Logging
- Security Verification
Hard boundary: NO unrestricted shell.

M8.5 — Advanced Orchestration (Future)
- Multi-step task planning
- Task decomposition
- Agent-to-agent delegation
- Parallel workers
- Dependency-aware execution
- Richer verifier strategies
- Human-in-the-loop approval
- Scheduling
- Long-running tasks

M8.6 — Local Intelligence (Future)
Aligned with Local Intelligence / Tiny ML Layer entry below.

See DECISION_LOG.md ADR-026 (`docs/ADR-026.md`) and ARCHITECTURE.md §16d.

---

### Local Machine Control

Status: Future

Controlled local-machine interaction through explicit, permissioned tools:
opening applications, URLs, files/folders, inspecting running processes, and
executing approved local commands. FRIDAY must NOT initially receive
unrestricted arbitrary shell access; safe application/file operations are
distinguished from potentially dangerous arbitrary command execution.

See DECISION_LOG.md ADR-026 (`docs/ADR-026.md`) and ARCHITECTURE.md.

---

### Autonomous Task Scheduling

Status: Future

Background execution with priorities and dependencies.

---

### Smart Context Compression

Status: Planned

Deterministic and AI-assisted context optimization before prompt construction.

Note: a post-Phase-3 refinement proposes moving historical-conversation
compression from per-request runtime shrinking toward threshold-triggered,
persistent conversation compaction. See DECISION_LOG.md ADR-024.

---

### Conversation Compaction

Status: Planned

Background, threshold-triggered compaction of raw conversation into
reusable, persisted conversation summaries and decision records, keeping
raw history as the source of truth. Intended to reduce or replace
per-request runtime shrinking in normal operation.

Compaction may also optionally project selected items into durable memory
through the existing memory pipeline. Automatic/background promotion is
deferred until a runtime/orchestration seam exists; promotion is live
downstream of successful compaction in the current runtime.

See DECISION_LOG.md ADR-024, ADR-025 (`docs/ADR-025.md`), and
ARCHITECTURE.md.

---

### Local Intelligence / Tiny ML Layer

Status: Future

FRIDAY may eventually use small local ML models and deterministic
classifiers for routine decisions, allowing the primary LLM
(API or Ollama) to focus on complex reasoning.

Potential future workloads include:

- memory classification
- fact/category classification
- memory relevance scoring
- routine compaction decisions
- task routing
- simple result classification
- deciding whether a task requires the main reasoning model

Possible model families:

- logistic regression
- decision trees
- small neural networks
- other lightweight classifiers/rankers

Do NOT lock the model architecture. Do NOT claim linear regression is the
selected model.

Intended hierarchy:

deterministic rules
        ↓
small local ML
        ↓
main reasoning model

Use the principle:

Use deterministic code where certainty is possible,
small models where patterns are learnable,
and the main model where reasoning is actually required.

Also document the future possibility of learning from FRIDAY's accumulated
decision traces, where appropriate and supported by the existing architecture.

Important: This remains FUTURE WORK. Do NOT connect it to the current
memory/compaction/promotion runtime.

---

### Home Automation

Status: Future

Integration with smart home ecosystems.

---

### Cloud Synchronization

Status: Future

Cross-device memory synchronization.

---

## Rejected

Reserved for ideas that were evaluated but intentionally discarded, along with the reasons why.

---

## Research Topics

- Knowledge graphs
- Hybrid retrieval
- MCP ecosystem evolution
- Event sourcing
- Local model orchestration
- Embedded vector databases
