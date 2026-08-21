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

------------------------------------------------------------------------

## 54. M7.1a — FRIDAY Context Injection into LiveKit

M7.1a proved the existing ContextManager can control the context sent to the
LiveKit LLM through the ``Agent.on_user_turn_completed(turn_ctx, new_message)``
extension point, without replacing the LiveKit voice, LLM, MCP tool pipeline,
TTS, VAD, or interruption handling.

Files changed:

``` text
friday/core/session.py            (AssistantSession; rewritten context assembly)
friday/core/test_m71a_context_integration.py   (24 focused + integration tests)
agent_friday.py                   (FridayAgent.on_user_turn_completed wiring)
```

Architectural decision (verified against livekit-agents 1.6.9 source):

``` text
1. LiveKit passes Agent.on_user_turn_completed a MUTABLE COPY of
   agent.chat_ctx (temp_mutable_chat_ctx) that does NOT include the current
   user message. The copy is what _generate_reply passes to the LLM
   (agent_activity._generate_reply(chat_ctx=temp_mutable_chat_ctx)), so the
   replacement context is applied IN PLACE to turn_ctx.items. Calling
   update_chat_ctx() instead would NOT affect the current generation and
   would permanently replace the agent accumulated history with the
   budgeted subset.
2. The current user message is NOT added by FRIDAY. LiveKit inserts it into
   the LLM-call context after this hook returns
   (_pipeline_reply_task_impl chat_ctx.insert(new_message)), and into
   agent.chat_ctx only after the reply is scheduled.
3. FunctionCall / FunctionCallOutput items are preserved as NATIVE LiveKit
   items (walked from turn_ctx.items, inserted verbatim) — never flattened
   into text and never dropped. The budgeted ChatMessage subset (selected by
   ContextManager) plus all tool items retain their original chronological
   order.
4. System instructions are emitted as a single system message; LiveKit does
   not re-inject instructions in the normal turn flow (no update_chat_ctx is
   called), so there is no duplicate system prompt.
5. Context assembly is synchronous and failure-safe: any exception is
   caught in FridayAgent.on_user_turn_completed and logged as a warning,
   leaving turn_ctx untouched so LiveKit falls back to its default context.
6. No background work: assemble_context_for_turn never spawns asyncio tasks.
```

Tests:

``` text
- LiveKit message conversion (3)
- ContextSnapshot to replacement context, all sections (3)
- ContextManager invoked correctly (1)
- Durable memory and project context reach the context (2)
- Budgeted context replaces unbounded history (1)
- Tool items preserved natively: not flattened, ordering kept, coexists
  with memory (4)
- In-place application: turn_ctx.items is the custom context; current user
  message added exactly once by LiveKit; system instructions once; no
  background tasks (4)
- Graceful degradation on memory/project/shrinker failure (3)
- Tools still passed separately to llm.chat (1)
- Integration: fake LLM receives budgeted context with memory + project
  context, and native tool history (2)
```

Results:

``` text
24 M7.1a tests passed.
620 friday/context + friday/memory + friday/compaction tests.
736 full-suite tests.
Ruff clean on changed files.
```

Discovered LiveKit 1.6.9 constraints recorded for M7.1b:

``` text
1. Preemptive generation is ENABLED by default (turn.py
   _PREEMPTIVE_GENERATION_DEFAULTS). Replacing the turn context each turn
   invalidates the preemptive candidate (is_equivalent compares item IDs,
   types, and payloads), so preemptive generation will not match and its
   latency benefit is effectively disabled while context injection is active.
2. turn_ctx.messages() drops FunctionCall/FunctionCallOutput; tool history
   must be preserved from turn_ctx.items explicitly (done in M7.1a).
3. update_instructions() keys on reserved id "lk.agent_task.instructions";
   not used in M7.1a because update_chat_ctx is not called in the turn flow.
```

M7.1b NOT STARTED.

------------------------------------------------------------------------

## 55. M7.1b.1 — Post-Turn Background Task Coordination

M7.1b.1 created the minimal lifecycle/task-coordination layer in
AssistantSession so post-turn background work can be safely scheduled,
tracked, and shut down. This is ONLY task coordination — no memory
extraction, compaction, or promotion is connected yet.

