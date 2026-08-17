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

See DECISION_LOG.md ADR-024 and ARCHITECTURE.md.

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
