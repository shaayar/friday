# FRIDAY Build Log

> Canonical historical bridge between FRIDAY engineering and the FRIDAY
> build journal.
>
> **Status:** Historical reconstruction from the available engineering
> conversation and project context. Exact dates are not invented where
> unavailable.

------------------------------------------------------------------------

## 0. Why This Log Exists

FRIDAY is being built as a long-running personal AI assistant rather
than as a single voice-demo application.

This log records: - decisions - reasons - implementation changes -
failures - architectural corrections - deliberately deferred work -
current state

Failures and wrong assumptions are part of the record.

------------------------------------------------------------------------

## 1. Initial Direction

FRIDAY began as a voice-activated assistant inspired by a Tony
Stark-style personal assistant.

The intended system included: - voice input - LLM reasoning - spoken
responses - external tools - web/news lookup - system information -
custom scripts - persistent conversations - a tool-rich backend

The early architecture used two long-running processes:

1.  An MCP server exposing callable tools.
2.  A LiveKit-based voice agent.

The MCP server exposed tools through SSE. The voice agent handled the
conversational voice pipeline.

A recurring principle emerged:

> Do not make the assistant dependent on one model, provider, or
> interface.

------------------------------------------------------------------------

## 2. Early Architecture

The system evolved toward layered architecture rather than putting
everything inside `agent_friday.py`.

The intended lifecycle became:

``` text
USER
 │
 ▼
Input Normalizer
 │
 ▼
Request Object
 │
 ▼
Intent Classification
 │
 ├── Deterministic
 ├── AI Required
 └── Hybrid
 │
 ▼
Planner
 │
 ▼
Task Manager
 │
 ▼
Task Scheduler
 │
 ▼
Executor
 │
 ├── MCP Tools
 ├── Memory Manager
 └── AI Engine
 │
 ▼
Observation
 │
 ├── Session State
 └── Long-term Memory
 │
 ▼
Response Builder
 │
 ▼
Output Interface
```

Real implementation later refined these boundaries.

A major principle became:

> Build capabilities as independent subsystems first, then connect them
> through a proper assistant/session layer.

------------------------------------------------------------------------

## 3. Conversation Memory

The first concrete memory subsystem was conversation history.

A SQLite backend, `SQLiteConversationStore`, was created around
`Conversation` and `Message` domain objects.

It supports: - creating conversations - saving messages - retrieving
conversations - retrieving recent messages - timestamps - foreign-key
cascade deletion - context-manager usage - multiple store instances
against the same database

The schema uses `conversations` and `messages`.

The initial implementation passed 15 focused tests and was later
expanded.

------------------------------------------------------------------------

## 4. Memory Manager

A `MemoryManager` abstraction was introduced above SQLite.

The intent was to separate memory semantics from storage implementation.

It uses an injected `ConversationStorage` protocol.

The public operations are:

``` text
create_conversation()
save_message()
get_conversation()
get_recent_messages()
```

The API was deliberately kept small.

------------------------------------------------------------------------

## 5. LiveKit Conversation Integration

Conversation events were wired into the LiveKit voice session.

The intended event was:

``` text
conversation_item_added
```

User and assistant messages were persisted into the conversation store.

Conversation IDs were created for sessions and kept in session state.

Global memory state was deliberately avoided.

------------------------------------------------------------------------

## 6. Failure: Closed SQLite Database

The first LiveKit memory integration exposed a lifecycle problem.

The event handler attempted to save messages after the SQLite store had
already been closed.

The error was:

``` text
sqlite3.ProgrammingError: Cannot operate on a closed database.
```

Lesson:

> A persistence resource must outlive every callback that can write to
> it.

The fix was lifecycle/cleanup correction, not a MemoryManager API
redesign.

------------------------------------------------------------------------

## 7. Failure: Incorrect LiveKit Type Assumption

Another integration failure came from assuming:

``` python
isinstance(item, llm.ChatMessage)
```

The runtime object was not exposed through `llm.ChatMessage` in the
installed API.

The installed API/runtime needed to be inspected instead.

Lesson:

> Verify installed APIs and runtime objects before coding against them.

This principle later influenced provider integrations.

------------------------------------------------------------------------

## 8. TTS Exploration: Groq

FRIDAY explored Groq TTS using:

``` text
canopylabs/orpheus-v1-english
```

with voices such as:

``` text
autumn
```

The plugin generated requests to:

``` text
POST /openai/v1/audio/speech
```

------------------------------------------------------------------------

## 9. Failure: Groq Orpheus Character Limit

The installed plugin accepted arbitrary text, while the Orpheus endpoint
imposed a 200-character input limit.

Long FRIDAY responses therefore produced HTTP 400 errors.

Several fixes were considered: - patching the TTS call site -
monkey-patching the plugin - subclassing the TTS implementation -
overriding LiveKit's TTS pipeline

The final reasoning favored overriding the LiveKit text-processing
layer.

A `tts_node` override was implemented that: - preserved LiveKit
streaming - preserved cancellation and ordering - preserved text
transforms - split oversized sentences at word boundaries - limited
chunks to 200 characters

Tests verified chunk size, word boundaries, order, and preservation of
content.

------------------------------------------------------------------------

## 10. Failed Manual Groq Test

A manual `curl` test was initially malformed because the shell
interpreted the multiline command incorrectly.

The output included:

``` text
-H: command not found
-d: command not found
```

A later output file was:

``` text
JSON text data
```

rather than audio.

Lesson:

> Verify the exact command being executed before drawing conclusions
> about the API.

------------------------------------------------------------------------

## 11. Sarvam TTS Exploration

Sarvam TTS was investigated as an alternative.

The installed LiveKit plugin exposed streaming `sarvam.TTS`.

Models included:

``` text
bulbul:v2
bulbul:v3-beta
bulbul:v3
```

A compatible voice for `bulbul:v3` was identified as:

``` text
neha
```

The intended configuration was approximately:

``` python
sarvam.TTS(
    target_language_code="en-IN",
    model="bulbul:v3",
    speaker="neha",
    pace=1.15,
)
```

Voice availability differs between model versions.

------------------------------------------------------------------------

## 12. Failure: Assumed Sarvam Codec Parameter

A proposed constructor argument:

``` text
output_audio_codec="wav"
```

was assumed to exist.

The installed plugin did not support it.

The actual error was:

``` text
TypeError: TTS.__init__() got an unexpected keyword argument 'output_audio_codec'
```

Inspection showed that the installed plugin already emitted WAV
internally.

Lesson:

> Never assume a provider/plugin API from memory. Inspect the installed
> version.

------------------------------------------------------------------------

## 13. LiveKit Version Upgrade Attempt

The project later attempted to move from LiveKit 1.5 toward 1.6.

Dependency resolution failed because project constraints conflicted with
available `livekit-api` versions across supported Python versions.

The resolver reported an unsatisfiable combination involving:

``` text
livekit-agents>=1.6
livekit-api>=1.6,<2.dev0
```

Lesson:

> "Latest" is not automatically compatible. Resolve dependencies against
> the actual project support matrix.

------------------------------------------------------------------------

## 14. Filesystem Capability Layer

FRIDAY needed controlled access to real project files.

The decision was not to give the assistant unrestricted filesystem
access.

A dedicated capability layer was built:

``` text
friday/filesystem/
├── models.py
├── exceptions.py
├── policy.py
├── registry.py
├── manager.py
└── tests
```

The subsystem is: - deny-by-default - permission-aware -
transport-independent - stdlib-focused - based on explicit authorization

------------------------------------------------------------------------

## 15. Filesystem Security Model

The policy boundary follows:

``` text
requested path
     ↓
normalize / resolve
     ↓
containment check
     ↓
permission check
     ↓
resolved authorized path
     ↓
I/O
```

It handles: - `..` traversal - symlink escapes - workspace root -
external authorized roots - read/write permissions

TOCTOU limitations are documented honestly.

------------------------------------------------------------------------

## 16. Filesystem Manager and MCP

`FileSystemManager` supports:

``` text
read_file
write_file
list_directory
search_files
```