Files changed:
``` text
friday/core/session.py                 (AssistantSession: added _schedule_background, _wait_background_tasks, stop() coordination)
friday/core/test_m71b1_background_tasks.py   (14 focused tests)
```

Task ownership design:
- Private `_background_tasks: set[asyncio.Task]` tracks all owned tasks
- `_schedule_background(coro)` creates task, retains it, removes on completion, observes exceptions
- `_stopping` flag prevents new work after shutdown begins
- `_wait_background_tasks()` cancels and awaits all tasks with timeout
- `stop()` is idempotent: prevents new tasks, cancels/awaits owned tasks, then closes stores

Scheduling seam:
```python
# Future post-turn code will call:
AssistantSession._schedule_background(some_coro())
```

Exception handling:
- Done callback removes task from tracking
- Cancelled tasks logged at DEBUG level
- Failed tasks logged at WARNING level with exc_info
- "Task exception was never retrieved" warnings avoided
- Voice session never crashes from background task failure

Shutdown sequence:
1. Set `_stopping = True` (prevents new scheduling)
2. Cancel all non-done owned tasks
3. Await with 5s timeout (gather + return_exceptions)
4. Clear tracking set
5. Close conversation/memory stores

Tests added (14):
- test_background_task_is_tracked
- test_completed_task_is_removed
- test_multiple_background_tasks_are_independent
- test_background_task_exception_is_observed
- test_background_task_failure_does_not_affect_session
- test_stop_cancels_background_tasks
- test_stop_awaits_background_tasks
- test_stop_is_idempotent
- test_new_tasks_rejected_after_stop
- test_completed_tasks_do_not_break_stop
- test_cancellation_is_not_logged_as_failure
- test_store_cleanup_still_occurs
- test_start_then_stop_with_background_task
- test_context_assembly_still_works

Results:
``` text
14 M7.1b.1 tests passed.
736 full-suite tests (previously 736).
Ruff clean on changed files.
```

Architectural notes:
1. No generic scheduler/TaskManager introduced — minimal internal mechanism only
2. Uses existing asyncio loop; no threading, no new event loop
3. No public result API — future workers handle their own results
4. Cancellation is cooperative; CancelledError not swallowed
5. M7.1a context assembly integration preserved and tested

M7.1b.1 COMPLETE.
M7.1b.2 NOT STARTED.

------------------------------------------------------------------------

## 56. M7.1b.2 — Post-Turn Memory Extraction Integration

M7.1b.2 connected the existing MemoryExtractor → MemoryResolver → DurableMemoryManager pipeline to the post-turn background lifecycle created in M7.1b.1. Memory extraction runs in background after every N assistant turns (configurable via EXTRACTION_CADENCE_TURNS, default 10), using the deterministic conversation_id and active_project_id from AssistantSession.

Files changed:
``` text
friday/core/session.py                    (AssistantSession: added _memory_extractor, _memory_resolver, on_assistant_message_persisted, _run_memory_extraction)
friday/core/test_m71b2_memory_extraction.py   (23 focused tests)
agent_friday.py                          (wired on_assistant_message_persisted call after assistant message persistence)
```

Trigger interval:
- Every N turns (config.EXTRACTION_CADENCE_TURNS = 10 default)
- Only fires after assistant message is persisted (via on_assistant_message_persisted)
- Not on every turn, not on partial/streaming output

Lifecycle boundary:
- assistant message persisted (conversation_item_added event with role="assistant")
- This is the turn-complete boundary per M7.1b readiness review

Extraction message window:
- Uses existing SQLiteConversationStore.get_recent_messages()
- Window size = EXTRACTION_WINDOW_MESSAGES * 2 (default 40 messages)
- Converts to (message_id, role, content) tuples for extractor

Conversation ID:
- From AssistantSession._conversation_id (stable for session lifetime)
- Set at session.start(), persists across turns

Project ID:
- From AssistantSession.active_project_id (deterministic, from ProjectService)
- Never inferred from LLM output or content
- Passed as project_id=None when no active project

