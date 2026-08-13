"""
Configuration — Application configuration and environment management.
"""

from pathlib import Path


class _Config:
    STT_PROVIDER       = "sarvam"
    LLM_PROVIDER       = "groq"
    TTS_PROVIDER       = "sarvam"

    GROQ_LLM_MODEL = "openai/gpt-oss-20b"
    OPENAI_LLM_MODEL   = "gpt-4o"
    OLLAMA_LLM_MODEL = "qwen2.5-coder:3b"

    SARVAM_TTS_MODEL   = "bulbul:v3"
    SARVAM_TTS_VOICE   = "neha"
    TTS_SPEED           = 1.15

    SARVAM_TTS_LANGUAGE = "en-IN"

    # MCP server running on Windows host
    MCP_SERVER_PORT = 8000
    
    SERVER_NAME = "Friday MCP Server"

    # FRIDAY workspace root — internally trusted by the filesystem policy
    FRIDAY_HOME = Path.home() / ".friday"

    # Filesystem capability limits (bytes / entries / results / depth)
    FILESYSTEM_READ_LIMIT_BYTES = 1_000_000
    FILESYSTEM_WRITE_LIMIT_BYTES = 1_000_000
    FILESYSTEM_LIST_LIMIT = 500
    FILESYSTEM_SEARCH_MAX_RESULTS = 100
    FILESYSTEM_SEARCH_MAX_DEPTH = 5

config = _Config()
