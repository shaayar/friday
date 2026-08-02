import logging
import os

from friday.config import config
from livekit.plugins import groq as lk_groq
from livekit.plugins import openai as lk_openai
from livekit.plugins import sarvam


logger = logging.getLogger("friday-agent")

# Speech to Text (STT), Text to Speech (TTS), and Large Language Model (LLM) builders based on configuration.
def build_stt():
    if config.STT_PROVIDER == "sarvam":
        logger.info("STT → Sarvam Saaras v3")
        return sarvam.STT(
            language="unknown",
            model="saaras:v3",
            mode="transcribe",
            flush_signal=True,
            sample_rate=16000,
        )
    elif config.STT_PROVIDER == "whisper":
        logger.info("STT → OpenAI Whisper")
        return lk_openai.STT(model="whisper-1")
    else:
        raise ValueError(f"Unknown STT_PROVIDER: {config.STT_PROVIDER!r}")


def build_llm():
    if config.LLM_PROVIDER == "openai":
        logger.info("LLM → OpenAI (%s)", config.OPENAI_LLM_MODEL)
        return lk_openai.LLM(model=config.OPENAI_LLM_MODEL)
    elif config.LLM_PROVIDER == "groq":
        logger.info("LLM → Groq (%s)", config.GROQ_LLM_MODEL)
        return lk_groq.LLM(model=config.GROQ_LLM_MODEL)
    elif config.LLM_PROVIDER == "ollama":
        logger.info("LLM → Ollama (%s)", config.OLLAMA_LLM_MODEL)
        return lk_openai.LLM(model=config.OLLAMA_LLM_MODEL)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {config.LLM_PROVIDER!r}")


def build_tts():
    if config.TTS_PROVIDER == "sarvam":
        logger.info("TTS → Sarvam Bulbul v3")
        return sarvam.TTS(
            target_language_code=config.SARVAM_TTS_LANGUAGE,
            model="bulbul:v3",
            speaker=config.SARVAM_TTS_SPEAKER,
            pace=config.TTS_SPEED,
        )
    elif config.TTS_PROVIDER == "openai":
        logger.info("TTS → OpenAI TTS (%s / %s)", config.OPENAI_TTS_MODEL, config.OPENAI_TTS_VOICE)
        return lk_openai.TTS(model=config.OPENAI_TTS_MODEL, voice=config.OPENAI_TTS_VOICE, speed=config.TTS_SPEED)
    else:
        raise ValueError(f"Unknown TTS_PROVIDER: {config.TTS_PROVIDER!r}")