Extractor → Resolver → Memory Manager flow:
1. MemoryExtractor.extract(messages, conversation_id, project_id) → MemoryCandidate[]
2. MemoryResolver.resolve(candidates, existing_memories) → Resolution[]
3. DurableMemoryManager.apply_batch(resolutions) → persisted memories
4. All failures isolated via try/except in background task

Provenance:
- source_conversation_id from session._conversation_id
- source_message_ids from extraction window message IDs
- Preserved through Candidate → Resolution → Memory

Replay/idempotency:
- MemoryResolver deduplicates (exact, containment, fuzzy)
- apply_batch is transactional
- Same content extracted again → REJECT via resolver
- Same provenance extracted again → RECONCILED (existing memory recognized)

Failure isolation:
- Extraction failures logged, next cadence retries
- Resolver failures logged, memory.db failures logged
- Voice session never crashes from background failures
- Stores closed only after background tasks handled

Tests added (23):
- test_memory_extraction_scheduled_at_interval
- test_memory_extraction_runs_after_assistant_persistence
- test_extractor_receives_correct_conversation_id
- test_extractor_receives_deterministic_project_id
- test_extractor_works_without_project_id
- test_extractor_receives_conversation_messages
- test_memory_candidate_reaches_resolver
- test_created_memory_persists
- test_memory_provenance_is_preserved
- test_user_memory_without_project_id
- test_project_memory_gets_project_id
- test_duplicate_extraction_does_not_duplicate_memory
- test_superseding_memory_works
- test_extractor_failure_isolated
- test_resolver_failure_isolated
- test_memory_store_failure_isolated
- test_background_task_is_owned_by_session
- test_shutdown_cancels_memory_extraction
- test_memory_extraction_does_not_modify_context
- test_memory_extraction_does_not_trigger_compaction
- test_memory_extraction_does_not_trigger_promotion
- test_full_memory_extraction_integration

Results:
``` text
23 M7.1b.2 tests passed.
773 full-suite tests.
Ruff clean on changed files.
```

Architectural notes:
1. No generic scheduler/MemoryService — uses M7.1b.1 task coordination directly
2. Uses existing asyncio loop; no threading, no new event loop
3. No compaction or promotion triggered (M7.1b.3+)
4. M7.1a context assembly preserved and tested

M7.1b.2 COMPLETE.
M7.1b.3 NOT STARTED.

------------------------------------------------------------------------

## 57. M7.1b.3 — Post-Turn Compaction Integration

M7.1b.3 connected the existing ConversationCompactor → SQLiteCompactionStore pipeline to AssistantSession's post-turn background lifecycle. Compaction evaluation runs in background after every completed assistant turn, using the deterministic conversation_id from AssistantSession and persisted messages from SQLiteConversationStore.

Files changed:
``` text
friday/core/session.py                    (AssistantSession: added _compactor, on_assistant_message_persisted_for_compaction, _run_compaction_check)
friday/core/test_m71b3_compaction.py          (26 focused tests)
```

Trigger frequency:
- Evaluated after every completed assistant turn (same boundary as M7.1b.2)
- No additional cadence; existing ConversationCompactor.should_compact() decides whether work is needed
- Not on every turn, not on partial/streaming output

Lifecycle boundary:
- assistant message persisted (conversation_item_added event with role="assistant")
- This is the turn-complete boundary per M7.1b readiness review

Message source:
- Uses existing SQLiteConversationStore.get_recent_messages()
- Retrieves complete conversation history for boundary evaluation
- Converts to compactor Message protocol format

Conversation ID:
- From AssistantSession._conversation_id (stable for session lifetime)
- Set at session.start(), persists across turns

Project ID:
- Not required for compaction (M7.1b.4 handles project-aware promotion)
- Compaction is conversation-scoped

Compactor integration:
1. ConversationCompactor.compact(messages, conversation_id=..., force=False)
2. Evaluates should_compact() with hybrid message/size thresholds
3. If triggered: extracts bounded window, persists ConversationCompaction
4. Returns CompactionResult (compacted, compaction, remaining_messages)
5. All failures isolated via try/except in background task

Bounded-window behavior:
- Only one bounded window per invocation (max_window = 20)
- Remaining messages left for later lifecycle invocation
- Preserves M5 design intent