and later:

``` text
create_directory
```

for internal workspace creation.

Limits exist for reads, writes, directory listings, search depth, and
search results. Violations raise explicit errors instead of silently
truncating.

The MCP adapter exposes:

``` text
read_file
write_file
list_directory
search_files
```

with a consistent result envelope:

``` json
{
  "success": true,
  "error": null,
  "data": {}
}
```

Filesystem policy and I/O remain outside MCP.

------------------------------------------------------------------------

## 17. Manual Filesystem Testing

The filesystem implementation was manually tested through MCP Inspector.

An initial failure was:

``` text
Access denied - path outside allowed directories:
/home/higan/Desktop/friday/test.txt
not in /tmp
```

The cause was not FRIDAY's implementation.

MCP Inspector was connected to its reference server:

``` text
filesystem-server-default
npx -y @modelcontextprotocol/server-filesystem /tmp
```

rather than FRIDAY's server.

FRIDAY's actual SSE endpoint was:

``` text
http://127.0.0.1:8000/sse
```

After connecting to the correct server, the filesystem tools worked.

Lesson:

> Verify which process/server is actually receiving an integration test.

------------------------------------------------------------------------

## 18. Filesystem v1 Result

Filesystem implementation reached:

``` text
77 tests passing
```

Manual testing verified: - write - read - list - search - duplicate
protection - overwrite - outside-root denial - traversal denial -
directory/file errors - missing-parent handling

Filesystem v1 was frozen.

------------------------------------------------------------------------

## 19. Project Workspace Concept

Filesystem access alone was insufficient. FRIDAY needed a concept of a
project.

Two mechanisms were deliberately combined:

1.  Explicit project registration.
2.  Current-working-directory detection.

The decision:

> Support both.

Explicit registration is authoritative.

CWD detection is convenience/discovery and never silently registers
unknown directories.

------------------------------------------------------------------------

## 20. Project Identity, Root, and Private Workspace

A critical separation was established:

``` text
User project
~/Projects/PostLeaf/
├── source
├── package.json
└── ...

FRIDAY private workspace
~/.friday/projects/<project-id>/
├── context.md
├── facts.md
├── decisions.md
├── changelog.md
└── state.json
```

The private workspace is FRIDAY's understanding of the project, not a
copy of the source repository.

------------------------------------------------------------------------

## 21. Project Registry Unification

Instead of creating a second registry, the filesystem root registry was
evolved into a project-aware registry.

A project contains:

``` text
id
root
name
permissions
created_at
```

Stable IDs are independent of display names.

Renaming therefore does not break the private workspace.

Existing grant-style registry data remains backward-loadable.

------------------------------------------------------------------------

## 22. Longest-Root Matching

Nested roots created a subtle detection problem.

For:

``` text
~/Projects
~/Projects/PostLeaf
```

and CWD:

``` text
~/Projects/PostLeaf/src
```

the most specific matching root must win.

The registry was changed from first-match behavior to longest-root
matching.

This makes nested project detection deterministic.

------------------------------------------------------------------------

## 23. Project Workspace

The initial project workspace is:

``` text
~/.friday/projects/<project-id>/
├── context.md
├── facts.md
├── decisions.md
├── changelog.md
└── state.json
```

Markdown is used for human-readable knowledge. JSON is used for
structured state.

SQLite is deferred until retrieval/query requirements justify it.

All workspace I/O goes through the filesystem capability layer.

------------------------------------------------------------------------

## 24. Project Detection and Active State

`ProjectDetector` is read-only.

It: - examines CWD - finds the most specific registered project root -
returns a detection result - never registers - never creates a workspace

The distinction is:

``` text
Project
    = durable identity

DetectedProject
    = runtime observation
```

Detection does not itself mean activation.

The active-project state machine became:

``` text
Explicit active project
        │
        ├── valid → keep it, regardless of CWD
        │
        └── invalid → clear → CWD fallback
```

Without explicit activation:

``` text
CWD detection
     │
     ├── project found → detected active
     └── none → no active project
```

`clear_active()` removes explicit focus and lets CWD detection resume.

