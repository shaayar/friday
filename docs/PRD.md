# Product Requirements Document (PRD)

# F.R.I.D.A.Y.
**Fully Responsive Intelligent Desktop Assistant**

**Version:** 1.0  
**Status:** Draft  
**Author:** Shubham Dave

---

# 1. Overview

F.R.I.D.A.Y. is a modular, desktop-first AI assistant inspired by the assistant from the Iron Man universe.

Unlike traditional AI chatbots, F.R.I.D.A.Y. is designed as a software system where artificial intelligence is only one capability among many. The assistant combines deterministic software, local system automation, persistent memory, and language models to create a natural, extensible desktop companion.

The project serves two goals:

- Build a practical everyday desktop assistant.
- Learn production-grade AI system architecture and software engineering.

---

# 2. Vision

Create an intelligent assistant that behaves naturally, remembers context, automates computer tasks, and can evolve into a highly capable desktop operating companion.

The assistant should feel less like "ChatGPT with tools" and more like an operating system component.

---

# 3. Objectives

## Primary

- Desktop-first architecture
- Natural voice conversations
- Persistent long-term memory
- Modular architecture
- Hybrid online/offline capability
- Extensible tool ecosystem

## Secondary

- Learn AI system engineering
- Understand LLM orchestration
- Explore retrieval systems
- Build reusable architecture

---

# 4. Core Principles

## AI is a capability, not the foundation.

Use deterministic software whenever possible.

Use AI only when reasoning is required.

---

## Modularity

Every subsystem owns one responsibility.

Modules communicate through clear interfaces.

---

## Replaceable Providers

External services must never become tightly coupled to the application.

Any provider should be replaceable.

Examples:

- Gemini → Ollama
- Sarvam → Whisper
- OpenAI → Piper

without affecting higher-level code.

---

## Local First

Whenever practical:

- process locally
- store locally
- automate locally

Cloud services enhance the experience rather than define it.

---

# 5. Target Platform

Primary:

- Linux (Ubuntu)

Future:

- Windows
- macOS

---

# 6. Users

Initially:

Single user (the developer).

Future:

Personal assistant for individual users.

---

# 7. Functional Requirements

## Voice Interaction

- Wake assistant
- Speech recognition
- Natural conversation
- Speech synthesis

---

## Desktop Automation

- Open applications
- Execute shell commands
- File management
- Browser automation
- Clipboard interaction
- Notifications

---

## Memory

Remember:

- conversations
- projects
- user preferences
- notes
- reminders
- decisions

Retrieve memories naturally.

---

## Knowledge

Store:

- research
- documentation
- meeting notes
- project context

Support semantic retrieval.

---

## Reasoning

Support:

- planning
- brainstorming
- summarization
- explanations
- decision making

---

## Tool Execution

Execute deterministic actions through tools.

Examples:

- open browser
- launch VS Code
- create folders
- search files
- manage projects

---

# 8. Non-functional Requirements

- Modular
- Maintainable
- Extensible
- Testable
- Offline capable
- Provider independent
- Low latency
- Minimal API usage

---

# 9. High-Level Architecture

Interfaces

↓

Intent Routing

↓

Execution Layer

↓

Providers

Major subsystems include:

- Interface Layer
- Intent Router
- Tool Engine
- Memory Manager
- AI Engine
- Context Builder
- Provider Layer

---

# 10. AI Responsibilities

AI should handle:

- reasoning
- planning
- summarization
- natural dialogue
- ambiguity resolution

AI should NOT handle:

- launching applications
- filesystem operations
- operating system APIs
- remembering structured data

---

# 11. Memory Strategy

## Structured Memory

Examples:

- preferences
- settings
- reminders

Storage:

SQLite

---

## Conversation History

Chronological storage of conversations.

Storage:

SQLite

---

## Semantic Memory

Examples:

- research
- documentation
- project notes

Storage:

Vector database (ChromaDB)

---

## Working Memory

Current session state.

Storage:

Memory cache.

---

# 12. Interfaces

Current:

- Voice

Planned:

- Desktop GUI
- Command Line
- API
- Mobile companion

---

# 13. Technology Stack

Language

- Python

Package Manager

- uv

AI

- Gemini
- Ollama (future)

Speech Recognition

- Sarvam
- Faster Whisper (future)

Speech Synthesis

- OpenAI
- Local TTS (future)

Memory

- SQLite
- ChromaDB

Protocols

- FastMCP

---

# 14. Milestones

## Phase 1

Foundation

- Project architecture
- Configuration
- Prompt system
- Provider abstraction

---

## Phase 2

Memory

- Conversation storage
- User profile
- Project memory
- Retrieval

---

## Phase 3

Desktop

- Desktop interface
- Automation
- System tools

---

## Phase 4

Intelligence

- Context builder
- Better retrieval
- Improved planning

---

## Phase 5

Advanced Features

- Vision
- Screen understanding
- Automation workflows
- Multi-agent capabilities (if needed)

---

# 15. Success Metrics

Technical

- Modular architecture
- Easy provider replacement
- Fast startup
- Reliable memory retrieval
- Stable voice interaction

Product

- Natural conversations
- Useful daily automation
- Context retention
- Low latency
- Reduced unnecessary AI calls

---

# 16. Out of Scope

Current version will not focus on:

- Multi-user support
- Cloud synchronization
- Team collaboration
- Mobile-first experience
- Large-scale deployment

---

# 17. Long-Term Vision

F.R.I.D.A.Y. should become a trusted desktop companion capable of understanding context, remembering long-term information, executing deterministic tasks reliably, and using AI only where intelligence genuinely adds value.

The architecture should remain understandable, modular, and maintainable as new capabilities are introduced over time.
