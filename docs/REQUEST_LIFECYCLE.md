# Request Lifecycle

> Defines how every user request travels through F.R.I.D.A.Y., from the moment it enters the system until a response is delivered.
>
> This document describes the logical flow of the system. It is independent of implementation details and technologies.

---

## Purpose

Every interaction with F.R.I.D.A.Y. follows the same lifecycle regardless of where it originates.

Whether the user interacts through:

- Voice
- Desktop UI
- Command Line
- API (future)

the request should travel through the same pipeline.

Having a single execution path provides:

- predictable behaviour
- easier debugging
- modular development
- reusable components
- extensibility

---

## Lifecycle Overview

```text
                                   USER
                                     │
                     Voice / Desktop / CLI / API
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
       ┌─────────────────────────────┼──────────────────────────────┐
       │                             │                              │
       ▼                             ▼                              ▼
 Deterministic                 AI Required                    Hybrid Request
       │                             │                              │
       └─────────────────────────────┴──────────────────────────────┘
                                     │
                                     ▼
                                 Planner
                                     │
                      Creates Execution Plan / Task Graph
                                     │
                                     ▼
                               Task Manager
                                     │
      ┌──────────────┬───────────────┼──────────────┬───────────────┐
      │              │               │              │               │
      ▼              ▼               ▼              ▼               ▼
 Tool Task      Memory Task      AI Task      Workflow Task   Background Task
      │              │               │              │               │
      └──────────────┴───────────────┴──────────────┴───────────────┘
                                     │
                                     ▼
                              Task Scheduler
                                     │
                                     ▼
                                 Executor
                                     │
        ┌────────────────────────────┼──────────────────────────┐
        │                            │                          │
        ▼                            ▼                          ▼
    MCP Tools                  Memory Manager              AI Engine
                                     │                          │
                          ┌──────────┴──────────┐               │
                          │                     │               │
                          ▼                     ▼               ▼
                 Conversation History    Durable Memory   Context Pipeline
                          │                     │               │
                          └──────────┬──────────┘               │
                                     │                          │
                                     └──────────────┬───────────┘
                                                    ▼
                                           Context Pipeline
                                                    │
                                                    ▼
                                            Prompt Builder
                                                    │
                                                    ▼
                                             LLM Provider
                                                    │
                                                    ▼
                                               Observation
                                                    │
                          ┌─────────────────────────┴─────────────────────────┐
                          │                                                   │
                          ▼                                                   ▼
                    Session State                                    Memory Update
                          │                                                   │
                          └─────────────────────────┬─────────────────────────┘
                                                    │
                                                    ▼
                                             Response Builder
                                                    │
                                                    ▼
                                           Output Interface
```

---

## Stage 1 — Input

Accept user interaction from any supported interface.

Supported interfaces:

- Voice
- Desktop
- CLI
- API (future)

At this stage the system does **not** care about the content of the request.

Its only job is accepting input.

---

## Stage 2 — Input Normalizer

Convert every interface into a common internal representation.

Regardless of the source, every interaction becomes a single Request object.

Examples:

Voice

↓

Speech-to-Text

↓

Request

Desktop

↓

Request

CLI

↓

Request

Every subsystem after this point only understands Requests.

---

## Stage 3 — Intent Classification

Determine what type of work needs to be performed.

Examples:

- Tool execution
- Memory lookup
- AI reasoning
- Workflow execution
- Hybrid request

The Intent Classifier never performs actions.

It only classifies.

---

## Stage 4 — Planner

Translate the user's intent into an executable plan.

The planner determines:

- required tasks
- execution order
- dependencies
- required resources

The planner does not execute tasks.

It only produces an Execution Plan.

Planning may be:

- deterministic
- AI-assisted

depending on complexity.

---

## Stage 5 — Task Manager

Own the lifecycle of every task.

Responsibilities include:

- creating tasks
- tracking progress
- cancelling tasks
- pausing tasks
- resuming tasks
- monitoring task state

The Task Manager becomes the central coordinator for execution.

---

## Stage 6 — Task Scheduler

Determine how tasks should execute.

Possible strategies:

- sequential
- parallel
- delayed
- background
- dependency-based

The scheduler never decides *what* should happen.

Only *when* it should happen.

---

## Stage 7 — Executor

Perform the work described by the Execution Plan.

The Executor is intentionally "dumb."

It does not reason.

It does not plan.

It simply executes tasks.

Possible execution targets:

- MCP tools
- AI Engine
- Memory Manager
- Workflow Engine

---

## Stage 8 — Memory Manager

### Purpose

Manage conversation history and persistent memory.

The Memory Manager separates raw conversation history from durable memory and hides storage implementation details from the rest of the system.

---

### Responsibilities

- Create conversations
- Store messages
- Retrieve conversation history
- Retrieve recent messages
- Store durable memories
- Retrieve memories
- Update durable memories
- Select storage backend

---

### Input

- Conversation requests
- Memory requests
- Context retrieval requests

---

### Output

- Conversation
- Message
- Memory
- Context

---

### Storage

Abstract.

Possible implementations include:

- SQLite
- ChromaDB
- Future storage backends

Higher-level modules must never communicate with databases directly.

---

## Stage 9 — Context Pipeline

Prepare context before it reaches the AI.

Possible operations include:

- filtering
- ranking
- deduplication
- relevance scoring
- compression
- token budgeting

The Context Pipeline never invents information.

It only optimizes retrieved context.

---

## Stage 10 — Prompt Builder

Assemble the final prompt.

Possible inputs:

- persona
- behaviour rules
- retrieved context
- conversation history
- user request
- available tools

The Prompt Builder prepares the final prompt sent to the language model.

---

## Stage 11 — AI Engine

Perform reasoning.

Examples:

- planning
- explanation
- summarization
- natural conversation
- ambiguity resolution

The AI Engine does **not**:

- execute tools
- store memory
- manage sessions
- control the operating system

---

## Stage 12 — Observation

Observe the outcome of execution.

Examples:

Success

Failure

Latency

Errors

Tool outputs

State changes

Observations provide feedback to the rest of the system.

---

## Stage 13 — State Update

Execution may update two kinds of state.

### Session State

Temporary information.

Examples:

- active conversation
- pending questions
- active workflows
- recent observations
- temporary variables

Destroyed when the session ends.

---

### Conversation History

Persistent record of interactions.

Examples:

- conversations
- messages
- tool interactions
- relevant observations

Conversation History records what happened.

It is not automatically considered durable Memory.

---

### Durable Memory

Persistent information retained because it is useful beyond the immediate conversation.

Examples:

- preferences
- projects
- research
- user profile
- decisions
- facts

Durable Memory may eventually be produced through Memory Distillation.

---

Both Conversation History and Durable Memory persist across sessions, but they serve different purposes.

---

## Stage 14 — Response Builder

Convert execution results into a user-facing response.

The Response Builder combines:

- observations
- AI responses
- tool outputs

into a single coherent response.

---

## Stage 15 — Output

Return the response through the originating interface.

Examples:

Voice

↓

Text-to-Speech

Desktop

↓

GUI

CLI

↓

Terminal

API

↓

JSON Response

---

## Lifecycle Principles

### Single Entry

Every interaction becomes a Request.

---

### Single Planner

Only the Planner decides how work should be performed.

---

### AI Only When Necessary

AI is responsible for reasoning.

Never for deterministic execution.

---

### Memory Independence

Memory remains independent from AI.

The AI consumes prepared context.

It never directly accesses storage.

---

### Provider Independence

Higher-level components never depend directly on:

- Gemini
- Ollama
- Sarvam
- ChromaDB
- SQLite

Providers are implementation details.

---

### Observability

Every significant action should produce an Observation.

This enables:

- debugging
- logging
- analytics
- automation
- future event-driven architecture

---

## Future Extensions

This lifecycle is intentionally designed to support future capabilities without requiring architectural changes.

Potential extensions include:

- Screen vision
- File indexing
- Calendar integration
- Email integration
- Plugin ecosystem
- Event bus
- Autonomous workflows
- Multi-agent orchestration
- Remote interfaces

These features should integrate into the existing lifecycle rather than replacing it.
