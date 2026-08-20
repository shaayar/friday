"""FRIDAY - Voice Agent (MCP-powered)
====================================
Iron Man-style voice assistant that controls RGB lighting, runs diagnostics,
scans the network, and triggers dramatic boot sequences via an MCP server
running on the Windows host.

MCP Server URL is auto-resolved from WSL -> Windows host IP.

Run:
    uv run agent_friday.py dev      - LiveKit Cloud mode
    uv run agent_friday.py console  - text-only console mode
"""

import logging
import subprocess
from datetime import UTC

from dotenv import load_dotenv
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.llm import ChatContext, ChatMessage
from livekit.agents.voice import Agent, AgentSession

# Plugins
from livekit.plugins import silero

from friday.ai.prompts import load_system_prompt
from friday.ai.providers import build_llm, build_stt, build_tts
from friday.config import config
from friday.core.session import AssistantSession, create_assistant_session

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

load_dotenv()

logger = logging.getLogger("friday-agent")
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Resolve Windows host IP from WSL
# ---------------------------------------------------------------------------

def _get_windows_host_ip() -> str:
    """Get the Windows host IP by looking at the default network route."""
    try:
        # 'ip route' is the most reliable way to find the 'default' gateway
        # which is always the Windows host in WSL.
        cmd = "ip route show default | awk '{print $3}'"
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=2, check=False
        )
        ip = result.stdout.strip()
        if ip:
            logger.info("Resolved Windows host IP via gateway: %s", ip)
            return ip
    except OSError as exc:
        logger.warning("Gateway resolution failed: %s. Trying fallback...", exc)

    # Fallback to your original resolv.conf logic if 'ip route' fails
    try:
        with open("/etc/resolv.conf", "r") as f:
            for line in f:
                if "nameserver" in line:
                    ip = line.split()[1]
                    logger.info("Resolved Windows host IP via nameserver: %s", ip)
                    return ip
    except OSError:
        logger.debug("resolv.conf read failed, using localhost")

    return "127.0.0.1"


def _mcp_server_url() -> str:
    url = f"http://127.0.0.1:{config.MCP_SERVER_PORT}/sse"
    logger.info("MCP Server URL: %s", url)
    return url


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class FridayAgent(Agent):
    """F.R.I.D.A.Y. - Iron Man-style voice assistant."""

    def __init__(self, stt, llm, tts, assistant_session: AssistantSession) -> None:
        super().__init__(
            instructions=load_system_prompt(),
            stt=stt,
            llm=llm,
            tts=tts,
            vad=silero.VAD.load(),
            mcp_servers=[
                __import__("livekit.agents.llm", fromlist=["mcp"]).mcp.MCPServerHTTP(
                    url=_mcp_server_url(),
                    transport_type="sse",
                    client_session_timeout_seconds=30,
                ),
            ],
        )
        self._assistant_session = assistant_session

    async def on_enter(self) -> None:
        """Greet the user based on the current time of day."""
        from datetime import datetime
        hour = datetime.now(UTC).hour  # UTC hour; adjust if local TZ differs

        if hour >= 22 or hour < 4:
            greeting_instruction = (
                "Greet the user with: 'Greetings boss, you're up late at night today. What are you up to?' "
                "Maintain a helpful but dry tone."
            )
        elif 4 <= hour < 12:
            greeting_instruction = (
                "Greet the user with: 'Good morning, boss. Early start today — what are we working on?' "
                "Maintain a helpful but dry tone."
            )
        elif 12 <= hour < 17:
            greeting_instruction = (
                "Greet the user with: 'Good afternoon, boss. What do you need?' "
                "Maintain a helpful but dry tone."
            )
        else:  # 17–21
            greeting_instruction = (
                "Greet the user with: 'Good evening, boss. What are you up to tonight?' "
                "Maintain a helpful but dry tone."
            )

        await self.session.generate_reply(instructions=greeting_instruction)

    async def on_user_turn_completed(
        self,
        turn_ctx: ChatContext,
        new_message: ChatMessage,
    ) -> None:
        """Assemble FRIDAY's budgeted context before the LLM responds.

        The replacement context is applied to ``turn_ctx`` in place; LiveKit
        passes this exact context to the LLM call for the current turn.
        """
        try:
            self._assistant_session.assemble_context_for_turn(turn_ctx, new_message)
        except Exception as exc:  # noqa: BLE001 - degrade, never break the turn
            logger.warning("Context assembly failed; using default LiveKit context: %s", exc)


# ---------------------------------------------------------------------------
# LiveKit entry point
# ---------------------------------------------------------------------------

def _turn_detection() -> str:
    return "stt" if config.STT_PROVIDER == "sarvam" else "vad"


def _endpointing_delay() -> float:
    return {"sarvam": 0.07, "whisper": 0.3}.get(config.STT_PROVIDER, 0.1)


async def entrypoint(ctx: JobContext) -> None:
    logger.info(
        "FRIDAY online – room: %s | STT=%s | LLM=%s | TTS=%s (%s / %s)",
        ctx.room.name,
        config.STT_PROVIDER,
        config.LLM_PROVIDER,
        config.TTS_PROVIDER,
        config.SARVAM_TTS_MODEL,
        config.SARVAM_TTS_VOICE,
    )

    stt = build_stt()
    llm = build_llm()
    tts = build_tts()

    # Create and start AssistantSession (owns stores, managers, context)
    assistant_session = await create_assistant_session()

    # Store in session userdata for event handlers
    session = AgentSession(
        turn_detection=_turn_detection(),
        min_endpointing_delay=_endpointing_delay(),
    )
    session.userdata = {
        "assistant_session": assistant_session,
        "conversation_id": assistant_session.conversation_id,
    }

    # Persist committed conversation items (user/assistant messages) to SQLite
    def _on_conversation_item_added(event) -> None:
        item = event.item
        if not isinstance(item, ChatMessage):
            return

        text = item.text_content
        if not text or item.role not in ("user", "assistant"):
            return

        conv_id = session.userdata["conversation_id"]
        mem = session.userdata["assistant_session"].conversation_store

        if item.role == "user":
            mem.save_message(conv_id, "user", text)
            logger.debug("Persisted user message: %s...", text[:50])
        elif item.role == "assistant":
            mem.save_message(conv_id, "assistant", text)
            logger.debug("Persisted assistant message: %s...", text[:50])

    session.on("conversation_item_added", _on_conversation_item_added)

    # Register shutdown callback to close stores AFTER session fully stops
    async def _cleanup(reason: str = "") -> None:
        await assistant_session.stop()
        logger.info("Closed assistant session (reason: %s)", reason or "shutdown")

    ctx.add_shutdown_callback(_cleanup)

    await session.start(
        agent=FridayAgent(stt=stt, llm=llm, tts=tts, assistant_session=assistant_session),
        room=ctx.room,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))


def dev() -> None:
    """Wrapper to run the agent in dev mode automatically."""
    import sys
    # If no command was provided, inject 'dev'
    if len(sys.argv) == 1:
        sys.argv.append("dev")
    main()


if __name__ == "__main__":
    main()