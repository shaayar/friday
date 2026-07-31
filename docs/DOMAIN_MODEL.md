# Domain Model

> Defines the core domain objects used throughout F.R.I.D.A.Y.
>
> These models form the common language of the system. Every subsystem communicates using these models instead of provider-specific objects, database schemas, or arbitrary dictionaries.
>
> **This document is implementation-independent.** It describes concepts, responsibilities, and relationships rather than Python classes.

---

## Purpose

As the system grows, modules must communicate through a shared language.

Instead of passing random dictionaries or provider-specific responses, every subsystem exchanges well-defined domain objects.

Benefits:

- Predictable interfaces
- Easier debugging
- Loose coupling
- Easier testing
- Provider independence

---

## Domain Model Overview

```text
Request
    │
    ▼
Intent
    │
    ▼
ExecutionPlan
    │
    ▼
Task
    │
    ▼
Observation
    │
    ▼
Response

Memory
    │
    ▼
Context
    │
    ▼
Prompt
    │
    ▼
AI Engine

Every action also produces:

Event
```

---

## 1. Request

### Purpose

Represents every user interaction entering the system.

Every interface must produce a Request.

---

### Produced By

- Voice Interface
- Desktop UI
- CLI
- API

---

### Consumed By

- Intent Classifier

---

### Fields

| Field | Description |
|--------|-------------|
| id | Unique request identifier |
| session_id | Active session |
| timestamp | Time received |
| source | Voice, Desktop, CLI, API |
| modality | Text, Voice, Image, File |
| content | User input |
| metadata | STT confidence, latency, etc. |
| attachments | Optional files/images |

---

### Example

User:

> Open VS Code.

↓

Request

---

## 2. Intent

### Purpose

Represents the system's understanding of what the user wants.

Intent never executes anything.

It only describes the work.

---

### Produced By

Intent Classifier

---

### Consumed By

Planner

---

### Fields

| Field | Description |
|--------|-------------|
| type | Tool, AI, Memory, Workflow, Hybrid |
| confidence | Classification confidence |
| requires_ai | Whether reasoning is required |
| requires_memory | Whether memory retrieval is required |
| requires_tools | Whether tool execution is required |
| priority | Execution priority |

---

## 3. ExecutionPlan

### Purpose

Represents the complete strategy for fulfilling a request.

ExecutionPlan describes *what* should happen.

It never performs work.

---

### Produced By

Planner

---

### Consumed By

Task Manager

---

### Fields

| Field | Description |
|--------|-------------|
| id | Plan identifier |
| goal | User objective |
| tasks | Collection of tasks |
| dependencies | Task relationships |
| estimated_steps | Expected execution steps |
| status | Current state |

---

### Example

Goal:

Launch development environment

Tasks:

1. Open VS Code
2. Open Project
3. Open Terminal
4. Run development server

---

## 4. Task

### Purpose

Represents the smallest executable unit of work.

Everything eventually becomes a Task.

---

### Produced By

Planner

Task Manager

---

### Consumed By

Executor

---

### Fields

| Field | Description |
|--------|-------------|
| id | Task identifier |
| type | Tool, AI, Memory, Workflow |
| action | Action to perform |
| payload | Required input |
| priority | Scheduling priority |
| status | Current state |
| retries | Retry count |
| timeout | Maximum execution time |
| dependencies | Required prerequisite tasks |

---

### Examples

- Open Browser
- Launch VS Code
- Read Memory
- Summarize Document
- Search Files

---

## 5. Observation

### Purpose

Represents the outcome of execution.

Every completed task should produce an Observation.

---

### Produced By

Executor

---

### Consumed By

- Response Builder
- Session State
- Memory Manager
- Logging

---

### Fields

| Field | Description |
|--------|-------------|
| task_id | Related task |
| success | Execution result |
| output | Result data |
| error | Failure information |
| duration | Execution time |
| timestamp | Completion time |
| metadata | Additional information |

---

### Example

```
Task:
Open Browser

Success:
True

Duration:
240 ms
```

---

## 6. Session

### Purpose

Represents the current working state.

