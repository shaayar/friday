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

------------------------------------------------------------------------

## 43. Compaction Domain Models (Phase 4, M1)

The Phase 4 compaction subsystem began with its immutable domain models.

Files:

``` text
friday/compaction/__init__.py
friday/compaction/models.py
friday/compaction/test_models.py
```

`CompactionItem` (frozen + slots):

``` text
item_id
content
source_message_ids
```

It validates a non-empty identity and content, requires non-empty provenance,
and normalizes source IDs to sorted, de-duplicated positive integers.

`ConversationCompaction` (frozen + slots):

``` text
compaction_id
conversation_id
first_message_id
last_message_id
created_at
compaction_version
summary
facts
decisions
changes
open_questions
```

Validation covers: positive integer conversation/message/version IDs,
`first_message_id <= last_message_id`, timezone-aware `created_at`, categories
containing only `CompactionItem` instances, and every `source_message_id`
falling within the inclusive compaction range.

Explicitly excluded from the domain: a `promoted` flag, `project_id`,
`status`, LLM/reasoning fields, storage/database handles, and a persisted
`next_start`.

42 M1 tests passed. M1 was independently verified before M2.

Architectural note: the domain models do not verify that source message IDs
actually exist in SQLite. That belongs to persistence/storage.

------------------------------------------------------------------------

## 44. Compaction Boundary and Bounded Window (Phase 4, M2)

M2 added the deterministic in-memory boundary computation and bounded window
selection.

Files:

``` text
friday/compaction/boundary.py
friday/compaction/test_boundary.py
friday/compaction/__init__.py
```

`Boundary` is derived as `max(last_message_id) + 1`, is `None` when no previous
compactions exist, is never stored, and is independent of compaction input
ordering.

Window selection: selects messages with `id >= boundary`, preserves original
ordering, selects at most `max_window`, does not mutate the input, and
tolerates gaps in SQLite message IDs.

Actual repository discovery: conversation message IDs are SQLite
`INTEGER PRIMARY KEY AUTOINCREMENT`, monotonic but not guaranteed gap-free,
with ordering by message ID. `max(last_message_id) + 1` is therefore a
lower-bound threshold, not an assumption that all intermediate IDs exist.

Edge decision: overlapping/duplicate compaction ranges were not specified by
the design. M2 conservatively tolerates them and derives the greatest boundary.

Architectural concern: the store `Message` uses integer IDs while the context
`Message` uses string tuple IDs; M2 operates on the conversation-store message
shape.

36 M2 tests passed, for 78 compaction tests total. Memory/context: 217.
Full suite: 387. Ruff clean.

------------------------------------------------------------------------

## 45. LLM Compaction Extraction (Phase 4, M3)

M3 added the extraction step that converts a bounded message window into a
validated `ConversationCompaction`.

Files:

``` text
friday/compaction/exceptions.py
friday/compaction/extractor.py
friday/compaction/test_extractor.py
friday/compaction/__init__.py
```

Implemented:

``` text
ConversationCompactionExtractor
CompactionError
CompactionProviderError
CompactionOutputError
```

API:

``` python
ConversationCompactionExtractor(llm: LLMBackend, *, compaction_version: int = 1)
extract(messages, *, conversation_id) -> ConversationCompaction
```

LLM contract: a provider-neutral `LLMBackend`; a system prompt defining the
five categories and the quoted-data boundary; a transcript supplied as
`[id] role: content`; JSON output with `summary`, `facts`, `decisions`,
`changes`, and `open_questions`.

Validation: JSON parsing tolerates whitespace, fences, and harmless
surrounding text; malformed JSON fails safely; `summary` must be a string;
categories must be lists when present; item content must be non-empty;
`source_message_ids` must be valid IDs from the supplied window; invalid
provenance is discarded/rejected safely. The compaction range is always
derived from the input messages — the LLM cannot redefine
`first_message_id`/`last_message_id` — and the resulting object must satisfy
the M1 invariants.

Identity: deterministic SHA-256 compaction IDs and item IDs. IDs are never
generated by the LLM; the same input produces the same IDs, and changed
content/provenance produces different item IDs.

