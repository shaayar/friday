"""AssistantSession — minimal lifecycle wrapper for FRIDAY context integration.

Owns the context assembly integration with LiveKit and coordinates
post-turn background tasks. Does NOT orchestrate memory extraction,
compaction, or promotion directly; those are invoked via the background
task scheduling seam.

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

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from friday.compaction.compactor import ConversationCompactor
from friday.compaction.extractor import ConversationCompactionExtractor
from friday.compaction.models import ConversationCompaction
from friday.compaction.promoter import ConversationMemoryPromoter
from friday.compaction.promotion_store import SQLitePromotionStore
from friday.compaction.sqlite_store import SQLiteCompactionStore
from friday.config import config
from friday.context.manager import (
    ContextManager,
    ProjectContext,
)
from friday.memory.durable_manager import DurableMemoryManager
from friday.memory.extractor import MemoryExtractor
from friday.memory.resolver import MemoryResolver
from friday.memory.sqlite_memory_store import SQLiteMemoryStore
from friday.memory.sqlite_store import Conversation, SQLiteConversationStore
from friday.projects.service import ProjectService, build_project_service

if TYPE_CHECKING:
    from livekit.agents.llm import ChatContext, ChatMessage

    from friday.ai.backend import LLMBackend
    from friday.context.models import ContextSnapshot

logger = logging.getLogger(__name__)


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
    - Coordinate post-turn background tasks
    - Schedule memory extraction (M7.1b.2)
    - Schedule compaction evaluation (M7.1b.3)

    Does NOT (M7.1b+):
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
        self._memory_store = SQLiteMemoryStore(home / "data" / "memory.db")

        # Core managers
        self._memory_manager = DurableMemoryManager(self._memory_store)
        self._project_service = build_project_service(home)
        self._context_manager = ContextManager(
            memory_manager=self._memory_manager,
            project_context_provider=ProjectContextAdapter(self._project_service),
            shrinker=None,  # M7.1a: no shrinker yet; ContextManager handles gracefully
            budget=None,  # Use config defaults
        )

        # Memory extraction pipeline (M7.1b.2)
        if llm_backend is None:
            # Defer extractor creation until a backend is provided
            self._memory_extractor = None
        else:
            self._memory_extractor = MemoryExtractor(
                llm=llm_backend,
                window_size=config.EXTRACTION_WINDOW_MESSAGES,
                min_messages=1,
            )
        self._memory_resolver = MemoryResolver()
        self._extraction_interval = config.EXTRACTION_CADENCE_TURNS

        # Compaction pipeline (M7.1b.3)
        self._compaction_extractor = None
        self._compactor = None
        self._compaction_store = None
        if llm_backend is not None:
            self._compaction_extractor = ConversationCompactionExtractor(
                llm=llm_backend,
                compaction_version=1,
            )
            self._compaction_store = SQLiteCompactionStore()
            self._compactor = ConversationCompactor(
                store=self._compaction_store,
                extractor=self._compaction_extractor,
            )

        # Promotion pipeline (M7.1b.4) — constructs dependencies; execution wired later
        self._promotion_store = SQLitePromotionStore()
        self._promoter = ConversationMemoryPromoter(
            promotion_store=self._promotion_store,
            memory_manager=self._memory_manager,
            resolver=self._memory_resolver,
        )

        # Runtime state
        self._conversation: Conversation | None = None
        self._conversation_id: int | None = None
        self._turn_count = 0

        # Background task coordination (M7.1b.1)
        self._background_tasks: set[asyncio.Task] = set()
        self._stopping = False

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

    # --- Background task coordination (M7.1b.1) ---

    def _schedule_background(self, coro) -> asyncio.Task | None:
        """Schedule a background coroutine and track its lifecycle.

        Returns the created Task, or None if the session is stopping. A
        rejected coroutine is closed explicitly so it is never leaked.
        """
        if self._stopping:
            logger.debug("Session stopping; background task not scheduled")
            coro.close()
            return None

        task = asyncio.create_task(coro)
        self._background_tasks.add(task)

        def _task_done(t: asyncio.Task) -> None:
            self._background_tasks.discard(t)
            if t.cancelled():
                logger.debug("Background task cancelled: %s", t.get_name())
            elif t.exception() is not None:
                # Exception is observed here; we log it to avoid
                # "Task exception was never retrieved" warnings.
                logger.warning(
                    "Background task %s failed: %s",
                    t.get_name(),
                    t.exception(),
                    exc_info=t.exception(),
                )

        task.add_done_callback(_task_done)
        return task

    async def _wait_background_tasks(self, timeout: float = 5.0) -> None:
        """Cancel and await all owned background tasks."""
        if not self._background_tasks:
            return

        logger.info("Cancelling %d background task(s)", len(self._background_tasks))
        for task in self._background_tasks:
            if not task.done():
                task.cancel()

        # Await with timeout; don't let shutdown hang indefinitely
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._background_tasks, return_exceptions=True),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning("Background task shutdown timed out after %.1fs", timeout)
        finally:
            self._background_tasks.clear()

    # --- Session lifecycle ---

    async def start(self) -> None:
        """Create the conversation for this session."""
        self._conversation = self._conversation_store.create_conversation()
        self._conversation_id = self._conversation.id
        logger.info("AssistantSession started: conversation_id=%s", self._conversation_id)

    async def stop(self) -> None:
        """Close stores and cancel/await background tasks in correct order."""
        if self._stopping:
            return
        self._stopping = True

        logger.info("Stopping AssistantSession (conversation_id=%s)", self._conversation_id)

        # 1. Prevent new background work
        # 2. Cancel and await owned background tasks
        await self._wait_background_tasks()

        # 3. Close stores
        self._conversation_store.close()
        self._memory_store.close()
        if self._compaction_store is not None:
            self._compaction_store.close()
        if self._promotion_store is not None:
            self._promotion_store.close()
        logger.info("AssistantSession stopped")

    # --- Context assembly ---

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


# --- Post-turn memory extraction (M7.1b.2) ---

    def on_assistant_persisted(self) -> None:
        """Sync dispatcher called from the agent's non-async event handler.

        Schedules both post-turn pipelines as independent, tracked background
        tasks. Memory extraction and compaction evaluation are isolated: a
        failure in one never prevents the other from running.
        """
        self._schedule_background(self.on_assistant_message_persisted())
        self._schedule_background(self.on_assistant_message_persisted_for_compaction())

    async def on_assistant_message_persisted(self) -> None:
        """Call this after an assistant message is persisted to trigger extraction cadence."""
        if self._stopping:
            return
        if self._memory_extractor is None:
            logger.debug("Memory extractor not available; skipping extraction")
            return

        self._turn_count += 1
        if self._turn_count % self._extraction_interval != 0:
            return

        # Schedule background memory extraction
        logger.info(
            "Scheduling memory extraction (turn %d, interval %d)",
            self._turn_count,
            self._extraction_interval,
        )
        self._schedule_background(self._run_memory_extraction())

    async def _run_memory_extraction(self) -> None:
        """Run the full memory extraction pipeline in background."""
        if self._conversation_id is None:
            logger.warning("No conversation_id; cannot run memory extraction")
            return

        extractor = self._memory_extractor
        if extractor is None:
            logger.debug("Memory extractor not available; skipping extraction")
            return

        try:
            # 1. Get recent messages from conversation store
            messages = self._conversation_store.get_recent_messages(
                self._conversation_id, limit=extractor._window_size * 2
            )

            if not messages:
                logger.debug("No messages to extract from")
                return

            # Convert to extractor format: (message_id, role, content)
            extraction_messages = [
                (str(msg.id), msg.role, msg.content)
                for msg in messages
            ]

            # 2. Run extraction
            project_id = self.active_project_id
            logger.debug(
                "Running memory extraction for conversation %s (project_id=%s)",
                self._conversation_id,
                project_id,
            )
            candidates = await extractor.extract(
                extraction_messages,
                conversation_id=self._conversation_id,
                project_id=project_id,
            )

            if not candidates:
                logger.debug("No memory candidates extracted")
                return

            # 3. Resolve candidates against existing memories
            existing = self._memory_manager.get_active(
                valid_at=None, limit=1000
            )
            resolutions = self._memory_resolver.resolve(
                candidates, existing_memories=existing
            )

            # 4. Apply resolutions in batch
            applied = self._memory_manager.apply_batch(resolutions)
            created = sum(1 for m in applied if m is not None)
            logger.info(
                "Memory extraction complete: %d candidates → %d resolutions → %d memories",
                len(candidates),
                len(resolutions),
                created,
            )

        except Exception as exc:  # noqa: BLE001 - isolation boundary
            logger.warning("Memory extraction failed: %s", exc)
            # Exception is logged; task callback will handle it

# --- Post-turn compaction evaluation (M7.1b.3) ---

    async def on_assistant_message_persisted_for_compaction(self) -> None:
        """Call this after an assistant message is persisted to evaluate compaction."""
        if self._stopping:
            return
        if self._compactor is None:
            logger.debug("Compactor not available; skipping compaction check")
            return

        # Schedule background compaction evaluation
        logger.info("Scheduling compaction check")
        self._schedule_background(self._run_compaction_check())

    async def _run_compaction_check(self) -> None:
        """Run compaction evaluation in background."""
        if self._conversation_id is None:
            logger.warning("No conversation_id; cannot run compaction check")
            return

        compactor = self._compactor
        if compactor is None:
            logger.debug("Compactor not available; skipping compaction check")
            return

        try:
            # Get all messages from conversation store for compaction evaluation
            messages = self._conversation_store.get_recent_messages(
                self._conversation_id, limit=1000  # Large enough to get full history
            )

            if not messages:
                logger.debug("No messages for compaction check")
                return

            logger.debug(
                "Running compaction check for conversation %s (%d messages)",
                self._conversation_id,
                len(messages),
            )

            # Run compaction (compactor decides whether threshold is met)
            result = await compactor.compact(messages, conversation_id=self._conversation_id, force=False)

            if result.compacted and result.compaction is not None:
                logger.info(
                    "Compaction completed: id=%s, remaining_messages=%d",
                    result.compaction.compaction_id,
                    result.remaining_messages,
                )
                # Schedule promotion as a separate background task after successful compaction
                self._schedule_background(self._run_promotion(result.compaction))
            else:
                logger.debug("Compaction check: no compaction needed (remaining_messages=%d)", result.remaining_messages)

        except Exception as exc:  # noqa: BLE001 - isolation boundary
            logger.warning("Compaction check failed: %s", exc)
            # Exception is logged; task callback will handle it

    async def _run_promotion(self, compaction: ConversationCompaction) -> None:
        """Run promotion after successful compaction in background."""
        if self._stopping:
            return
        if self._promoter is None:
            logger.debug("Promoter not available; skipping promotion")
            return

        try:
            logger.debug(
                "Running promotion for compaction %s (project_id=%s)",
                compaction.compaction_id,
                self.active_project_id,
            )
            result = self._promoter.promote(
                compaction,
                project_id=self.active_project_id,
            )
            promoted_count = sum(1 for r in result.items if r.outcome == "promoted")
            skipped_count = sum(1 for r in result.items if r.outcome == "skipped")
            rejected_count = sum(1 for r in result.items if r.outcome == "rejected")
            logger.info(
                "Promotion complete for compaction %s: promoted=%d, skipped=%d, rejected=%d",
                compaction.compaction_id,
                promoted_count,
                skipped_count,
                rejected_count,
            )
        except Exception as exc:  # noqa: BLE001 - isolation boundary
            logger.warning("Promotion failed for compaction %s: %s", compaction.compaction_id, exc)
            # Exception is logged; task callback will handle it


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