Idempotency:
- Rely on existing M5 mechanisms
- Persisted compaction boundary via next_compaction_start()
- Deterministic compaction IDs
- Duplicate-save handling via CompactionAlreadyExistsError
- No new "compacted" flag on messages

Failure isolation:
- Compaction failures logged, voice session never crashes
- Memory extraction and compaction are independent background tasks
- Stores closed only after background tasks handled

Tests added (26):
- test_compaction_check_runs_after_assistant_persistence
- test_below_threshold_is_noop
- test_message_threshold_triggers_compaction
- test_size_threshold_triggers_compaction
- test_compaction_uses_persisted_messages
- test_compaction_uses_correct_conversation_id
- test_compaction_respects_existing_boundary
- test_compaction_respects_max_window
- test_only_one_window_compacted_per_invocation
- test_remaining_messages_are_not_compacted_in_same_task
- test_repeated_compaction_is_idempotent
- test_compaction_failure_is_isolated
- test_memory_failure_does_not_block_compaction
- test_compaction_failure_does_not_block_memory
- test_compaction_runs_as_background_task
- test_compaction_task_is_owned_by_session
- test_shutdown_cancels_compaction
- test_cancellation_is_not_logged_as_compaction_failure
- test_compaction_does_not_modify_context
- test_compaction_does_not_trigger_promotion
- test_compaction_does_not_modify_memory
- test_compaction_persists_in_conversations_db
- test_full_compaction_integration
- test_memory_and_compaction_independence
- test_memory_fails_compaction_succeeds
- test_compaction_fails_memory_succeeds

Results:
``` text
26 M7.1b.3 tests passed.
798 full-suite tests.
Ruff clean on changed files.
```

Architectural notes:
1. No generic CompactionScheduler/CompactionService — uses M7.1b.1 task coordination directly
2. Uses existing asyncio loop; no threading, no new event loop
3. No promotion triggered (M7.1b.4)
4. M7.1a context assembly and M7.1b.2 memory extraction preserved and tested

M7.1b.3 COMPLETE.
M7.1b.4 NOT STARTED.

------------------------------------------------------------------------

## 58. M7.1b — Runtime Architecture Review (read-only)

A read-only runtime architecture review of the M7.1b post-turn lifecycle
was performed against livekit-agents 1.6.9 installed source, the `friday/`
code, the 62 M7.1b tests, and the architecture docs. No source, config, or
doc file was modified by the review itself.

Scope verified:

- LiveKit turn lifecycle (1.6.9): `on_user_turn_completed` receives
  `agent.chat_ctx.copy()`; the LLM call consumes that copy in place; the
  assistant message is committed to `agent.chat_ctx` and emitted via
  `conversation_item_added` only after reply + TTS playout finish.
- The assistant-persisted boundary is the correct turn-complete seam for
  M7.1b.2/M7.1b.3.
- M7.1a in-place context replacement is correct and consumed by the LLM
  call; preemptive generation is invalidated every turn (expected cost).
- Background task coordination (M7.1b.1), extraction (M7.1b.2), and
  compaction (M7.1b.3) are sound, isolated, and covered by 62 passing
  tests (13 + 23 + 26), 1 warning.
- ADR-024 lives in DECISION_LOG.md (no `docs/ADR-024.md` file). ADR-025
  promotion machinery is complete and compliant. ADR-026 items remain
  future-direction only.

### M7.1b.4 VERDICT: GO WITH FIXES

### MUST FIX BEFORE M7.1b.4

1. No production `LLMBackend` exists. `friday/ai/backend.py` defines only
   the protocol and defers the adapter to the assistant/session layer.
   `create_assistant_session()` is called without `llm_backend`
   (agent_friday.py), so `_memory_extractor` and `_compactor` are None in
   the runtime and both pipelines no-op (they only run in tests with fake
   backends). M7.1b.4 consumes compaction output, so this must be closed:
   add a LiveKit-LLM → `LLMBackend.complete()` adapter and pass it in.
2. `on_assistant_message_persisted_for_compaction` is never called in
   agent_friday.py — only `on_assistant_message_persisted` is wired.
   Compaction therefore never runs in production even with a backend.
   Wire the compaction hook on the same assistant-persisted boundary.