Failure behavior: provider failure raises `CompactionProviderError`;
malformed/schema-invalid output raises `CompactionOutputError`; an empty
input window raises a deterministic `ValueError`. There is no retry loop and
raw provider exceptions do not escape.

33 M3 tests passed, for 111 compaction tests total. Memory/context: 217.
Full suite: 420. Ruff clean.

Architectural concern: M3 returns one compaction or raises typed errors,
unlike the existing `MemoryExtractor`, which returns an empty list on failure.
This is intentional so M5 can decide retry/isolation behavior.

------------------------------------------------------------------------

## 46. SQLite Compaction Storage (Phase 4, M4)

M4 added SQLite persistence for compaction records.

Files:

``` text
friday/compaction/sqlite_store.py
friday/compaction/exceptions.py
friday/compaction/__init__.py
friday/compaction/test_sqlite_store.py
```

Implemented:

``` text
SQLiteCompactionStore
CompactionStorageError
CompactionAlreadyExistsError
CompactionNotFoundError
CompactionCorruptError
```

Storage uses the existing `conversations.db` and does not create `memory.db`,
defaulting to `~/.friday/data/conversations.db`. It supports
`save`/`get`/`list_for_conversation`/`get_latest_for_conversation`, plus
`close` and context-manager support. There is no `update()`.

Schema:

``` text
conversation_compactions
compaction_items
compaction_provenance
```

Relationships: conversation → compactions, compaction → items, item →
provenance, all `ON DELETE CASCADE`, with category `CHECK` constraints and
foreign keys enabled.

Important boundary: source message content is never duplicated; provenance
is stored as message IDs. Source message existence is explicitly checked
during save; missing source messages produce `CompactionCorruptError`.

Persistence: atomic complete-compaction save, duplicate compaction IDs
rejected, compactions immutable, `compaction_version` persisted, unsupported
versions rejected on read, round-trip verified, and close/reopen durability
verified.

26 M4 tests passed, for 137 compaction tests total. Memory/context: 217.
Full suite: 446. Ruff clean.

Architectural note: compaction persistence shares `conversations.db` with raw
conversation history, while durable memory remains isolated in `memory.db`.

------------------------------------------------------------------------

## 47. Conversation Compactor and Triggers (Phase 4, M5)

M5 built the orchestration layer connecting the previously tested pieces and
added deterministic trigger evaluation with explicit force/flush.

Files:

``` text
friday/compaction/trigger.py
friday/compaction/compactor.py
friday/compaction/test_trigger.py
friday/compaction/test_compactor.py
friday/compaction/__init__.py
friday/config.py
```

Implemented:

``` text
should_compact()
ConversationCompactor
CompactionResult
CompactionStorage / Message protocols
```

Trigger: deterministic hybrid OR —

``` text
message_count >= message_threshold
    OR
estimated_units >= unit_threshold
```

`COMPACTION_MESSAGE_THRESHOLD = 20` is locked. `COMPACTION_MAX_WINDOW = 20`
is configured. Size uses the existing `estimate_units()` character-based
abstraction with a default size threshold of 4,000 units — **provisional/OPEN**
because Phase 4 did not lock the exact value.

Force: `compact(..., force=True)` acts as the explicit flush; there is no
separate `flush()` method. Force bypasses thresholds but still respects the
boundary, the bounded window, extraction validation, and persistence.

Workflow:

``` text
messages
  → M2 boundary
  → M2 bounded window
  → M3 extraction
  → M4 persistence
```

M2 boundary logic remains the sole source of the next compaction boundary.
M2 bounded-window selection remains the sole window-selection logic. The M3
extractor produces the validated `ConversationCompaction`, and M4's
`SQLiteCompactionStore` persists it atomically.

Properties: one bounded window per invocation, no loop over the entire
conversation, `remaining_messages` reports additional uncompacted work, a
successful persisted compaction advances the effective boundary, repeated
invocation after a successful compaction is a safe no-op, duplicate
persistence can be treated as idempotent success, failed extraction/storage
does not advance the boundary, the raw conversation is never mutated, and
there is no separate "mark compacted" operation.

Not integrated yet: MemoryResolver / memory.db, ContextManager, and
LiveKit/background execution. M5 exposes a synchronous deterministic
operation; a future runtime seam may call it from a background task.

