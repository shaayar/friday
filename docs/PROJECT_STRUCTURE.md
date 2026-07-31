# Project Structure

This document explains the purpose of every directory in the repository.

---

## docs/

Project documentation.

Contains architecture, milestones, engineering decisions and future planning.

---

## friday/

Application source code.

---

## friday/ai/

Everything related to reasoning.

Contains:

- Providers
- Prompt Builder
- Prompt definitions
- AI orchestration

Must never contain:

- Database code
- Tool implementations
- Desktop automation

---

## friday/memory/

Persistent knowledge management.

Responsible for:

- Retrieval
- Storage
- Memory lifecycle

---

## friday/tools/

Deterministic capabilities.

Examples:

- Browser
- File System
- System Commands

---

## friday/interfaces/

Entry points into the application.

Examples:

- Voice
- Desktop
- CLI
- API

---

## friday/routing/

Request routing.

Responsible for:

- Intent classification
- Request dispatching

---

## friday/resources/

Static resources required by the application.

---

## Root Files

agent_friday.py

Current LiveKit agent entry point.

main.py

Application entry point.

server.py

MCP server.

config.py

Application configuration.
