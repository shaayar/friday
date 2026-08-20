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

    # Phase 3 — Memory distillation & context management
    # Provisional implementation defaults, not architectural constants.
    # All values are overridable at construction time.
    EXTRACTION_CADENCE_TURNS = 10
    EXTRACTION_WINDOW_MESSAGES = 20
    CONTEXT_RECENT_TURNS = 10
    CONTEXT_MEMORY_CAP = 10
    CONTEXT_PROJECT_CAP_UNITS = 2_000
    CONTEXT_MAX_INPUT_UNITS = 40_000
    CONTEXT_RESERVED_OUTPUT_UNITS = 8_000
    CONTEXT_SAFETY_MARGIN = 2_000
    DEDUP_SIMILARITY_THRESHOLD = 0.85

    # Phase 4 — Persistent conversation compaction
    # Locked: hybrid trigger (message count + size), COMPACTION_MESSAGE_THRESHOLD=20.
    # OPEN: the exact size threshold value (provisional below); the mechanism
    # uses the context subsystem's character-unit estimation (estimate_units).
    COMPACTION_MESSAGE_THRESHOLD = 20
    COMPACTION_MAX_WINDOW = 20
    COMPACTION_SIZE_THRESHOLD_UNITS = 4_000  # provisional (Phase 4 OPEN value)

config = _Config()