M2 non-contiguous behavior preserved: if 1–20 and 50–70 are compacted, the
next boundary is 71 and messages 21–49 are not selected.

34 trigger tests and 37 compactor tests passed, for 71 M5 tests and 208
compaction tests total. Memory/context: 217. Full suite: 517. Ruff clean.

Architectural concern: size-trigger estimation currently scans eligible
messages synchronously. Acceptable for M5; future background orchestration
may optimize this.

------------------------------------------------------------------------

## 48. Build Log Rule Going Forward

From M6 onward, after every completed milestone the order is:

``` text
1. implementation
2. tests
3. review
4. build-log entry
5. only then the next milestone
```

Milestone implementation and build-log work are not combined unless
explicitly requested.

------------------------------------------------------------------------

## 49. Phase 4 Test Corrections and Repository State

The M4 and M5 milestone entries above record the shipped behavior but not the
test corrections made during TDD. They are recorded here so the engineering
record is complete.

M4 (`friday/compaction/test_sqlite_store.py`) — three corrections:

``` text
1. The provenance-rejection tests originally cited out-of-range source
   message IDs (999); the M1 domain model rejects those before storage
   is reached. They now use in-range-but-nonexistent IDs (compaction
   range 1-6 citing message 5) so the M4 store's explicit
   source-message existence check is actually exercised.
2. test_no_memory_db_interaction originally patched FRIDAY_HOME on the
   friday.config module, but FRIDAY_HOME is a class attribute on
   _Config. It now patches the config.config instance.
3. test_conversation_isolation did not request the conversation_id
   fixture, so the second conversation received id 1 and the isolation
   assertion was vacuous. The fixture was added.
```

M5 (`friday/compaction/test_compactor.py`) — three corrections:

``` text
1. "Above threshold" used 20 messages, not 21; corrected to 21 so a
   second bounded window remains outstanding (remaining_messages == 1).
2. "Fewer remaining messages than max_window" needed force=True: after
   the first compaction only 4 messages remained, below the message
   threshold, so a normal trigger would not fire.
3. The duplicate-persistence test required a hidden-preseed store: a
   visible prior compaction advances the boundary, so the
   CompactionAlreadyExistsError path is never reached through the normal
   flow. FakeStore.preseed_hidden simulates the concurrent-duplicate
   case (row exists in storage while the boundary read is stale).
```

Repository state: the most recent git commit is "Phase 3 complete". The
entire Phase 4 M1-M5 code — the `friday/compaction/` package and the
`COMPACTION_*` additions in `friday/config.py` — is uncommitted work.

Design artifact note: a Phase 4 design document
(`/tmp/opencode/PHASE4_DESIGN.md`, Revision 2, 822 lines) was regenerated
before M1 and maintained through M5, recording the locked/OPEN Phase 4
decisions that the milestone entries reference (hybrid trigger, category
set, provenance rules, no `promoted` flag, promotion path). It lived under
`/tmp` and is no longer present; its decisions are preserved in entries
43-48 and `docs/DECISION_LOG.md` ADR-024.

------------------------------------------------------------------------

## 50. M6.1 — Promotion Ledger Domain Model

M6.1 built the promotion-ledger domain layer defined by ADR-025 — the
domain representation for tracking the promotion of a single
`CompactionItem`.

Files:

``` text
friday/compaction/promotion.py
friday/compaction/test_promotion.py
friday/compaction/__init__.py
```

Implemented:

``` text
CompactionItemCategory    FACTS / DECISIONS / CHANGES / OPEN_QUESTIONS
PromotionStatus           PENDING / PROMOTED / REJECTED
PromotionResolutionKind   CREATE / SUPERSEDE
CompactionPromotion       immutable promotion-ledger entry
```

The ledger is keyed by the deterministic `CompactionItem.item_id`; no
separate promotion ID replaces it and no `promoted` boolean was added to
`CompactionItem`.

State transitions:

``` text
PENDING → PROMOTED
PENDING → REJECTED
REJECTED → PENDING   (explicit reconsideration only)
```

PROMOTED is terminal. Transient failures remain PENDING while incrementing
`retry_count` and recording `last_error`; there is no separate FAILED
state. State transitions return new immutable instances; arbitrary mutation
is not allowed.

