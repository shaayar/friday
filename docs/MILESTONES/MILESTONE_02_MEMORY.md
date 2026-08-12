# Milestone 02 --- Memory Foundation

**Status:** Planned\
**Phase:** Memory Foundation\
**Project codename:** F.R.I.D.A.Y.\
**Final assistant name:** Deferred

## 1. Objective

Build the first persistent memory capability without prematurely
implementing the complete memory system.

The first implementation provides persistent conversation history
through local SQLite while preserving the architecture needed for
structured memory, semantic memory, memory distillation, project-local
knowledge, ChromaDB/RAG, and context compression.

## 2. Current State

The `friday/memory/` package is currently only a placeholder:

``` text
friday/
└── memory/
    └── __init__.py
```

No memory storage or retrieval implementation exists yet.

Memory is an independent subsystem. The AI must not access storage
directly.

## 3. Memory Architecture

``` text
                         REQUEST
                            │
                            ▼
                    ┌───────────────┐
                    │ Memory Manager│
                    └───────┬───────┘
                            │
                 ┌──────────┴──────────┐
                 │                     │
                 ▼                     ▼
        Conversation History     Durable Memory
                 │                     │
                 ▼                     ▼
              SQLite          Future memory backends
```

The Memory Manager owns memory operations and hides storage
implementation details from the rest of the application.

## 4. First Capability: Conversation History

The first implementation persists conversations and messages.

### Conversation

``` text
Conversation
├── id
├── created_at
└── updated_at
```

### Message

``` text
Message
├── id
├── conversation_id
├── role
├── content
└── created_at
```

Keep the first version small. Do not add embeddings, summaries,
tool-call metadata, observations, or other fields without an actual
requirement.

## 5. Storage Backend

**Initial backend: SQLite**

SQLite is local, persistent, embedded, serverless, and available through
Python's standard library.

No separate database server, Docker container, network port,
credentials, or process is required.

The application should create the database automatically when needed.

## 6. Persistent Data Location

Persistent application data stays outside the source repository.

Conceptually:

``` text
Source code
~/Desktop/friday/
├── friday/
├── docs/
└── ...

Persistent application data
~/.friday/
└── data/
    └── conversations.db
```

The final runtime directory may change when the assistant is renamed.
The architectural rule is:

``` text
source code != user/application data
```

## 7. Initial Memory Layer

Create:

``` text
friday/memory/
├── __init__.py
├── manager.py
└── sqlite_store.py
```

`manager.py` understands memory semantics and exposes operations such
as:

``` text
create conversation
save message
get conversation
get recent messages
```

`sqlite_store.py` owns SQLite-specific concerns such as connections,
schema creation, queries, transactions, and persistence.

The rest of the application should not access SQLite directly.

## 8. Memory Lifecycle

The long-term lifecycle is:

``` text
User interaction
       │
       ▼
Conversation History
       │
       ▼
Memory Distillation
       │
       ├── irrelevant information → discard
       ├── recurring facts        → durable fact
       ├── decisions              → durable decision
       ├── project information    → project memory
       └── useful context         → retained knowledge
```

Conversation history is raw historical material. It is not automatically
equivalent to durable memory.

## 9. Memory Distillation

Future capability:

> Determine what information from conversations is worth retaining as
> durable knowledge.

Example:

``` text
Conversation 1:
"I really like cats."

Conversation 2:
"I saw a cat today."

Conversation 3:
"I want to build something related to cats."

            ↓

Fact:
User has an interest in cats.
```

Memory Distillation answers:

> What should we remember?

The Context Pipeline answers:

> What should we provide to the AI for this request?

These are separate responsibilities.

## 10. Project-Local Memory

Future capability: projects may contain an internal `.friday/` knowledge
directory.

Example:

``` text
project/
├── src/
├── docs/
├── ...
└── .friday/
    ├── context
    ├── decisions
    ├── facts
    ├── changelog
    ├── state
    └── index
```

The user does not need to interact with these files directly.

The format is an implementation detail. Optimize it eventually for
deterministic parsing, compact retrieval, low token usage, reliable
updates, corruption resistance, and versioning.

Do not select a binary/custom encoding merely for compression without a
demonstrated benefit.

## 11. Project Memory Must Be Rebuildable

`.friday/` is derived knowledge, not the irreplaceable source of truth.

