# Components

> This document defines every major subsystem of F.R.I.D.A.Y., its responsibility, boundaries, inputs, outputs, and dependencies.
>
> Components describe **what a subsystem is responsible for**, not **how it is implemented**.
>
> A component should own one responsibility and communicate with other components only through well-defined domain models.

---

## System Overview

```text
                    Interfaces
                         │
                         ▼
                Input Normalizer
                         │
                         ▼
               Intent Classification
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
      ┌──────────────┬──────────────┬──────────────┐
      │              │              │
      ▼              ▼              ▼
 Tool Engine   Memory Manager   AI Engine
      │              │              │
      └──────────────┴──────────────┘
                     │
                     ▼
              Response Builder
                     │
                     ▼
                 Output Layer
```

---

## 1. Interface Layer

### Purpose

Provide a way for users to interact with F.R.I.D.A.Y.

---

### Responsibilities

- Accept user input
- Deliver responses
- Handle interface-specific logic
- Convert interface events into Requests

---

### Inputs

User interaction

---

### Outputs

Request

---

### Future Interfaces

- Voice
- Desktop UI
- CLI
- REST API
- Mobile Companion

---

### Should NOT

- Reason
- Execute tools
- Manage memory
- Plan tasks

---

## 2. Input Normalizer

### Purpose

Convert every interface into a standardized Request.

---

### Responsibilities

- Normalize inputs
- Populate Request metadata
- Attach timestamps
- Attach session information

---

### Input

Interface-specific data

---

### Output

Request

---

## 3. Intent Classifier

### Purpose

Determine what kind of work the request requires.

---

### Responsibilities

Classify requests as:

- Tool
- AI
- Memory
- Workflow
- Hybrid

Determine:

- confidence
- required capabilities

---

### Input

Request

---

### Output

Intent

---

### Should NOT

- Execute anything
- Call tools
- Access memory

---

## 4. Planner

### Purpose

Transform an Intent into an executable plan.

---

### Responsibilities

- Create Execution Plans
- Break goals into Tasks
- Resolve dependencies
- Determine execution order

---

### Input

Intent

---

### Output

ExecutionPlan

---

### Notes

Planning may be:

- deterministic
- AI-assisted

depending on complexity.

---

## 5. Task Manager

### Purpose

Own every task throughout its lifecycle.

---

### Responsibilities

- Create tasks
- Track progress
- Pause tasks
- Resume tasks
- Cancel tasks
- Monitor state

---

### Input

ExecutionPlan

---

### Output

Task

---

### Future

Support:

- concurrent tasks
- background execution
- task priorities

---

## 6. Task Scheduler

### Purpose

Determine when tasks execute.

---

### Responsibilities

- Sequential execution
- Parallel execution
- Background scheduling
- Dependency resolution

---

### Input

Tasks

---

### Output

Scheduled Tasks

---

### Should NOT

Determine what tasks exist.

---

## 7. Executor

### Purpose

Execute tasks.

---

### Responsibilities

Perform work.

Nothing else.

---

### Input

Task

---

### Output

Observation

---

### Characteristics

The Executor is intentionally "dumb."

It never:

- reasons
- plans
- interprets

It only executes.

---

## 8. Tool Engine

### Purpose

Provide deterministic system capabilities.

---

### Responsibilities

Execute:

- file operations
- browser automation
- application launching
- operating system interaction

---

### Input

Task

---

### Output

ToolResult

---

### Should NOT

- Reason
- Store memory
- Generate responses

---

## 9. Memory Manager

### Purpose

Manage persistent memory and conversation history.

The Memory Manager separates raw conversation history from durable memory and hides storage implementation details from higher-level components.

---

### Responsibilities

- Store conversations
- Store messages
- Retrieve conversation history
- Retrieve recent messages
- Store durable memories
- Retrieve relevant memories
- Update durable memories
- Select and manage storage backends
- Maintain the boundary between conversation history and durable memory

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

Examples:

- SQLite
- ChromaDB
- Future storage backends

Higher-level components remain unaware of storage implementation.

---

### Should NOT

- Reason about the meaning of conversations
- Decide what information should become durable memory
- Build prompts
- Call LLM providers directly
- Expose storage implementation details

---

## 10. Context Pipeline

### Purpose

Optimize context before AI reasoning.

---

### Responsibilities

- Filter
- Rank
- Deduplicate
- Compress
- Budget tokens

---

### Input

Context

---

### Output

Optimized Context

---

### Should NEVER

Invent information.

---

## 11. Prompt Builder

### Purpose

Construct the final prompt.

---

### Responsibilities

Combine:

- Persona
- Behaviour
- Context
- User request
- Tool definitions

---

### Input

Context

Request

Persona

---

### Output

Prompt

---

## 12. AI Engine

### Purpose

Provide reasoning.

---

### Responsibilities

- Planning
- Explanation
- Summarization
- Dialogue
- Ambiguity resolution

---

### Input

Prompt

---

### Output

AI Response

---

### Should NOT

- Execute tools
- Store memory
- Access databases
- Control the operating system

---

## 13. Observation Engine

### Purpose

Capture execution outcomes.

---

### Responsibilities

Record:

- success
- failure
- latency
- outputs
- state changes

---

### Input

Executor results

---

### Output

Observation

---

### Future

May emit Events.

---

## 14. Session Manager

### Purpose

Maintain temporary working state.

---

### Responsibilities

Track:

- active conversations
- active workflows
- pending questions
- temporary variables

---

### Lifetime

Current session only.

---

### Storage

Memory (RAM)

---

## 15. Response Builder

### Purpose

Generate the final user-facing response.

---

### Responsibilities

Combine:

- observations
- AI responses
- tool outputs

into a coherent response.

---

### Input

Observation

AI Response

---

### Output

Response

---

## 16. Output Layer

### Purpose

Deliver responses through the originating interface.

---

### Responsibilities

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

JSON

---

## Component Relationships

```text
Request

↓

Intent Classifier

↓

Planner

↓

Task Manager

↓

Task Scheduler

↓

Executor

↓

Tool Engine
Memory Manager
AI Engine

↓

Observation

↓

Response Builder

↓

Output Layer
```

---

## Component Dependencies

| Component | Depends On |
|------------|------------|
| Interface Layer | None |
| Input Normalizer | Interface Layer |
| Intent Classifier | Request |
| Planner | Intent |
| Task Manager | ExecutionPlan |
| Scheduler | Task Manager |
| Executor | Scheduler |
| Tool Engine | Executor |
| Memory Manager | Conversation, Message, Memory, Observation |
| Context Pipeline | Memory Manager |
| Prompt Builder | Context Pipeline |
| AI Engine | Prompt Builder |
| Observation Engine | Executor |
| Session Manager | Observation Engine |
| Response Builder | Observation Engine, AI Engine |
| Output Layer | Response |

---

## Design Rules

### Single Responsibility

Every component owns exactly one responsibility.

---

### Loose Coupling

Components communicate only through domain models.

Never through implementation details.

---

### Replaceable Providers

Providers are hidden behind components.

Business logic never depends directly on:

- Gemini
- Ollama
- SQLite
- ChromaDB
- Sarvam

---

### Deterministic First

Components should prefer deterministic execution whenever possible.

Reasoning is delegated to the AI Engine only when necessary.

---

### Explicit Data Flow

Data always flows through the request lifecycle.

Components should avoid hidden state or implicit communication.

---

### Testability

Every component should be independently testable through its public interface.