The invariant is:

> Explicit active project beats detected project.

------------------------------------------------------------------------

## 25. Project Workspace Implementation Result

Project Workspace implementation reached:

``` text
129 tests passing
```

It included: - project registry - project models - workspace -
detector - active-project manager - service facade - filesystem
integration

Session wiring was deliberately not implemented because the proposed
domain `Session` model did not exist.

We decided:

``` text
Session.current_project = deferred
```

until a real assistant/session core exists.

------------------------------------------------------------------------

## 26. Project Workspace Manual Smoke Test

A temporary project was registered:

``` text
/tmp/friday-project-test
```

with name:

``` text
Test Project
```

and stable ID:

``` text
dee090a21610
```

Its workspace was created at:

``` text
~/.friday/projects/dee090a21610/
```

with:

``` text
context.md
facts.md
decisions.md
changelog.md
state.json
```

CWD detection from:

``` text
/tmp/friday-project-test/src/components
```

resolved correctly to:

``` text
/tmp/friday-project-test
```

Explicit activation persisted after moving to:

``` text
/tmp
```

Clearing explicit activation while inside the project changed the active
source to:

``` text
detected
```

The complete state machine passed manual verification.

------------------------------------------------------------------------

## 27. Durable Conversation History

Before Memory Distillation, we identified a prerequisite: raw
conversation history had to be genuinely durable.

The existing `SQLiteConversationStore` already used the correct default:

``` text
~/.friday/data/conversations.db
```

The actual bug was shutdown cleanup attempting to delete the database.

The erroneous line was:

``` python
db_path.unlink(missing_ok=True)
```

The fix was simply to stop deleting the database.

No schema redesign was needed.

After the fix:

``` text
37 memory tests passed
129 full-suite tests passed
```

Persistence was manually verified:

``` text
create conversation
    ↓
save messages
    ↓
close store
    ↓
reopen store
    ↓
same conversation/messages available
```

The database now survives process/store restarts.

------------------------------------------------------------------------

## 28. Memory Distillation

The next architectural distinction is:

``` text
RAW CONVERSATION ≠ LONG-TERM MEMORY
```

Raw conversation answers:

> What did we say?

Durable memory answers:

> What knowledge deserves to survive?

For example:

``` text
"I've been thinking about getting a cat."
```

must not automatically become:

``` text
User likes cats.
```

Likewise:

``` text
PostLeaf currently uses Next.js.
```

is project knowledge, not a global user fact.

Memory distillation therefore determines what information deserves
long-term survival.

------------------------------------------------------------------------

## 29. Initial Memory Taxonomy

The intentionally small initial taxonomy is:

``` text
user_fact
project_fact
project_constraint
project_decision
conversation_summary
```

Other concepts such as generic task memory, temporary context, and
entity memory are deferred until there is evidence for dedicated types.

The goal is to avoid premature ontology complexity.

------------------------------------------------------------------------

## 30. Memory Scope and Trust

Memory scope must distinguish:

``` text
User memory
Project memory
Conversation-local context
```

A project-specific fact must not silently become a global user fact.

A temporary conversation detail must not automatically become durable
memory.

The trust hierarchy is:

``` text
explicit
    >
inferred
    >
tentative
```

The LLM is a proposer, not the final authority.

Conceptually:

``` text
Conversation
    ↓
LLM candidate extraction
    ↓
deterministic validation
    ↓
memory policy / resolver
    ↓
durable memory
```

Memory failures must never break the primary conversation.

------------------------------------------------------------------------

## 31. Provenance and Supersession

Durable memory should retain enough provenance to answer:

> Why does FRIDAY believe this?

Potential provenance includes: - source conversation - source messages -
timestamps - evidence - confidence

Important memories should not simply be overwritten.

For example:

``` text
M1: User likes cats.
```

followed by:

``` text
M2: User is not really a cat person.
```

should become:

``` text
M1 → superseded
M2 → active
M2.supersedes → M1
```

This preserves history and supports contradiction handling.

------------------------------------------------------------------------

## 32. Proposed Memory Storage