Validation covers: non-empty `item_id`/`compaction_id`; category/status/
resolution-kind enums; non-negative `retry_count`; timezone-aware
timestamps with `created_at`/`updated_at` ordering; memory IDs (present
only when promoted); PROMOTED requires resulting memory ID(s); REJECTED
requires a resolution reason; `resolution_kind` only valid when promoted;
terminal-state rules.

62 focused M6.1 tests passed. 270 compaction tests total. Memory/context:
217. Full suite: 579. Ruff clean.

Architectural notes:

``` text
1. Category promotability policy (ADR-025: summary/open_questions never
   promoted, etc.) is deliberately NOT encoded in the domain model. That
   belongs to the future promotion orchestrator.
2. Rejection reason is currently a current-state field; historical
   promotion-attempt history remains a storage concern.
3. Test fixtures must use timestamps compatible with the model's
   created_at/updated_at ordering validation (a fixed NOW later than the
   wall clock triggers the ordering guard on transition methods).
```

M6.1 IMPLEMENTATION COMPLETE.

M6.2 NOT STARTED.

------------------------------------------------------------------------

## 51. M6.2 — SQLite Promotion Ledger

M6.2 added persistent storage for `CompactionPromotion` ledger entries in
conversations.db, per ADR-025. The domain model remains the source of truth
for validation and state transitions; this store is a persistence layer
only.

Files:

``` text
friday/compaction/promotion_store.py
friday/compaction/test_promotion_store.py
friday/compaction/exceptions.py
friday/compaction/__init__.py
```

Implemented:

``` text
SQLitePromotionStore
save()                 insert a new ledger entry (item_id-keyed)
replace()              persist a new immutable state after a domain transition
get()                  retrieve by item_id or None
list_for_compaction()  deterministic ordering
```

The promotion ledger lives in `~/.friday/data/conversations.db` alongside
compactions and raw conversation history. There is no memory.db
interaction. The ledger is keyed by `CompactionItem.item_id`; no generated
promotion ID and no `promoted` boolean.

Schema additions (idempotent `CREATE TABLE IF NOT EXISTS`):

``` text
compaction_promotions              item_id PRIMARY KEY, category/status/
                                   resolution_kind/resolution_reason/
                                   retry_count/last_error/timestamps,
                                   CHECK constraints, FKs to
                                   compaction_items and
                                   conversation_compactions (CASCADE)
promotion_resolved_memory_ids      child table (item_id, memory_id,
                                   ordinal) preserving normalized order
```

Foreign keys and cascades preserve compaction → promotion integrity.
Resolved memory IDs are stored as cross-database audit references only;
`promotion_resolved_memory_ids` intentionally has no FK to memory.db
because the databases are separate.

API shape: no public `delete()` (promotion history is audit state) and no
generic mutable `update()`. `replace()` exists because the domain model is
immutable and transitioned states share the item_id key; it persists the
resulting new immutable object. Idempotency decisions belong to the future
orchestrator, not storage.

Storage behavior:

``` text
- enum values stored deterministically (.value) and reconstructed via Enum()
- timestamps preserve timezone information (isoformat microseconds, aware)
- collection ordering preserved deterministically via child-table ordinals
- database uniqueness on item_id is authoritative for concurrent saves
- duplicate item_id becomes typed PromotionAlreadyExistsError
- corrupt persisted data becomes typed PromotionCorruptError
- individual writes are transactional; no cross-database transactions
- no promotion decisions in storage (promotability, candidates, memory
  creation, supersession, scope, confidence, timing all deferred)
```

39 M6.2 storage tests passed. 309 compaction tests total. Memory/context:
217. Full suite: 618. Ruff clean.

Architectural concerns:

``` text
1. compaction_items.item_id is globally unique, so deterministic item IDs
   must remain collision-resistant across all compactions.
2. promotion_resolved_memory_ids intentionally has no FK to memory.db
   because the databases are separate.
3. replace() rewrites child memory-ID rows on state transitions, which is
   acceptable for the small ledger.
4. Domain timestamp fixtures must respect updated_at >= created_at.
```

M6.2 IMPLEMENTATION COMPLETE.

M6.3 NOT STARTED.

