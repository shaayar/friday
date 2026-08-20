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

See DECISION_LOG.md ADR-026 (`docs/ADR-026.md`) and ARCHITECTURE.md §16.

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
deferred until a runtime/orchestration seam exists; promotion is explicitly
invocable in the current implementation phase.

See DECISION_LOG.md ADR-024, ADR-025 (`docs/ADR-025.md`), and
ARCHITECTURE.md.

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