The current design favors a dedicated SQLite database:

``` text
~/.friday/data/memory.db
```

rather than mixing durable memory with raw conversations or treating
Markdown as a database.

SQLite is appropriate for: - querying - updates - provenance -
deduplication - status - supersession - future indexing

Vector databases are explicitly deferred.

Initial retrieval can use simple SQL/LIKE matching. FTS5 can be
introduced later if needed.

------------------------------------------------------------------------

## 33. Context Shrinking Is Separate

A further architectural distinction was identified:

**Context shrinking** and **memory distillation** are different systems.

Context shrinking answers:

> What should be sent to the LLM right now?

Memory distillation answers:

> What knowledge should survive long-term?

The intended relationship is:

``` text
                    CONVERSATION
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
       Context Manager       Memory Distiller
              │                     │
              ▼                     ▼
      Short-term context      Durable memory
              │                     │
              ▼                     ▼
             LLM                memory.db
```

Context shrinking should not repeatedly summarize and destroy the raw
history.

The raw conversation remains intact while runtime context can contain: -
recent turns - current task - relevant project context - relevant
durable memories - compressed older conversation

------------------------------------------------------------------------

## 34. Current Architecture

At the current point:

``` text
Filesystem Capability Layer     ✅
Project Registry                ✅
Project Workspace               ✅
CWD Detection                   ✅
Explicit Project Activation     ✅
Durable Conversation History    ✅
Memory Domain Models            ✅
Memory Storage (SQLite)         ✅
Durable Memory Manager          ✅
Memory Distillation             ✅
Memory Resolver                 ✅
Context Budget / Snapshot       ✅
Context Shrinker                ✅

Session.current_project         ⏳ deferred
Context Manager (assembly)      ⏳ next
Context Retrieval               ⏳
Runtime wiring (agent_friday)   ⏳ deferred
Web Interface                   ⏳
Agent naming                    ⏳
```

------------------------------------------------------------------------

## 35. Principles Established

### Verify before assuming

Installed APIs, runtime objects, provider behavior, and dependency
constraints must be inspected rather than guessed.

### Capabilities before orchestration

Filesystem, memory, projects, and other capabilities should exist
independently before being wired into a larger assistant/session core.

### Explicit trust boundaries

FRIDAY should not receive unrestricted filesystem access.

### Durable state is separated by purpose

``` text
conversations.db
    = raw conversation history

memory.db
    = durable extracted knowledge

project workspace
    = human-readable project understanding
```

### Raw history remains available

Compression and distillation should not destroy raw conversation by
default.

### LLMs propose; deterministic systems validate

Especially for durable memory.

### Do not invent abstractions merely to satisfy diagrams

The nonexistent Session model was deliberately deferred.

### Small, testable milestones

Each subsystem is implemented and manually verified before the next
major subsystem begins.

### Failures are architecture feedback

Groq limits, LiveKit lifecycle issues, MCP routing mistakes, API
mismatches, and dependency resolution problems remain part of the
engineering record.

------------------------------------------------------------------------

## 36. Next Engineering Direction

The immediate next milestone is:

``` text
Memory Domain Models
```

Before implementation, the boundary between Context Management and
Memory Distillation must remain explicit.

The eventual architecture should allow:

``` text
raw conversation
      ↓
short-term compressed context
      +
durable memory
      +
project context
      ↓
LLM context
```

The next engineering step should not assume that context shrinking and
memory distillation are the same mechanism.

------------------------------------------------------------------------

## 37. Historical Note

This document was reconstructed from the available FRIDAY engineering
conversation and project context after the system had already reached
the Filesystem, Project Workspace, and durable conversation milestones.

It is intended to become the bridge between:

``` text
FRIDAY engineering work
```

and:

``` text
FRIDAY public build journal
```

Future entries should record significant architectural changes as they
happen rather than reconstructing them months later.

------------------------------------------------------------------------

## 38. Memory Domain Models and Storage

The durable-memory subsystem (Milestone 3, Phase 2) was implemented and
verified.

Domain objects live in `friday/memory/models.py`:

``` text
Memory
MemoryType      user_fact | project_fact | project_constraint |
                project_decision | conversation_summary
MemoryScope     user | project | conversation
MemoryStatus    active | superseded | invalidated
MemoryConfidence explicit | inferred | tentative
MemoryProvenance source_conversation_id | source_message_ids
```

A dedicated SQLite store (`friday/memory/sqlite_memory_store.py`) backs a
dedicated database:

``` text
~/.friday/data/memory.db
```

keeping durable knowledge separate from raw conversations
(`conversations.db`) and the Markdown project workspace.

`DurableMemoryManager` (`friday/memory/durable_manager.py`) owns high-level
semantics: supersession, invalidation, and — added in Phase 3 — atomic batch
application (`apply_batch`). It delegates primitive persistence to an
injected `MemoryStorage`.

Phase 2 verified:

``` text
103 memory tests passed
195 full-suite tests passed
```

Ruff was clean on all new Phase 2 files. The remaining pre-existing
findings inside the memory subsystem (invalid-type checks in
`models.py`, the `__enter__` return annotation in `sqlite_store.py`, and
two test-file issues) were later cleaned up, so
`friday/memory`, `friday/context`, and `friday/ai` are all ruff-clean.
Lint findings elsewhere (agent orchestration, tools, server, and
pre-existing tests) remain outside this subsystem scope.

------------------------------------------------------------------------

## 39. Memory Distillation and Resolver

The core distinction governs distillation:

``` text
RAW CONVERSATION ≠ LONG-TERM MEMORY
```

The pipeline is:

``` text
conversation transcript
        ↓
MemoryExtractor      → proposes candidates (LLM is a proposer)
        ↓
deterministic validation / parsing
        ↓
MemoryResolver       → decides CREATE / SUPERSEDE / INVALIDATE / REJECT
        ↓
DurableMemoryManager.apply_batch → atomic durable writes
```

`MemoryCandidate` (`friday/memory/candidates.py`) is the temporary,
pre-identity proposal. It is never persisted. `Resolution` captures the
resolver's decision; `candidate_to_memory` maps a candidate into a durable
`Memory` only at execution time.

`MemoryExtractor` (`friday/memory/extractor.py`):

- considers only the most recent bounded window of messages (default 20)
- asks an LLM for structured, third-person factual statements
- tolerates malformed JSON (fenced, noisy, or object-wrapped output); bad
  candidates are logged and skipped, never written
- applies a deterministic trivia/relevance gate (`friday/memory/text.py`)
- never persists and never calls the durable manager

`MemoryResolver` (`friday/memory/resolver.py`) is the only component that
decides mutations. It is conservative by design:

- deduplication pipeline: normalize → exact → containment → difflib ratio
  (threshold 0.85, configurable)
- never supersedes or invalidates on weak heuristics; ambiguous overlaps
  preserve the existing memory and reject the candidate (or consult an
  advisory LLM when configured)
- confidence may only be lowered: hedged EXPLICIT → TENTATIVE

Scope mapping is a hard invariant: USER_FACT→USER, PROJECT_*→PROJECT,
CONVERSATION_SUMMARY→CONVERSATION. PROJECT scope requires a project_id;
non-PROJECT rejects one. The active project is context only and never
auto-converts user facts into project facts.

`DurableMemoryManager.apply_batch` applies a list of resolutions inside a
single transaction — the whole batch commits or the whole batch rolls back.

------------------------------------------------------------------------

## 40. Context Management

Context shrinking is separate from memory distillation:

``` text
Context Manager   → what should be sent to the LLM right now?
Memory Distiller  → what knowledge should survive long-term?
```

The context package (`friday/context/`) provides the building blocks:

- `ContextBudget` — bounds for assembled input, expressed in conservative
  character-based units (deliberately not token counts)
- `estimate_units` — ~4 characters per unit, over-counting rather than
  risking overflow
- `ContextSnapshot` — the immutable, testable result of one assembly pass
  with sources ordered by priority
- `ContextShrinker` — LLM-backed compression of older history into a short
  factual summary

Source priority (highest first):