### GO WITH FIXES (non-blocking, address alongside M7.1b.4)

3. Replace hardcoded `message_id=0` with the real saved `Message.id` (or
   drop the unused parameter).
4. Replace the bare `asyncio.create_task` trigger with a tracked seam so
   no work runs after stores close during shutdown.
5. Flag the `get_recent_messages(limit=1000)` compaction fetch as
   inefficient; document the latent >1000-message silent-skip edge case.
6. Drop the redundant `_window_size * 2` extraction fetch.
7. Accept/measure the per-turn preemptive-generation invalidation cost.
8. Close `_compaction_store` in `AssistantSession.stop()`.

### M7.1b.4 PLAN (PLANNING ONLY — NOT IMPLEMENTED)

Objective: connect the ADR-025 promotion machinery downstream of M7.1b.3
compaction, executed as an explicit background step strictly after
successful compaction persistence, using deterministic caller-supplied
project scope.

Steps (when authorized):

1. Add a `LiveKitLLMBackend` adapter implementing `LLMBackend.complete()`
   (sync wrapper around the LiveKit LLM `chat()`), and pass it to
   `create_assistant_session(llm_backend=...)` in agent_friday.py
   (MUST FIX 1).
2. Wire `on_assistant_message_persisted_for_compaction` in agent_friday.py
   on the same assistant-persisted boundary as extraction (MUST FIX 2).
3. In AssistantSession: construct `ConversationMemoryPromoter` with
   `SQLitePromotionStore`, `MemoryResolver`, and `DurableMemoryManager`;
   after `compactor.compact(...)` reports `compacted=True`, run
   `promote(compaction, conversation_id=..., project_id=self.active_project_id)`
   in the same background task; log ledger outcomes.
4. Apply the GO-WITH-FIXES items (3-8) as low-risk hygiene.
5. Tests: promoter-after-compaction integration, promotion skips with no
   project_id (USER_FACT proceeds, PROJECT_FACT/DECISION skip), duplicate
   promotion no-op via PENDING/PROMOTED/REJECTED ledger, failure isolation
   (memory.db vs ledger), idempotent re-run, shutdown cancellation.

Non-goals: no automatic background promotion beyond the per-compaction
explicit step; no cross-database transactions (ADR-025); no new memory
types; no vector search/embeddings.

Verification: full pytest suite, Ruff clean, 62 existing M7.1b tests plus
new M7.1b.4 tests, live smoke test that extraction and compaction now
actually run in the voice runtime.

Results:
``` text
Review read-only; 62 M7.1b tests passed (13 + 23 + 26), 1 warning.
Full suite at M7.1b.3: 798 tests.
```