If it is deleted or corrupted, the system should eventually be able to
reconstruct relevant information from available sources such as:

-   project files
-   Git history
-   documents
-   conversation history
-   recorded decisions

## 12. Long-Term Memory Layers

The architecture should eventually support:

``` text
Memory
├── Session State
├── Conversation History
├── Structured Memory
└── Semantic Memory
```

Possible future implementations:

``` text
Session State       → runtime/session storage
Conversation History→ SQLite
Structured Memory   → SQLite or another structured store
Semantic Memory     → ChromaDB / vector database
```

Storage technology remains an implementation detail of the Memory
subsystem.

## 13. RAG and ChromaDB

RAG is intentionally out of scope for this first implementation.

Future semantic retrieval may look like:

``` text
Semantic Memory
       │
       ▼
Vector Store / ChromaDB
       │
       ▼
Relevant information
       │
       ▼
Context Pipeline
```

Do not introduce embeddings or vector storage until there is an actual
semantic-retrieval requirement.

## 14. Context Pipeline Relationship

The long-term flow is:

``` text
Memory
   │
   ▼
Retrieve relevant information
   │
   ▼
Context Pipeline
   │
   ├── filtering
   ├── ranking
   ├── deduplication
   ├── relevance scoring
   ├── compression
   └── token budgeting
   │
   ▼
Prompt Builder
   │
   ▼
AI
```

The Context Pipeline must not invent information. It optimizes
information that has already been retrieved.

## 15. Context Multiplier / Compression

A future context multiplier may reduce the amount of context sent to an
LLM by selecting relevant information, removing redundancy, compressing
related information, summarizing long histories, and respecting token
budgets.

This belongs in the Context Pipeline, not in the storage layer.

The exact algorithm is intentionally undecided.

## 16. In Scope Now

-   SQLite local storage
-   persistent conversation records
-   persistent message records
-   Memory Manager
-   SQLite storage layer
-   automatic database initialization
-   basic conversation retrieval
-   recent-message retrieval with a limit
-   separation between memory semantics and storage implementation
-   persistent data outside the source repository

## 17. Explicitly Out of Scope

-   ChromaDB
-   embeddings
-   RAG
-   semantic search
-   memory distillation
-   automatic fact extraction
-   project `.friday/` knowledge directory
-   context compression
-   context multiplier
-   autonomous memory management
-   multi-agent memory
-   cloud memory synchronization

## 18. Acceptance Criteria

-   [ ] Application can create a conversation.
-   [ ] Messages can be persisted.
-   [ ] A conversation survives application restart.
-   [ ] Messages are retrieved in the correct order.
-   [ ] Recent messages can be retrieved with a limit.
-   [ ] Rest of application does not access SQLite directly.
-   [ ] Database is stored outside the source repository.
-   [ ] Database initialization is automatic.
-   [ ] Storage can theoretically be replaced without changing
    higher-level memory semantics.
-   [ ] Existing AI/provider functionality continues to work.

## 19. Implementation Order

``` text
1. Define memory entities
        ↓
2. Define Memory Manager responsibilities
        ↓
3. Define SQLite schema
        ↓
4. Implement SQLite storage
        ↓
5. Implement Memory Manager
        ↓
6. Test persistence independently
        ↓
7. Integrate conversation history into request lifecycle
        ↓
8. Verify existing voice/LLM flow
        ↓
9. Update architecture and decision documentation
```

Do not implement every future layer in this milestone.

## 20. Future Evolution

``` text
                    MEMORY SYSTEM
                         │
          ┌──────────────┼──────────────┐
          │              │              │
          ▼              ▼              ▼
     Conversation    Structured      Semantic
       History        Memory          Memory
          │              │              │
       SQLite         SQLite       ChromaDB/etc.
          │              │              │
          └──────────────┼──────────────┘
                         │
                         ▼
                 Memory Distillation
                         │
                         ▼
                 Context Pipeline
                         │
                         ▼
                   Prompt Builder
                         │
                         ▼
                          AI
```

Project-local `.friday/` knowledge will eventually provide
project-scoped memory alongside global memory.

## 21. Architectural Principle

> **Store raw conversation history first. Distill knowledge later.
> Retrieve only what is relevant.**

Do not make the first memory implementation responsible for
understanding everything the user says.

Build the storage foundation first.