------------------------------------------------------------------------

## 52. M6.3 — Conversation Memory Promotion

M6.3 added the explicit promotion orchestrator defined by ADR-025 — the
component that turns a `ConversationCompaction` into durable memory through
the existing memory pipeline (`MemoryCandidate` → `MemoryResolver` →
`DurableMemoryManager.apply_batch` → memory.db) and records the outcome in
the promotion ledger.

Files:

``` text
friday/compaction/promoter.py
friday/compaction/test_promoter.py
friday/compaction/__init__.py
```

Implemented:

``` text
ConversationMemoryPromoter
```

`ConversationMemoryPromoter` is dependency-injected: it accepts a promotion
ledger store, a memory manager, and a memory resolver via protocols
(`PromotionLedgerStore`, `MemoryManager`, `PromotionResolver`). Promotion is
explicit only — a synchronous operation invoked by the caller; there is no
automatic/background trigger.

Category policy:

``` text
FACTS and DECISIONS are eligible.
SUMMARY is never converted to a CONVERSATION_SUMMARY memory.
CHANGES are not automatically promoted (changes_not_promotable).
OPEN_QUESTIONS are not promoted (open_questions_not_promotable).
```

Facts use deterministic subject classification (`_classify_fact_type`).
Decisions become PROJECT_DECISION and require a deterministic `project_id`
(`decision_requires_project_id`). `project_id` is caller-supplied only and is
never derived from content or an LLM. Promotion confidence starts at
EXPLICIT.

Compaction provenance (conversation_id + source_message_ids) becomes the
`MemoryCandidate` provenance. Every eligible candidate passes through the
injected `MemoryResolver`, and every accepted resolution is applied through
`DurableMemoryManager.apply_batch()`. CREATE and SUPERSEDE become PROMOTED
ledger states; resolver rejection becomes REJECTED; items already
PROMOTED/REJECTED become NOOP; transient failures remain PENDING with retry
information.

Reconciliation: `_find_matching_memory()` recognizes an existing durable
memory by identical deterministic provenance/content, so the
memory-success/ledger-failure boundary is safe — a retry never blindly
duplicates a memory. No cross-database transaction is claimed; memory writes
commit atomically inside memory.db while the ledger row is updated in
conversations.db.

35 M6.3 tests passed, including an integration test using real SQLite
components. 344 compaction tests total. Memory/context: 217. Full suite:
653. Ruff clean.

Architectural concern:

``` text
1. Reconciliation relies on matching existing durable memory by the
   deterministic provenance/content strategy.
2. _load_existing() currently queries active memories per distinct
   scope/project context; acceptable at current scale.
```

M6.3 IMPLEMENTATION COMPLETE.

M6.4 NOT STARTED.

------------------------------------------------------------------------

## 53. M6.4 — Compaction Promotion Integration + Failure Verification

M6.4 was a TEST/HARDENING phase for the promotion path defined by ADR-025.
It made NO source-code changes.

Files:

``` text
friday/compaction/test_m64_integration.py
friday/compaction/test_m64_architecture.py
```

Verified against real temporary SQLite databases:

``` text
- end-to-end CREATE
- end-to-end SUPERSEDE
- REJECT
- ineligible categories
- project boundaries
- provenance
- idempotent repeated promotion
- memory-success / ledger-failure reconciliation
- memory failure isolation
- apply_batch atomicity
- multiple-item behavior
- concurrency / repeated promotion
- crash-boundary behavior
- compaction immutability
- persistence across reopen
- corruption detection
- architectural / import invariants
- separation of conversations.db and memory.db
- absence of promoted boolean
- absence of cross-database transaction claims
```

Results:

``` text
59 new M6.4 tests passed.
403 friday/compaction tests total.
217 friday/memory + friday/context tests.
712 full-suite tests.
Ruff clean.
No source-code changes.
```

Unresolved concerns:

``` text
1. First-run concurrent schema initialization of a fresh database can race
   around table creation; production databases are initialized once at
   startup and tests pre-initialize them.
2. Concurrency was verified at thread level; multi-process concurrency was
   outside M6.4 scope.
```

M6.4 IMPLEMENTATION COMPLETE.

M6 COMPLETE — FINAL VALIDATION PASSED.