M7.1b.4 NOT STARTED (plan only, pending authorization).
```

## 59. M7.1b.3.1 — Production Runtime Wiring

**Scope.** Make the dormant M7.1b.2 memory-extraction pipeline and M7.1b.3
compaction pipeline actually execute in the production FRIDAY runtime
(LiveKit voice agent). M7.1b.4 (promotion) was NOT touched.

**Protocol correction (approved by user).** `LLMBackend.complete()` became
`async def` because every LiveKit LLM plugin exposes chat as an async
operation; the previous sync protocol could only be bridged unsafely.

**Files changed:**
- `friday/ai/backend.py` — `LLMBackend.complete` is now `async`.
- `friday/ai/providers/__init__.py` — added `LiveKitLLMBackend` (wraps a
  configured LiveKit LLM; sends `system` + `user` as a two-message
  `ChatContext`, `await llm.chat(chat_ctx=ctx).collect()` → `.text`) and
  `build_llm_backend()`.
- `friday/memory/extractor.py` — `MemoryExtractor.extract`/`_ask_llm` async.
- `friday/compaction/extractor.py` — `ConversationCompactionExtractor.extract` async.
- `friday/compaction/compactor.py` — `ConversationCompactor.compact` async.
- `friday/memory/resolver.py`, `friday/context/shrinker.py` — remain sync
  (never given an async backend in production); each guards against an async
  backend by closing the leaked coroutine instead of using it as a string.
- `friday/core/session.py` — new sync dispatcher `on_assistant_persisted()`
  schedules both post-turn hooks through `_schedule_background()`; the dead
  `message_id` parameter was removed from `on_assistant_message_persisted`;
  `_schedule_background` now closes a rejected coroutine (fixes the
  "coroutine was never awaited" warning); `_run_memory_extraction` and
  `_run_compaction_check` await the pipelines; `stop()` closes
  `_compaction_store`.
- `agent_friday.py` — passes `llm_backend=build_llm_backend()` to
  `create_assistant_session()` and replaces the untracked
  `asyncio.create_task(..., message_id=0)` with
  `assistant_session.on_assistant_persisted()`.

**Why these and not others.** Making `ContextManager.assemble` async would
have altered the M7.1a context-injection signature and churned ~30 test
call sites; making `MemoryResolver.resolve` async would have forced M6.3
`promote()` async across ~50 call sites. Both are dead/deferred paths in
production (`shrinker=None`, resolver has no backend), so they stay sync with
a coroutine guard. This is reported here as the scope of the async ripple.

**Tests.** 21 new tests in `friday/core/test_m71b31_runtime_wiring.py`
covering the adapter (protocol conformance, expected text, memory/compaction
pipelines running through it), session wiring (extractor/compactor
constructed from the production backend), the dispatcher (both tasks
scheduled, tracked, actually invoked, failure isolation both directions),
lifecycle (rejected coroutine closed, dead `message_id` removed,
`_compaction_store` closed on stop, stop waits before cleanup), no
promotion triggered, and a full production-path integration test
(configured LLM → adapter → AssistantSession → persisted records in memory.db
and conversations.db). Fakes updated to `async def complete` in the
memory/compaction/context/core suites.

Results:
``` text
Full suite: 819 tests passed.
Ruff: All checks passed (agent_friday.py, friday/ai, friday/memory,
      friday/compaction, friday/context, friday/core).
No RuntimeWarning "coroutine was never awaited" (verified with
      -W error::RuntimeWarning on M7.1b.1 + M7.1b.3.1).
