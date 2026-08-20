# M7 READINESS REVIEW — DETERMINE THE NEXT FRIDAY SUBSYSTEM

> **READ-ONLY ARCHITECTURAL INVESTIGATION**  
> No source files modified. No tests modified. No configuration modified.

---

## SECTION 1 — CURRENT RUNTIME MAP

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           FRIDAY RUNTIME ARCHITECTURE                        │
└─────────────────────────────────────────────────────────────────────────────┘

USER VOICE INPUT (LiveKit Room)
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  agent_friday.py — LIVEKIT VOICE AGENT ENTRY POINT                          │
│  ─────────────────────────────────────────────────────────────────────────  │
│  • Builds STT/LLM/TTS providers via friday.ai.providers                    │
│  • Creates FridayAgent with system prompt + MCP server list                │
│  • Opens SQLiteConversationStore → MemoryManager                           │
│  • Creates conversation_id, stores in session.userdata                     │
│  • Registers on("conversation_item_added") handler                         │
│  • Starts AgentSession with FridayAgent                                    │
└─────────────────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  LiveKit AgentSession (voice pipeline)                                      │
│  ─────────────────────────────────────────────────────────────────────────  │
│  • STT → User speech → text                                                │
│  • text → LLM (via LiveKit's LLM plugin — Groq/OpenAI/Ollama)              │
│  • LLM → tool calls (via MCP SSE to server.py)                             │
│  • tool results → LLM                                                      │
│  • LLM → TTS → audio → user                                                │
└─────────────────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  MCP SERVER (server.py) — runs on :8000/sse                                │
│  ─────────────────────────────────────────────────────────────────────────  │
│  • FastMCP registers: filesystem, system, utils, web tools                 │
│  • Tools delegate to friday.filesystem.manager (policy-gated I/O)          │
│  • Tool results return JSON envelope {success, error, data}                │
└─────────────────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PERSISTENCE LAYER                                                          │
│  ─────────────────────────────────────────────────────────────────────────  │
│  ~/.friday/data/conversations.db  ← raw messages + compactions + promotions │
│  ~/.friday/data/memory.db         ← durable memories (separate DB)           │
│  ~/.friday/projects/<id>/         ← project workspace (markdown + JSON)      │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Where subsystems currently sit:**

| Subsystem | Runtime Location |
|-----------|------------------|
| **LLM Backend** | LiveKit plugin (Groq/OpenAI/Ollama) — inside AgentSession |
| **Voice Runtime** | LiveKit Agents (STT→LLM→TTS pipeline) in `agent_friday.py` |
| **MCP Server** | `server.py` — separate process, SSE on port 8000 |
| **Tools** | Registered in `server.py` → delegate to `friday.filesystem.manager` |
| **Conversation Storage** | `SQLiteConversationStore` → `conversations.db` (in `agent_friday.py` entrypoint) |
| **Memory Extraction** | `MemoryExtractor` — **NOT connected to runtime** (library only) |
| **Memory Resolution** | `MemoryResolver` — **NOT connected to runtime** (library only) |
| **Durable Memory** | `DurableMemoryManager` + `SQLiteMemoryStore` — **NOT connected to runtime** |
| **Context Assembly** | `ContextManager` — **NOT connected to runtime** (library only) |
| **Context Shrinking** | `ContextShrinker` — **NOT connected to runtime** (library only) |
| **Compaction** | `ConversationCompactor` — **NOT connected to runtime** (library only) |
| **Compaction Persistence** | `SQLiteCompactionStore` → `conversations.db` — **NOT connected** |
| **Memory Promotion** | `ConversationMemoryPromoter` — **NOT connected to runtime** (library only) |
| **Project Context** | `ProjectService` + `ProjectWorkspace` — **NOT connected to runtime** |

---

## SECTION 2 — IMPLEMENTED VS CONNECTED

| Subsystem | Implemented | Tested | Runtime Connected | Notes |
|-----------|-------------|--------|-------------------|-------|
| LLM Backend (providers) | ✅ | ✅ | ✅ | Via LiveKit plugins in `agent_friday.py` |
| Voice Runtime (STT/LLM/TTS) | ✅ | ⚠️ | ✅ | LiveKit AgentSession runs it |
| MCP Server | ✅ | ✅ | ✅ | `server.py` runs standalone on :8000/sse |
| Tools (filesystem, system, web) | ✅ | ✅ | ✅ | Registered on MCP server, policy-gated |
| Conversation Storage | ✅ | ✅ | ✅ | `SQLiteConversationStore` in `agent_friday.py` entrypoint |
| Memory Extraction | ✅ | ✅ | ❌ | `MemoryExtractor` exists, never called at runtime |
| Memory Resolution | ✅ | ✅ | ❌ | `MemoryResolver` exists, never called at runtime |
| Durable Memory | ✅ | ✅ | ❌ | `DurableMemoryManager` + `SQLiteMemoryStore`; no runtime caller |
| Context Assembly | ✅ | ✅ | ❌ | `ContextManager` exists, never called at runtime |
| Context Shrinking | ✅ | ✅ | ❌ | `ContextShrinker` exists, never called at runtime |
| Compaction (extraction) | ✅ | ✅ | ❌ | `ConversationCompactionExtractor`; never called at runtime |
| Compaction Persistence | ✅ | ✅ | ❌ | `SQLiteCompactionStore`; never called at runtime |
| Compaction Trigger | ✅ | ✅ | ❌ | `trigger.should_compact` + `ConversationCompactor`; never called |
| Memory Promotion | ✅ | ✅ | ❌ | `ConversationMemoryPromoter`; never called at runtime |
| Project Context | ✅ | ✅ | ❌ | `ProjectService` + workspace; never called at runtime |
| Configuration | ✅ | ✅ | ✅ | `config.py` used everywhere |

**Key Finding:** The **only** runtime-connected path is:
- Voice → LiveKit AgentSession → LLM → MCP Tools → Conversation persistence (raw messages only)

Everything built in Phases 2, 3, 4 (Memory, Context, Compaction, Promotion) exists **only as tested libraries** with **zero integration** into the live voice agent.

---

## SECTION 3 — BIGGEST ARCHITECTURAL GAP

**The single biggest missing layer: ASSISTANT CORE / SESSION ORCHESTRATION**

There is **no component** that:
1. Receives a user message (voice or text)
2. Assembles context (recent messages + durable memory + project context)
3. Calls the LLM with that assembled context
4. Handles tool calls and feeds results back
5. Persists the assistant response
6. Triggers extraction/compaction/promotion as background work

The architecture diagrams in `ARCHITECTURE.md` and `DECISION_LOG.md` describe:
```
Input → Intent Classification → Planner → Task Manager → Executor → Memory Manager → Context Pipeline → Prompt Builder → AI
```

**None of this exists.** The current `agent_friday.py` is a thin LiveKit adapter that:
- Delegates **all** reasoning to the LLM via LiveKit's built-in `Agent` class
- Delegates **all** tool execution to the external MCP server
- Only persists raw user/assistant messages to `conversations.db`

The "assistant core" — the layer that should own the conversation lifecycle, context assembly, memory lifecycle, and compaction triggers — **does not exist**.

---

## SECTION 4 — MEMORY / CONTEXT / COMPACTION LIFECYCLE (HYPOTHETICAL TRACE)

### Conversation:
```
User: "I prefer using Vim."
User: "What editor do I prefer?"
... (enough messages to trigger compaction threshold of 20)
```

### What ACTUALLY happens today:

| Stage | What is stored | Where | What is retrieved | What is passed to LLM | What is NOT connected |
|-------|---------------|-------|-------------------|----------------------|----------------------|
| User says "I prefer using Vim." | Raw message: `role=user, content="I prefer using Vim."` | `conversations.db` (messages table) | Nothing (no retrieval) | **Full conversation history** (LiveKit sends all messages in session) | Memory extraction, durable memory |
| Assistant responds | Raw message: `role=assistant, content="..."` | `conversations.db` | Nothing | Full conversation history | Context assembly, memory retrieval |
| User asks "What editor do I prefer?" | Raw message | `conversations.db` | Nothing | Full conversation history | Durable memory lookup — LLM only sees raw history |
| After ~20 messages | Nothing additional | — | Nothing | Full conversation history | **Compaction never triggers**; no background task exists |

### What is ONLY available through direct API calls (not at runtime):
- `MemoryExtractor.extract(messages, conversation_id=..., project_id=...)` → `MemoryCandidate[]`
- `MemoryResolver.resolve(candidates, existing_memories=...)` → `Resolution[]`
- `DurableMemoryManager.apply_batch(resolutions)` → writes to `memory.db`
- `ContextManager.assemble(system_instructions, current_user_message, recent_messages, conversation_id, active_project_id)` → `ContextSnapshot`
- `ContextShrinker.shrink(older_messages, max_units)` → compressed summary
- `ConversationCompactor.compact(messages, conversation_id=..., force=False)` → `CompactionResult`
- `ConversationMemoryPromoter.promote(compaction, project_id=...)` → `PromotionResult`

---

## SECTION 5 — THE "FRIDAY BRAIN" QUESTION

| Decision | Current Owner |
|----------|---------------|
| What context the LLM receives? | **LiveKit AgentSession** — sends entire conversation history (no budget, no selection) |
| Which memories matter? | **Nobody** — durable memory never retrieved |
| Which tools to call? | **LLM** (via LiveKit's function calling) → MCP server |
| Whether a task is complete? | **LLM** — no external orchestrator |
| Whether another model/tool should be invoked? | **LLM** — no planner/router |
| When conversation state is persisted? | **LiveKit event handler** in `agent_friday.py` — only raw messages |
| When compaction occurs? | **Never** — no trigger, no scheduler, no background task |

**Answer: Nothing currently does this.** FRIDAY has **no orchestration/decision layer**. It is a collection of:
- A voice pipeline (LiveKit)
- An MCP tool server
- A conversation log (SQLite)
- **Several excellent but completely disconnected libraries** (memory, context, compaction, promotion, projects)

---

## SECTION 6 — M7 CANDIDATE SCOPES

### Candidate A: Runtime Context Integration (RECOMMENDED)
| Aspect | Detail |
|--------|--------|
| **Name** | M7 — Assistant Core & Context Integration |
| **Objective** | Connect the existing memory/context/compaction libraries to the live voice agent by implementing the missing "assistant core" session layer |
| **Why it matters** | Without this, Phases 2-4 are dead code. The assistant cannot use memory, context budgeting, or compaction |
| **Dependencies** | All Phase 2-4 libraries (already built and tested) |
| **What it would connect** | `agent_friday.py` → `ContextManager` → `MemoryManager`/`DurableMemoryManager` → `ConversationCompactor` (triggered per-turn or background) → `ConversationMemoryPromoter` (explicit) |
| **What it would NOT build** | No OpenCode/Hermes agents, no Agent Registry, no verifier, no local-machine tools, no new databases |
| **Expected complexity** | Medium — wiring existing components, adding per-turn context assembly, background compaction trigger |
| **Testing requirements** | Integration tests: voice message → context assembly → LLM call → memory retrieval → compaction trigger |
| **Architectural risks** | Must not block voice pipeline; compaction/promotion must be async/non-blocking; session state must survive restarts |

### Candidate B: Conversation Persistence & Session Management
| Aspect | Detail |
|--------|--------|
| **Name** | M7 — Conversation Session & Persistence Layer |
| **Objective** | Implement proper session/conversation lifecycle: resume conversations, session metadata, multi-session support |
| **Why it matters** | Current conversation_id is created fresh each voice session; no resume capability |
| **Dependencies** | `SQLiteConversationStore` (exists), needs session model |
| **What it would connect** | Conversation resume, session metadata, active project tracking |
| **What it would NOT build** | Context assembly, memory integration, compaction |
| **Expected complexity** | Low-Medium |
| **Architectural risks** | Session model might duplicate what ContextManager already assumes |

### Candidate C: Background Task Runtime
| Aspect | Detail |
|--------|--------|
| **Name** | M7 — Background Compaction & Promotion Runtime |
| **Objective** | Add a background worker that watches conversations and triggers compaction/promotion |
| **Why it matters** | Compaction/promotion are explicitly invocable only; no automatic trigger exists |
| **Dependencies** | `ConversationCompactor`, `ConversationMemoryPromoter`, needs scheduler |
| **What it would connect** | Periodic compaction checks, promotion after compaction |
| **What it would NOT build** | Context assembly for LLM calls, session orchestration |
| **Expected complexity** | Medium — needs process supervision, failure isolation |
| **Architectural risks** | Running background tasks in same process as voice agent; SQLite locking |

### Candidate D: Project Workspace Integration
| Aspect | Detail |
|--------|--------|
| **Name** | M7 — Project-Aware Assistant |
| **Objective** | Wire `ProjectService` into the runtime so the assistant knows the active project |
| **Why it matters** | Project context + project-scoped memory are built but never used |
| **Dependencies** | `ProjectService`, `ProjectDetector`, `ActiveProjectManager` |
| **What it would connect** | Active project detection → context assembly → project-scoped memory retrieval |
| **What it would NOT build** | Core context assembly, memory extraction, compaction |
| **Expected complexity** | Low — mostly wiring |
| **Architectural risks** | Project detection must not block voice pipeline |

### Candidate E: Tool Orchestration Layer
| Aspect | Detail |
|--------|--------|
| **Name** | M7 — Local Tool Execution & Permissioned Tools |
| **Objective** | Move tool execution from external MCP server to in-process with permission boundaries (ADR-026 local-machine tools) |
| **Why it matters** | ADR-026 envisions local tools; current MCP server is external |
| **Dependencies** | `friday.filesystem` (exists), needs local tool adapters |
| **What it would connect** | In-process tool execution, permission model |
| **What it would NOT build** | Context assembly, memory, compaction, multi-agent |
| **Expected complexity** | High — security model, sandboxing, process isolation |
| **Architectural risks** | **Premature** — ADR-026 explicitly says this is future direction; current MCP works |

---

## SECTION 7 — RECOMMENDED M7

### **M7 — Assistant Core & Context Integration** (Candidate A)

**Justification using actual repository:**

1. **Makes FRIDAY functional end-to-end** — The voice agent will actually use the memory, context, and compaction systems that were built and tested in Phases 2-4. Today they are **zero-percent utilized**.

2. **Reuses systems already built** — `ContextManager`, `MemoryExtractor`, `MemoryResolver`, `DurableMemoryManager`, `ConversationCompactor`, `ConversationMemoryPromoter`, `ProjectService` all exist, are tested, and have clean protocols. M7 just needs to wire them into the conversation turn loop.

3. **Avoids unnecessary architecture** — No new databases, no new frameworks, no multi-agent complexity. Just connects existing pieces.

4. **Establishes clean boundaries for ADR-026** — The "assistant core" that M7 builds becomes the **single integration point** where future orchestration (Agent Registry, OpenCode, Hermes, Verifier) plugs in. ADR-026's `FRIDAY → Task understanding / planning → Agent selection` flow requires a working assistant core first.

5. **Makes next phase testable** — Once context assembly runs per-turn, you can write integration tests: "user says X → memory Y is retrieved → context includes Y → LLM responds correctly."

6. **Avoids premature multi-agent complexity** — ADR-026's orchestration layer **depends on** a functioning assistant core that can assemble context, retrieve memory, and manage conversation state. Building orchestration before the core exists puts the cart before the horse.

**Why other candidates should wait:**

- **B (Session Management)** — `ContextManager.assemble()` already takes `conversation_id` and `active_project_id`. Session resume is a **feature of the assistant core**, not a prerequisite.
- **C (Background Runtime)** — Compaction trigger (`should_compact`) is designed to be called **per-turn** (see `ConversationCompactor.compact()` — it evaluates thresholds on the current message list). A background worker is an optimization, not a requirement. Per-turn triggering is simpler and works.
- **D (Project Integration)** — This is a **subset** of context integration. `ContextManager` already accepts `ProjectContextProvider`. Wiring it is part of M7, not a separate phase.
- **E (Local Tools)** — Explicitly deferred by ADR-026. Current MCP server works. This is orthogonal to the core gap.

---

## SECTION 8 — SHOULD ADR-026 START NOW?

**Answer: C. PARTIALLY — only a prerequisite should be built, not the actual multi-agent system.**

**What must exist before OpenCode/Hermes/verifier orchestration should begin:**

1. ✅ **Assistant Core / Session Layer** (M7) — The component that:
   - Owns the conversation turn lifecycle
   - Assembles context (recent + memory + project) per turn
   - Calls the LLM with assembled context
   - Handles tool calls and feeds results back
   - Persists assistant messages
   - Triggers compaction/promotion asynchronously

2. ✅ **Working Context Assembly** — `ContextManager` producing `ContextSnapshot` for every LLM call

3. ✅ **Working Memory Retrieval** — Durable memories actually reaching the LLM prompt

4. ✅ **Working Compaction Trigger** — Conversation compaction running (per-turn or background) so context doesn't grow unbounded

5. ✅ **Task/Execution State Model** — ADR-026 §7 says: "No Session model is invented merely to represent this now. Task/execution state will be designed during the future orchestration phase." → This **depends on** the assistant core existing first.

**Without M7, ADR-026 orchestration has nowhere to plug in.** The "FRIDAY" box in ADR-026's diagram doesn't exist as a runtime component — it's currently just `agent_friday.py` (a LiveKit adapter) + an MCP server.

---

## SECTION 9 — PROPOSED M7 MILESTONES

### M7.1 — Assistant Core Session Protocol
| Aspect | Detail |
|--------|--------|
| **Objective** | Define the internal session interface that replaces LiveKit's opaque `AgentSession` for context assembly |
| **Files likely involved** | New: `friday/core/session.py`, `friday/core/protocols.py`; Modify: `agent_friday.py` |
| **Public APIs** | `AssistantSession` protocol: `assemble_context(user_message) → ContextSnapshot`, `process_turn(snapshot) → AssistantResponse`, `persist_turn(user_msg, assistant_msg)` |
| **Dependencies** | `ContextManager`, `MemoryManager`, `DurableMemoryManager`, `ProjectService` (all exist) |
| **Tests** | Unit: session assembles context correctly with memories/project; Integration: fake LLM returns expected response |
| **Stop/Review** | ContextSnapshot renders correctly; memory retrieval works; project context included |

### M7.2 — Per-Turn Context Assembly Integration
| Aspect | Detail |
|--------|--------|
| **Objective** | Wire `ContextManager` into the voice agent turn loop so every LLM call receives budgeted context |
| **Files likely involved** | Modify: `agent_friday.py` (replace LiveKit's default message handling); New: `friday/core/turn_handler.py` |
| **Public APIs** | `TurnHandler.handle_user_message(text) → str` (assembles context → calls LLM → returns response) |
| **Dependencies** | M7.1; `friday.ai.providers.build_llm()` for direct LLM call (bypass LiveKit's Agent) |
| **Tests** | Integration: user message → context includes recent + relevant memories → LLM responds with memory awareness |
| **Stop/Review** | Voice agent responds using durable memory; context budget enforced; no regression on tool calls |

### M7.3 — Compaction Trigger Integration
| Aspect | Detail |
|--------|--------|
| **Objective** | Run `ConversationCompactor.compact()` after each turn (or every N turns) to bound conversation growth |
| **Files likely involved** | Modify: `friday/core/session.py` or `turn_handler.py`; New: `friday/core/compaction_scheduler.py` (optional async) |
| **Public APIs** | `CompactionScheduler.maybe_compact(conversation_id, messages) → CompactionResult` |
| **Dependencies** | M7.2; `ConversationCompactor`, `SQLiteCompactionStore`, `trigger.should_compact` |
| **Tests** | Integration: 25-message conversation → compaction triggers → compaction persisted → next turn uses compressed history |
| **Stop/Review** | Compaction fires at threshold; compressed history appears in context; raw messages preserved |

### M7.4 — Explicit Promotion Hook
| Aspect | Detail |
|--------|--------|
| **Objective** | Wire `ConversationMemoryPromoter.promote()` to run after successful compaction (explicit, not automatic) |
| **Files likely involved** | Modify: compaction scheduler/turn handler; New: `friday/core/promotion_coordinator.py` |
| **Public APIs** | `PromotionCoordinator.promote_compaction(compaction, project_id) → PromotionResult` |
| **Dependencies** | M7.3; `ConversationMemoryPromoter`, `SQLitePromotionStore`, `DurableMemoryManager`, `MemoryResolver` |
| **Tests** | Integration: compaction with facts/decisions → promotion runs → memories appear in `memory.db` → next conversation retrieves them |
| **Stop/Review** | Promotion creates durable memories; ledger tracks state; re-promotion is idempotent |

### M7.5 — Project Context Activation
| Aspect | Detail |
|--------|--------|
| **Objective** | Wire `ProjectService` active project detection into context assembly |
| **Files likely involved** | Modify: `friday/core/session.py` to accept/derive `active_project_id` |
| **Public APIs** | `ProjectContextProvider` implementation adapting `ProjectService.get_workspace()` |
| **Dependencies** | M7.1; `ProjectService`, `ProjectDetector`, `ActiveProjectManager` |
| **Tests** | Integration: CWD in registered project → project context + project-scoped memories included in LLM prompt |
| **Stop/Review** | Project context appears in rendered prompt; project-scoped memories retrieved; explicit activation persists |

---

## SECTION 10 — WHAT WE SHOULD NOT BUILD (PREMATURE AT M7)

| Premature Item | Reason |
|----------------|--------|
| OpenCode integration | ADR-026 §11: "Substantial future engineering work remains OPEN"; requires working assistant core first |
| Hermes integration | Same as above; no adapter pattern exists yet |
| Verifier agent | ADR-026 §5: "Exact retry limits and policies are OPEN"; needs task contract system first |
| Agent Registry | ADR-026 §3: "Exact implementation is OPEN"; no manifests, no adapters |
| Arbitrary shell access | ADR-026 §8: "Arbitrary unrestricted local command execution is NOT the initial security model" |
| Distributed task scheduling | ADR-026 §3: "Task scheduling... OPEN" |
| Multi-agent communication | No agent-to-agent protocol exists; ADR-026 §11: "whether agents can delegate to other agents" is OPEN |
| Autonomous background agents | No task state model; ADR-026 §7: "No Session model is invented merely to represent this now" |
| Embeddings/vector search | Explicitly deferred: ARCHITECTURE.md §9: "Vector search and embeddings are explicitly out of scope for now" |
| New frameworks | Current stack (LiveKit, MCP, SQLite, stdlib) sufficient |
| Unnecessary database changes | Two DBs (`conversations.db`, `memory.db`) already exist and are architecturally separated per ADR-025 |

---

## SECTION 11 — ARCHITECTURAL RISKS M7 SHOULD ADDRESS

| Risk | Description | Mitigation in M7 |
|------|-------------|------------------|
| **Duplicated state** | `conversations.db` (raw + compactions + promotions) + `memory.db` + project workspace (markdown) all hold overlapping info | M7 defines clear ownership: raw=conversations, compacted=conversations, durable=memory, project=workspace |
| **Conversation/message representation mismatch** | LiveKit `ChatMessage` vs `SQLiteConversationStore.Message` vs `ContextManager.Message` (tuple) vs compaction `Message` protocol | M7.1 defines canonical internal `Message` type; adapters at boundaries |
| **Lifecycle ownership** | Who closes DBs? `agent_friday.py` closes conversation store; memory/compaction stores have no owner | M7.1 introduces `AssistantSession` that owns all stores' lifecycles |
| **Persistence boundaries** | Two SQLite DBs, no cross-DB transactions (ADR-025) | M7 respects this; promotion is idempotent eventual reconciliation |
| **Failure isolation** | Memory/compaction/promotion failures must never break voice pipeline | M7.2/M7.3: all subsystem calls wrapped in try/except; degrade gracefully (per ContextManager pattern) |
| **Sync vs async execution** | Voice pipeline is async; compaction/promotion could be slow | M7.3: compaction/promotion run in background task (asyncio.create_task) or thread pool |
| **Dependency injection** | Current `agent_friday.py` hardcodes store creation | M7.1: session receives pre-constructed managers (testable, swappable) |
| **Testability** | Voice agent hard to test end-to-end | M7.1: `AssistantSession` protocol enables fake LLM / fake stores in tests |
| **Process boundaries** | MCP server is separate process; local tools would be in-process | M7 keeps MCP; local tools deferred per ADR-026 |
| **Local machine permissions** | Not yet needed | Deferred |

---

## SECTION 12 — TEST STRATEGY FOR M7

### UNIT (fast, isolated, no I/O)
- `ContextManager.assemble()` with fake providers → correct snapshot, budget enforcement, priority ordering
- `ConversationCompactor.compact()` with fake extractor/store → correct boundary/window/extraction/persistence
- `ConversationMemoryPromoter.promote()` with fake stores/resolver → correct ledger transitions, memory creation
- `TurnHandler.handle_user_message()` with fake LLM → context assembled, LLM called, response returned

### INTEGRATION (real components, temp DBs)
- `ContextManager` + real `DurableMemoryManager` + `SQLiteMemoryStore` → memories retrieved, ranked, capped
- `ConversationCompactor` + real `SQLiteCompactionStore` + real `ConversationCompactionExtractor` (fake LLM) → compaction persisted, idempotent
- `ConversationMemoryPromoter` + real `SQLitePromotionStore` + real `DurableMemoryManager` + real `MemoryResolver` → promotion creates memories, ledger updated
- Full turn: user message → context assembly → fake LLM → response → persistence → compaction check

### END-TO-END (voice pipeline or simulated)
- Simulated conversation: 30 turns → verify compaction triggers, compressed history used, memories promoted, next session retrieves memories
- Project activation: CWD detection → project context in prompt → project-scoped memories retrieved
- Tool call: LLM calls filesystem tool → result returned → incorporated into context

### FAILURE/RECOVERY
- Memory store unavailable during context assembly → voice turn succeeds without memories
- Compaction LLM fails → compaction skipped, raw messages preserved, retry next turn
- Promotion ledger write fails after memory write → ledger stays PENDING, retry reconciles
- SQLite locked (concurrent access) → graceful degradation, no crash
- Process restart → conversation resumes, memories intact, compaction boundary preserved

---

## SECTION 13 — FINAL VERDICT

```
M7 RECOMMENDATION
------------------
Recommended scope:
Assistant Core & Context Integration — wire the existing memory, context, compaction,
and promotion libraries into the live voice agent by implementing the missing
session/orchestration layer that owns the conversation turn lifecycle.

Reason:
Phases 2-4 built excellent, tested subsystems that are 0% utilized at runtime.
The voice agent (agent_friday.py) delegates all reasoning to LiveKit's Agent
and all tools to an external MCP server, with only raw message persistence.
M7 connects the dots so FRIDAY actually uses its own brain.

M7 SHOULD:
1. Implement AssistantSession/TurnHandler that assembles ContextSnapshot per turn
   using ContextManager, retrieves durable memories, includes project context.
2. Replace LiveKit's opaque Agent with direct LLM calls using assembled context.
3. Trigger ConversationCompactor.compact() after each turn (hybrid thresholds).
4. Run ConversationMemoryPromoter.promote() after successful compaction (explicit).
5. Wire ProjectService active project detection into context assembly.
6. Ensure all subsystem failures degrade gracefully (never break voice pipeline).
7. Own all store lifecycles (conversations.db, memory.db) in the session.

M7 SHOULD NOT:
1. Build any multi-agent orchestration (Agent Registry, OpenCode, Hermes, Verifier).
2. Implement local-machine tools (open_application, launch_command, etc.).
3. Add embeddings, vector search, or new storage backends.
4. Create background daemon processes (per-turn triggering is sufficient for M7).
5. Invent a Session/Task execution state model (ADR-026 explicitly defers this).

ADR-026 STATUS:
PARTIALLY — M7 builds the prerequisite assistant core that ADR-026's orchestration
layer requires. The actual multi-agent system (registry, adapters, verifier,
task contracts) should wait until M7 is complete and the core is proven.

NEXT MILESTONE:
M7.1 — Assistant Core Session Protocol
  Define AssistantSession protocol, implement ContextManager integration,
  wire MemoryManager/DurableMemoryManager/ProjectService, replace LiveKit
  Agent with direct LLM calls using assembled context.

BLOCKERS:
- None. All required libraries exist, are tested, and have stable protocols.
- Only integration work remains.

ARCHITECTURAL CONCERNS:
- LiveKit AgentSession currently owns the turn loop; M7 must extract control
  without losing voice pipeline features (STT, TTS, VAD, interruption handling).
- SQLite connection lifetime: session must outlive all async callbacks.
- Compaction/promotion must not add latency to the voice turn (async/background).
- Project detection (CWD) must be fast; cache active project in session.

FILES THAT WOULD LIKELY CHANGE:
- agent_friday.py                 (major rewrite: extract turn handling)
- friday/core/session.py          (new: AssistantSession, TurnHandler)
- friday/core/protocols.py        (new: AssistantSession, TurnHandler protocols)
- friday/core/compaction_scheduler.py (new: per-turn compaction trigger)
- friday/core/promotion_coordinator.py (new: post-compaction promotion)
- friday/ai/providers/__init__.py (expose direct LLM call for assembled context)
- friday/config.py                (add M7-specific config if needed)

NO IMPLEMENTATION WAS PERFORMED.
```

---

## VERIFICATION

```
$ git status
On branch main
Your branch is up to date with origin/main.

Changes to be committed:
  (use "git restore --staged <file>..." to unstage)
        ... (27 staged files from previous work)

Untracked files:
  (use "git add <file>..." to include in your commit)
        .hermes/
        M7_READINESS_REVIEW.md

No source files were modified. No tests were modified. No configuration was modified. No documentation was modified. No files were created in the source tree.
```