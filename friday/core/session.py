"""AssistantSession — minimal lifecycle wrapper for FRIDAY context integration.

Owns the context assembly integration with LiveKit. Does NOT orchestrate
memory extraction, compaction, or promotion. Those belong to later milestones.

LiveKit integration contract (verified against livekit-agents 1.6.9):
- ``Agent.on_user_turn_completed(turn_ctx, new_message)`` receives
  ``temp_mutable_chat_ctx`` = ``agent.chat_ctx.copy()``. This copy does NOT
  contain the new user message; LiveKit inserts it into the LLM-call context
  later (``agent_activity._pipeline_reply_task_impl``) and into
  ``agent.chat_ctx`` only after the reply is scheduled.
- The copy IS what ``_generate_reply`` passes to the LLM
  (``agent_activity._generate_reply(..., chat_ctx=temp_mutable_chat_ctx)``),
  so the turn context must be edited IN PLACE — calling ``update_chat_ctx``
  would not affect the current generation and would permanently replace the
  agent's accumulated history with the budgeted subset.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from friday.config import config
from friday.context.manager import (
    ContextManager,
    ProjectContext,
)
from friday.memory.durable_manager import DurableMemoryManager
from friday.memory.sqlite_memory_store import SQLiteMemoryStore
from friday.memory.sqlite_store import Conversation, SQLiteConversationStore
from friday.projects.service import ProjectService, build_project_service

if TYPE_CHECKING:
    from livekit.agents.llm import ChatContext, ChatMessage

    from friday.ai.backend import LLMBackend
    from friday.context.models import ContextSnapshot


class ProjectContextAdapter:
    """Adapts ProjectService to the ProjectContextProvider protocol."""

    def __init__(self, project_service: ProjectService) -> None:
        self._service = project_service

    def get_context(self, project_id: str) -> ProjectContext | None:
        workspace = self._service.get_workspace(project_id)
        try:
            context_md = workspace.read_context(project_id) or ""
            state_dict = workspace.read_state(project_id)
            state_json = str(state_dict) if state_dict else ""
            facts_md = workspace.read_facts(project_id)
            decisions_md = workspace.read_decisions(project_id)
        except OSError:
            return None
        return ProjectContext(
            context_md=context_md,
            state_json=state_json,
            facts_md=facts_md,
            decisions_md=decisions_md,
        )


class AssistantSession:
    """Minimal lifecycle wrapper for FRIDAY context integration.

    Responsibilities:
    - Own SQLite stores (conversations.db, memory.db)
    - Own ContextManager and DurableMemoryManager
    - Own ProjectService
    - Provide context assembly for each LiveKit turn
    - Expose conversation_id and active_project_id

    Does NOT (M7.1b+):
    - Memory extraction scheduling
    - Compaction scheduling
    - Promotion scheduling
    - Task execution state
    """

    def __init__(
        self,
        *,
        friday_home: Path | None = None,
        llm_backend: LLMBackend | None = None,
    ) -> None:
        home = friday_home or config.FRIDAY_HOME

        # Persistence
        self._conversation_store = SQLiteConversationStore()
        self._memory_store = SQLiteMemoryStore()

        # Core managers
        self._memory_manager = DurableMemoryManager(self._memory_store)
        self._project_service = build_project_service(home)
        self._context_manager = ContextManager(
            memory_manager=self._memory_manager,
            project_context_provider=ProjectContextAdapter(self._project_service),
            shrinker=None,  # M7.1a: no shrinker yet; ContextManager handles gracefully
            budget=None,  # Use config defaults
        )

        # Runtime state
        self._conversation: Conversation | None = None
        self._conversation_id: int | None = None
        self._turn_count = 0

    @property
    def conversation_id(self) -> int | None:
        return self._conversation_id

    @property
    def active_project_id(self) -> str | None:
        active = self._project_service.active_project()
        return active.project_id if active else None

    @property
    def project_service(self) -> ProjectService:
        return self._project_service

    @property
    def context_manager(self) -> ContextManager:
        return self._context_manager

    @property
    def memory_manager(self) -> DurableMemoryManager:
        return self._memory_manager

    @property
    def conversation_store(self) -> SQLiteConversationStore:
        return self._conversation_store

    async def start(self) -> None:
        """Create the conversation for this session."""
        self._conversation = self._conversation_store.create_conversation()
        self._conversation_id = self._conversation.id

    async def stop(self) -> None:
        """Close stores in correct order."""
        self._conversation_store.close()
        self._memory_store.close()

    def assemble_context_for_turn(
        self,
        turn_ctx: ChatContext,
        new_message: ChatMessage,
    ) -> ChatContext:
        """Assemble FRIDAY's budgeted context and apply it to the turn.

        ``turn_ctx`` is the mutable copy LiveKit hands to
        ``on_user_turn_completed``; it is what the LLM call consumes, so the
        replacement context is assigned to ``turn_ctx.items`` in place.

        The current user message is intentionally NOT added: LiveKit inserts
        it into the LLM-call context after this hook returns, so adding it
        here would duplicate it.
        """

        # 1. Extract recent messages from LiveKit's turn context
        recent_lk_messages = turn_ctx.messages()
        recent_messages = self._lk_messages_to_context_messages(recent_lk_messages)

        # 2. Get current user message text
        current_user_text = new_message.text_content or ""

        # 3. Assemble via ContextManager
        snapshot = self._context_manager.assemble(
            system_instructions=self._load_system_prompt(),
            current_user_message=current_user_text,
            recent_messages=recent_messages,
            conversation_id=self._conversation_id,
            active_project_id=self.active_project_id,
        )

        # 4. Build replacement ChatContext from snapshot, preserving native
        #    FunctionCall / FunctionCallOutput items from the turn history.
        custom_ctx = self._build_replacement_context(turn_ctx, snapshot)

        # 5. Apply in place so the current LLM generation consumes it.
        turn_ctx.items = custom_ctx.items

        return custom_ctx

    def _lk_messages_to_context_messages(
        self,
        lk_messages: list[ChatMessage],
    ) -> list[tuple[str, str, str]]:
        """Convert LiveKit ChatMessage list to ContextManager Message tuples.

        Filters to user/assistant roles with non-empty content.
        """
        result: list[tuple[str, str, str]] = []
        for msg in lk_messages:
            if msg.role not in ("user", "assistant"):
                continue
            content = msg.text_content or ""
            if not content.strip():
                continue
            result.append((msg.id, msg.role, content))
        return result

    def _build_replacement_context(
        self,
        turn_ctx: ChatContext,
        snapshot: ContextSnapshot,
    ) -> ChatContext:
        """Build the replacement LiveKit ChatContext for the current turn.

        Preserves native ``FunctionCall`` / ``FunctionCallOutput`` items from
        the turn history (never flattened into text) and keeps the budgeted
        subset of ``ChatMessage`` items selected by the ContextManager.

        Order: system instructions, then history in original chronological
        order (budgeted messages + tool items), then project context, durable
        memories, and compressed history as developer messages. The current
        user message is not included — LiveKit inserts it for the LLM call.
        """
        from livekit.agents.llm import ChatContext, ChatMessage

        kept_ids = {message_id for message_id, _role, _content in snapshot.recent_messages}

        ordered: list = []
        if snapshot.system_instructions:
            ordered.append(
                ChatMessage(role="system", content=[snapshot.system_instructions])
            )

        for item in turn_ctx.items:
            if item.type in ("function_call", "function_call_output"):
                # Preserve tool history as native items — do not flatten.
                ordered.append(item)
            elif item.type == "message" and item.id in kept_ids:
                ordered.append(item)

        if snapshot.project_context:
            ordered.append(ChatMessage(role="developer", content=[snapshot.project_context]))
        if snapshot.durable_memories:
            mem_text = "\n".join(f"- {m.content}" for m in snapshot.durable_memories)
            ordered.append(ChatMessage(role="developer", content=[f"Relevant memories:\n{mem_text}"]))
        if snapshot.compressed_history:
            ordered.append(
                ChatMessage(
                    role="developer",
                    content=[f"Previous context summary:\n{snapshot.compressed_history}"],
                )
            )

        return ChatContext(items=ordered)

    def _load_system_prompt(self) -> str:
        """Load system prompt from persona.md."""
        from friday.ai.prompts import load_system_prompt
        return load_system_prompt()


# --- Convenience function for agent_friday.py ---

async def create_assistant_session(
    *,
    friday_home: Path | None = None,
    llm_backend: LLMBackend | None = None,
) -> AssistantSession:
    """Create and start an AssistantSession."""
    session = AssistantSession(friday_home=friday_home, llm_backend=llm_backend)
    await session.start()
    return session