"""
Configuration — Application configuration and environment management.
"""

class _Config:
    STT_PROVIDER       = "sarvam"
    LLM_PROVIDER       = "groq"
    TTS_PROVIDER       = "openai"

    GROQ_LLM_MODEL = "openai/gpt-oss-20b"
    OPENAI_LLM_MODEL   = "gpt-4o"
    OLLAMA_LLM_MODEL = "qwen2.5-coder:3b"

    OPENAI_TTS_MODEL   = "tts-1"
    OPENAI_TTS_VOICE   = "nova"       # "nova" has a clean, confident female tone
    TTS_SPEED           = 1.15

    SARVAM_TTS_LANGUAGE = "en-IN"
    SARVAM_TTS_SPEAKER  = "neha"
    # SARVAM_TTS_SPEAKER  = "shruti"
    # SARVAM_TTS_SPEAKER  = "ishita"
    # SARVAM_TTS_SPEAKER  = "kavya"

    # MCP server running on Windows host
    MCP_SERVER_PORT = 8000
    
    SERVER_NAME = "Friday MCP Server"

config = _Config()
