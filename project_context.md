# Friday Project Context

## Overview

A Tony Stark-inspired AI assistant (F.R.I.D.A.Y.) with two main components:

1. **MCP Server** (`server.py`) - Exposes tools via SSE on port 8000
2. **Voice Agent** (`agent_friday.py`) - Connects to LiveKit and uses MCP tools

## Project Structure

```
friday/
├── config.py - Environment variable loading and app settings
├── tools/ - MCP tool implementations
│   ├── web.py - News, web search, fetch_url, open_world_monitor
│   ├── system.py - System info, time tools
│   └── utils.py - Helper functions
├── prompts/ - MCP prompt templates
├── resources/ - MCP resources
├── server.py - MCP server entry point (uv run friday)
├── agent_friday.py - Voice agent entry point (uv run friday_voice)
├── pyproject.toml - Dependencies and package config
├── .env.example - Environment variables template
└── README.md - Project overview and setup instructions
```

## Setup Instructions

1. **Prerequisites**:
   - Python ≥ 3.11
   - `uv` package manager (`pip install uv` or curl install script)
   - LiveKit Cloud account (free tier available)

2. **Installation**:

   ```bash
   git clone https://github.com/SAGAR-TAMANG/friday-tony-stark-demo.git
   cd friday-tony-stark-demo
   uv sync  # Creates .venv and installs dependencies
   ```

3. **Environment Setup**:

   ```bash
   cp .env.example .env
   # Edit .env and add required API keys:
   # - LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
   # - OPENAI_API_KEY (TTS)
   # - SARVAM_API_KEY (STT)
   # Optional: GROQ_API_KEY, DEEPGRAM_API_KEY, etc.
   ```

4. **Running the Project**:
   - **Terminal 1 (MCP Server)**:

     ```bash
     uv run friday
     ```

     Starts FastMCP server on `http://127.0.0.1:8000/sse`

   - **Terminal 2 (Voice Agent)**:

     ```bash
     uv run friday_voice
     ```

     Starts LiveKit voice agent. Connect to LiveKit room via [Agents Playground](https://agents-playground.livekit.io)

## Key Components

### MCP Server (server.py)

- Creates FastMCP instance with name from config
- Registers tools, prompts, and resources
- Runs on SSE transport on port 8000
- Main entry point: `main()` function

### Voice Agent (agent_friday.py)

- Uses LiveKit Agents framework
- Connects to MCP server via SSE
- Implements F.R.I.D.A.Y. persona with specific behavior rules:
  - Greeting based on time of day
  - Must call tools silently without announcing them
  - After news brief, must call open_world_monitor
  - Keep responses short (2-4 sentences)
  - Use natural spoken language, no technical terms

## Important Tools

- `get_world_news()` - Global news briefing
- `get_world_finance_news()` - Finance market updates
- `open_world_monitor()` - Opens world map dashboard
- `open_finance_world_monitor()` - Opens finance dashboard
- `search_web()` - Web search stub
- `fetch_url()` - Raw URL fetch

## Environment Variables (from .env.example)

- `LIVEKIT_URL` - LiveKit Cloud project URL
- `LIVEKIT_API_KEY` - LiveKit API key
- `LIVEKIT_API_SECRET` - LiveKit API secret
- `OPENAI_API_KEY` - OpenAI API key for TTS
- `SARVAM_API_KEY` - Sarvam AI API key for STT
- `GROQ_API_KEY` - Optional, for Groq provider
- `DEEPGRAM_API_KEY` - Optional, for Deepgram
- `GOOGLE_APPLICATION_CREDENTIALS` - Optional, for Google STT
- `GOOGLE_API_KEY` - Optional, for Google LLM
- `SUPABASE_URL` - Optional, for Supabase integration

## Notes

- Both processes must run simultaneously
- The voice agent connects to the MCP server on port 8000
- Windows host IP is auto-resolved from WSL gateway
- Use `uv run friday` and `uv run friday_voice` commands
- Project uses FastMCP, LiveKit Agents, Sarvam STT, Google Gemini LLM, OpenAI TTS
