"""
Configuration — Application configuration and environment management.
"""

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

config = _Config()