``` text
1. system instructions     (never removed)
2. current user message    (never removed)
3. recent messages         (verbatim, recent turns)
4. project context         (capped)
5. durable memories        (capped)
6. compressed history      (older conversation)
```

Removal/compression proceeds in reverse priority; the shrinker is only
invoked when over budget. Configuration knobs (window sizes, caps, budget,
dedup threshold) live on `friday/config.py` as class attributes, not in the
domain models.

Failure isolation is a standing rule: extraction, resolution, database,
compression, and project-context failures must never break the primary
conversation; they are logged.

Provider independence is enforced: the memory and context packages depend
only on a minimal `LLMBackend` protocol (`friday/ai/backend.py`) and never
import openai/groq/sarvam/livekit. The actual runtime adapter to the
existing LiveKit LLM is deferred to the future assistant/session layer.

------------------------------------------------------------------------

## 41. Milestone 3 Phase 3 Result

Memory distillation and context management building blocks are implemented
with deterministic, conservative semantics and full test coverage using
fake LLM backends (no real provider calls in tests).

``` text
170 memory tests passed
191 memory + context tests passed
283 full-suite tests passed
```

Ruff is clean across `friday/memory`, `friday/context`, and `friday/ai`.

Runtime wiring is deliberately out of scope for this phase: no
`conversation_item_added` hook, no LiveKit session integration, and no
production extraction/context loops. `agent_friday.py` and the build-log
documentation were not modified as part of the implementation.

The remaining next engineering step is a `ContextManager` that assembles
these building blocks into a runtime context, followed by actual runtime
wiring through a real assistant/session layer.

------------------------------------------------------------------------

## 42. ContextManager and Post-Phase-3 Direction

A `ContextManager` (`friday/context/manager.py`) was added to assemble the
context building blocks into a runtime `ContextSnapshot`. It:

- preserves `system_instructions` and the `current_user_message` (never
  removed)
- preserves the recent window verbatim, targeting `2 × recent_turns`
  messages, dropping complete oldest messages/turns only when over budget
  (individual messages are never partially truncated)
- retrieves durable memories (deterministic lexical relevance → confidence
  → recency ranking) and project context, each capped
- invokes `ContextShrinker` only into the leftover budget after the recent
  window fits, compressing only the older window
- keeps the compressed summary runtime-only (only in
  `ContextSnapshot.compressed_history`; never persisted)
- isolates failures: memory, project-context, and compression failures
  degrade gracefully and never break the request

Source priority is:

``` text
1. system instructions     (never removed)
2. current user message    (never removed)
3. recent messages         (verbatim, recent turns)
4. project context         (capped)
5. durable memories        (capped)
6. compressed history      (older conversation)
```

This was verified against the full suite (309 tests passing) with the
context package ruff-clean.

### Post-Phase-3 architectural refinement

A post-Phase-3 discussion revisited the runtime shrinking design. It is
now understood that repeatedly generating a summary on every LLM request
is unnecessarily expensive and adds latency.

The preferred future direction is **conversation compaction**: move
historical-conversation compression from per-request runtime behavior
toward threshold-triggered, background, persistent compaction that
produces reusable conversation summaries and decision records. Runtime
context shrinking may eventually be reduced or eliminated in normal
operation.

The distinction is now explicit:

``` text
Raw conversation      → source of truth, complete historical record
Conversation summary  → compact historical continuity (what happened?)
Conversation decisions→ explicit agreements/conclusions (what did we decide?)
Durable memory        → cross-conversation knowledge worth retaining
Runtime context       → temporary working set for one LLM call
Skills                → how FRIDAY performs an operation
Knowledge blocks      → what FRIDAY knows about a subject/project
```

This is a proposed future architecture direction, not an implemented
behavior. Exact thresholds, decision schema, summary format, knowledge-block
schema, retrieval mechanism, and the final context-degradation algorithm
remain OPEN. See `docs/DECISION_LOG.md` ADR-024 and `docs/ARCHITECTURE.md`.
Raw conversation history remains the source of truth; compaction is an
index/cache of meaning that can be regenerated from raw history.