Equivalent to RAM.

Destroyed when the session ends.

---

### Produced By

Session Manager

---

### Consumed By

Most subsystems

---

### Fields

| Field | Description |
|--------|-------------|
| id | Session identifier |
| active_tasks | Running tasks |
| pending_questions | Awaiting user response |
| recent_requests | Recent requests |
| recent_observations | Recent execution results |
| temporary_context | Temporary variables |
| current_project | Active project |

---

## 7. Memory

### Purpose

Represents persistent knowledge.

Independent of storage implementation.

---

### Produced By

Memory Manager

---

### Consumed By

Context Pipeline

---

### Fields

| Field | Description |
|--------|-------------|
| id | Memory identifier |
| type | Conversation, Preference, Project, Knowledge |
| content | Stored information |
| source | Origin of memory |
| importance | Retention score |
| created_at | Creation time |
| updated_at | Last modification |

---

### Notes

Memory does not know whether it lives in:

- SQLite
- ChromaDB
- another backend

Storage is an implementation detail.

---

## 8. Context

### Purpose

Represents all relevant information prepared for reasoning.

Context is **not** the final prompt.

It is structured information.

---

### Produced By

Memory Manager

Context Pipeline

---

### Consumed By

Prompt Builder

---

### Fields

| Field | Description |
|--------|-------------|
| memories | Retrieved memories |
| conversation | Conversation history |
| session | Current session |
| environment | System state |
| project | Active project |
| tool_results | Relevant observations |

---

## 9. Prompt

### Purpose

Represents the final prompt sent to an LLM.

---

### Produced By

Prompt Builder

---

### Consumed By

AI Provider

---

### Fields

| Field | Description |
|--------|-------------|
| persona | Assistant personality |
| instructions | System instructions |
| context | Prepared context |
| user_request | Current request |
| available_tools | Tool definitions |

---

## 10. Response

### Purpose

Represents the final response returned to the user.

Independent of interface.

---

### Produced By

Response Builder

---

### Consumed By

Output Interface

---

### Fields

| Field | Description |
|--------|-------------|
| text | Response text |
| actions | Actions performed |
| observations | Relevant execution results |
| latency | Total execution time |
| metadata | Additional information |

---

## 11. ToolResult

### Purpose

Represents the standardized output of every tool.

Every tool should return the same structure.

---

### Produced By

MCP Tools

---

### Consumed By

Executor

Observation

---

### Fields

| Field | Description |
|--------|-------------|
| success | Execution result |
| output | Human-readable output |
| structured_data | Machine-readable result |
| error | Failure details |
| metadata | Additional information |

---

## 12. Event

### Purpose

Represents something that happened inside the system.

Events enable logging, debugging, automation, and future event-driven architecture.

---

### Produced By

Every subsystem

---

### Consumed By

- Logger
- Analytics
- Automation
- Monitoring

---

### Fields

| Field | Description |
|--------|-------------|
| id | Event identifier |
| type | Event type |
| source | Producing subsystem |
| payload | Event data |
| timestamp | Event time |
| correlation_id | Related request/task |

---

### Example Events

- request_received
- intent_classified
- plan_created
- task_started
- task_completed
- task_failed
- tool_executed
- memory_saved
- llm_called
- response_generated

---

## Relationships

```text
Request
    │
    ▼
Intent
    │
    ▼
ExecutionPlan
    │
    ▼
Task
    │
    ▼
Observation
    │
    ▼
Response


Memory
    │
    ▼
Context
    │
    ▼
Prompt
    │
    ▼
AI Engine


Every significant action

↓

Event
```

---

## Design Principles

### Provider Independent

These models must never reference:

- Gemini
- Ollama
- SQLite
- ChromaDB
- Sarvam
- OpenAI

Providers are implementation details.

---

### Storage Independent

Domain objects should not know where they are stored.

---

### Interface Independent

Voice, Desktop, CLI, and API all use the same Request and Response models.

---

### Stable Contracts

These models form the public language of the system.

As the implementation evolves, these contracts should remain as stable as possible to minimize coupling between subsystems.