```

M7.1b.3.1 COMPLETE.
M7.1b.4 NOT STARTED.

## 60. M7.1b.4.1 — Promotion Dependency Construction

**Scope.** Construct the promotion dependencies in `AssistantSession` so the
orchestrator is available for later wiring. No promotion execution is wired;
M7.1b.4.2 will invoke `promote()` after successful compaction.

**Files changed:**
- `friday/core/session.py` — added imports for `ConversationMemoryPromoter`
  and `SQLitePromotionStore`; in `__init__`, constructs
  `self._promotion_store = SQLitePromotionStore()` (uses the same
  `conversations.db` as the conversation and compaction stores) and
  `self._promoter = ConversationMemoryPromoter(
      promotion_store=self._promotion_store,
      memory_manager=self._memory_manager,
      resolver=self._memory_resolver,
  )`.
- `friday/core/test_m71b41_promotion_construction.py` — 10 new tests
  verifying: promotion store construction, same `conversations.db` path,
  promoter construction, injection of existing `DurableMemoryManager` and
  `MemoryResolver`, no promotion during construction, and all pre-existing
  pipelines unchanged.
- `friday/core/test_m71b2_memory_extraction.py` — updated
  `test_memory_extraction_does_not_trigger_promotion` to verify promoter
  exists but is not invoked.
- `friday/core/test_m71b3_compaction.py` — updated
  `test_compaction_does_not_trigger_promotion` similarly.

**Database isolation verified:**
- Promotion store uses `conversations.db` (same as conversation + compaction
  stores).
- Memory store remains separate `memory.db`.
- No cross-database connections in promotion store.

**No promotion execution:**
- `promote()` is NOT called anywhere.
- `on_assistant_persisted()` and `_run_compaction_check()` unchanged.
- Tests verify promoter exists but `promote()` not invoked.

**Tests:**
- 10 new M7.1b.4.1 tests in `test_m71b41_promotion_construction.py`.
- 2 existing tests updated to reflect new construction.
- All existing M7.1a, M7.1b.1, M7.1b.2, M7.1b.3, M7.1b.3.1 tests pass.
- Full suite: 829 tests passed.
- Ruff: All checks passed.

**Results:**
```
Full suite: 829 tests passed.
Ruff: All checks passed.
```

M7.1b.4.1 COMPLETE.
M7.1b.4.2 NOT STARTED.

## 61. M7.1b.4.2 — Runtime Compaction → Memory Promotion

**Scope.** Wire the promotion path downstream of successful compaction in the live runtime, using the `ConversationMemoryPromoter` constructed in M7.1b.4.1. Promotion runs strictly after compaction persistence succeeds, as a separate background task owned by `AssistantSession`.

**Files changed:**
- `friday/core/session.py` — imports for `ConversationCompaction`, `ConversationMemoryPromoter`, `SQLitePromotionStore`; constructs `_compaction_store` and promotion pipeline in `__init__`; `stop()` closes both stores; `_schedule_background` closes rejected coroutines to avoid "coroutine was never awaited" warnings; `_run_compaction_check` awaits `compactor.compact()` and, on `result.compacted`, schedules `self._run_promotion(result.compaction)` as a new background task; `_run_promotion` calls `promoter.promote(compaction, project_id=self.active_project_id)` and logs promoted/skipped/rejected counts.

**Key behaviors implemented:**
- Successful persisted compaction now triggers promotion via `ConversationMemoryPromoter`.
- Promotion happens only after compaction persistence succeeds (separate background task).
- `project_id` comes from `AssistantSession.active_project_id` (deterministic `ProjectService` source).
- Promotion runs through `AssistantSession` background-task ownership (same `_schedule_background` seam).
- Promotion failures are isolated (try/except in `_run_promotion`, logged, voice session never crashes).
- Promotion ledger remains authoritative (`SQLitePromotionStore` in `conversations.db`).
- Memory persistence remains atomic through `DurableMemoryManager.apply_batch()`.
- Compaction remains independently persisted (no rollback on promotion failure).
- Promotion store lifecycle/shutdown added to `stop()`.
- Category policy enforced by promoter (FACTS/DECISIONS eligible; SUMMARY/CHANGES/OPEN_QUESTIONS skipped).
- Provenance preserved: `source_conversation_id` + `source_message_ids` from compaction items flow into `MemoryCandidate`.
- Idempotency/reconciliation via promotion ledger (PENDING/PROMOTED/REJECTED) and `_find_matching_memory()`.
- No cross-database transactions; memory writes commit in `memory.db`, ledger updates in `conversations.db`.

**Tests:**
- 2 new M7.1b.4.2 tests in `friday/core/test_m71b42_promotion_runtime.py`:
  - `test_successful_compaction_triggers_promotion` — verifies promotion background task fires after compaction.
  - `test_no_compaction_does_not_trigger_promotion` — verifies no promotion when compaction is no-op.
  - `test_promotion_receives_active_project_id` — verifies deterministic `project_id` passed from session.
- All existing M7.1a, M7.1b.1, M7.1b.2, M7.1b.3, M7.1b.3.1, M7.1b.4.1 tests pass.
- Full suite: 832 tests passed (3 new tests added).
- Ruff: All checks passed on changed files.

**Remaining concerns (unchanged from M6.4/M7.1b review):**
1. First-run concurrent schema initialization of a fresh database can race around table creation; production databases are initialized once at startup and tests pre-initialize them.
2. Concurrency was verified at thread level; multi-process concurrency was outside scope.

**Results:**
```
Full suite: 832 tests passed.
Ruff: All checks passed.
```

M7.1b.4.2 COMPLETE.
M7.1b.4 COMPLETE.

---

## 62. M7 Complete — M8 Ready

M7 assistant-runtime foundation is complete and frozen.

M8 Master Agent Orchestration roadmap is documented in ARCHITECTURE.md §16d
and FUTURE_IDEAS.md. M8.1 is NOT STARTED.

Milestone status:

M7.1a       COMPLETE
M7.1b.1     COMPLETE
M7.1b.2     COMPLETE
M7.1b.3     COMPLETE
M7.1b.3.1   COMPLETE
M7.1b.4.1   COMPLETE
M7.1b.4.2   COMPLETE
M7.1b.4     COMPLETE

M8.1        NOT STARTED
