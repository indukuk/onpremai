"""Agent loop: message -> LLM -> tools -> respond (max N rounds).

This is the core processing loop for the compliance assistant. It:
1. Takes the user message
2. Builds context (system prompt with persona, skills, playbook state)
3. Sends to LLM with available tools
4. If LLM returns tool calls: execute them via MCP, append results
5. Repeat until LLM responds with text (no tool calls) or max rounds hit

V2 additions:
- Loads user state doc and event queue on /init
- Triggers session reflection on goodbye/session end
- Handles agent naming on first launch
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from typing import Any

import structlog

from common.clients import LLMClient, MemoryClient
from common.errors import LLMCreditExhaustedError, LLMUnavailableError
from src.agent.context_builder import ContextBuilder
from src.agent.data_only_mode import handle_data_only_message
from src.agent.event_queue import EventQueueHandler
from src.agent.reflection import SessionReflector, should_reflect
from src.agent.user_state import UserStateManager
from src.config import settings
from src.mcp.client import MCPClient
from src.mcp.confirmation import ConfirmationHandler
from src.models import (
    ChatResponse,
    PendingConfirmation,
    SessionState,
    ToolAction,
    UserContext,
)
from src.session import SessionManager
from src.skills.loader import SkillLoader
from src.skills.matcher import SkillMatcher
from src.skills.playbook_engine import PlaybookEngine

logger = structlog.get_logger(__name__)


class AgentLoop:
    """Core agent loop that orchestrates LLM calls, tool execution, and state.

    The loop runs up to max_tool_rounds iterations. Each iteration:
    - Sends conversation to LLM gateway (with tools in OpenAI format)
    - If LLM returns tool_calls: executes them via MCP, appends results
    - If LLM returns only text: done, return response to user
    - If a tool requires confirmation: pause, return pending_confirmation
    """

    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryClient,
        mcp: MCPClient,
        sessions: SessionManager,
        context_builder: ContextBuilder,
        skill_loader: SkillLoader,
        skill_matcher: SkillMatcher,
        playbook_engine: PlaybookEngine,
        confirmation_handler: ConfirmationHandler,
        reflector: SessionReflector | None = None,
        user_state_mgr: UserStateManager | None = None,
        event_handler: EventQueueHandler | None = None,
    ) -> None:
        self._llm = llm
        self._memory = memory
        self._mcp = mcp
        self._sessions = sessions
        self._context_builder = context_builder
        self._skill_loader = skill_loader
        self._skill_matcher = skill_matcher
        self._playbook_engine = playbook_engine
        self._confirmation = confirmation_handler
        self._reflector = reflector
        self._user_state_mgr = user_state_mgr
        self._event_handler = event_handler

    async def handle_init(
        self,
        session: SessionState,
        user: UserContext,
    ) -> ChatResponse:
        """Handle session initialization (/init endpoint).

        V2: Loads user state doc, drains event queue, detects first launch
        for agent naming, then generates proactive opener.
        """
        # Load user state doc (R16)
        user_state = None
        if self._user_state_mgr:
            user_state = await self._user_state_mgr.load(user.user_id, user.tenant_id)

        # Detect first launch
        if user_state is None:
            session.is_first_launch = True
        else:
            session.agent_name = user_state.agent_name

        # Drain event queue (R17)
        events: list[dict[str, Any]] = []
        if self._event_handler:
            events = await self._event_handler.drain(user.user_id, user.tenant_id)

        # Load skills for this role
        skills = await self._skill_loader.load_for_role(
            role=user.role,
            tenant_id=user.tenant_id,
        )
        session.skills_loaded = [s.get("id", s.get("skill_name", "")) for s in skills]

        # Load MCP tools
        tools = await self._mcp.list_tools(jwt_token="")
        session.tools_cache = tools

        # Select persona
        from src.agent.personas import select_persona
        persona = select_persona(user.role)
        session.persona = persona.role

        # Check for active playbook resumption
        playbook_prompt = ""
        if session.active_playbook and session.playbook_step > 0:
            playbook_prompt = await self._playbook_engine.get_step_prompt(
                playbook_id=session.active_playbook,
                step=session.playbook_step,
                data=session.playbook_data,
                tenant_id=user.tenant_id,
            )

        # Build system prompt (with user state + events)
        active_skill_prompt = ""
        if session.active_skill:
            active_skill_prompt = await self._skill_loader.get_skill_prompt(
                skill_id=session.active_skill,
                tenant_id=user.tenant_id,
            )

        system_prompt = await self._context_builder.build(
            user=user,
            session=session,
            active_skill_prompt=active_skill_prompt,
            playbook_step_prompt=playbook_prompt,
            user_state=user_state,
            events=events,
        )

        # First launch: inject naming instruction
        if session.is_first_launch:
            system_prompt += (
                "\n\n## First Launch\n"
                "This is a brand new user. Welcome them warmly and ask what they "
                "would like to call you. You are their personal compliance agent — "
                "let them pick a name for you. Keep it brief and friendly."
            )

        # Build opener message
        opener_content = (
            "This is the start of our session. "
            "Greet me proactively with my current status and priorities."
        )
        if events and self._event_handler:
            opener_content += "\n\n" + self._event_handler.format_for_opener(events)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": opener_content},
        ]

        try:
            task = "skill_execution" if session.active_playbook else "chat_response"
            response = await self._llm.complete(
                messages=messages,
                task=task,
                tenant_id=user.tenant_id,
                tools=self._format_tools_for_llm(tools),
                trace_id=str(uuid.uuid4()),
            )

            # Store initial conversation
            session.conversation_history = [
                {"role": "system", "content": system_prompt},
                {"role": "assistant", "content": response.content},
            ]
            session.message_count = 1
            session.mode = "full"

            await self._sessions.save(session)

            return ChatResponse(
                message=response.content,
                session_id=session.session_id,
                actions=[],
                pending_confirmation=None,
                data_only_mode=False,
            )

        except LLMCreditExhaustedError as exc:
            session.mode = "data_only"
            await self._sessions.save(session)

            menu = await handle_data_only_message(
                message="init",
                session=session,
                user=user,
                mcp=self._mcp,
                estimated_recovery=exc.estimated_recovery,
            )
            return ChatResponse(
                message=menu,
                session_id=session.session_id,
                actions=[],
                pending_confirmation=None,
                data_only_mode=True,
            )

        except LLMUnavailableError:
            session.mode = "data_only"
            await self._sessions.save(session)

            return ChatResponse(
                message=(
                    "I'm having trouble connecting to the AI service. "
                    "I can still help with data queries. "
                    "Type STATUS, TASKS, OVERDUE, EVIDENCE, RISKS, or AUDIT."
                ),
                session_id=session.session_id,
                actions=[],
                pending_confirmation=None,
                data_only_mode=True,
            )

    async def handle_message(
        self,
        message: str,
        session: SessionState,
        user: UserContext,
    ) -> ChatResponse:
        """Handle a user message through the full agent loop.

        V2: handles agent naming on first launch, triggers reflection at session end.
        """
        session.message_count += 1

        # Data-only mode bypass
        if session.mode == "data_only":
            return await self._handle_data_only(message, session, user)

        # Agent naming flow: first launch, agent asked for a name, user responds
        if session.is_first_launch and not session.agent_name:
            return await self._handle_agent_naming(message, session, user)

        # Match skills / continue playbook
        skill_prompt, playbook_prompt = await self._resolve_skill_context(
            message, session, user
        )

        # Build system prompt (if not already in conversation history)
        if not session.conversation_history:
            system_prompt = await self._context_builder.build(
                user=user,
                session=session,
                active_skill_prompt=skill_prompt,
                playbook_step_prompt=playbook_prompt,
            )
            session.conversation_history.append(
                {"role": "system", "content": system_prompt}
            )

        # Add user message to history
        session.conversation_history.append({"role": "user", "content": message})

        # Run the agent loop
        try:
            response = await self._run_loop(session, user)
        except LLMCreditExhaustedError as exc:
            session.mode = "data_only"
            await self._sessions.save(session)
            result = await handle_data_only_message(
                message=message,
                session=session,
                user=user,
                mcp=self._mcp,
                estimated_recovery=exc.estimated_recovery,
            )
            return ChatResponse(
                message=result,
                session_id=session.session_id,
                actions=[],
                pending_confirmation=None,
                data_only_mode=True,
            )
        except LLMUnavailableError:
            session.mode = "data_only"
            await self._sessions.save(session)
            result = await handle_data_only_message(
                message=message,
                session=session,
                user=user,
                mcp=self._mcp,
            )
            return ChatResponse(
                message=result,
                session_id=session.session_id,
                actions=[],
                pending_confirmation=None,
                data_only_mode=True,
            )

        # Trigger reflection if session is ending (R15)
        if self._reflector and should_reflect(session, message):
            asyncio.create_task(
                self._run_reflection(session, user)
            )

        return response

    async def handle_confirm(
        self,
        session: SessionState,
        user: UserContext,
        confirmation_id: str,
    ) -> ChatResponse:
        """Handle confirmation of a pending destructive action."""
        if not session.pending_confirmation:
            return ChatResponse(
                message="No pending action to confirm.",
                session_id=session.session_id,
            )

        if session.pending_confirmation.confirmation_id != confirmation_id:
            return ChatResponse(
                message="Confirmation ID does not match the pending action.",
                session_id=session.session_id,
            )

        # Execute the confirmed tool
        result = await self._confirmation.execute_confirmed(
            tool_name=session.pending_confirmation.tool_name,
            params=session.pending_confirmation.params,
            jwt_token="",
        )

        # Clear pending confirmation
        await self._sessions.clear_pending_confirmation(session)

        action = ToolAction(
            tool_name=session.pending_confirmation.tool_name,
            success=result.get("status") != "error",
            result_summary=str(result.get("data", result.get("message", "")))[:200],
        )

        # Add tool result to conversation and get LLM summary
        session.conversation_history.append({
            "role": "tool",
            "content": str(result.get("data", result)),
            "tool_name": session.pending_confirmation.tool_name,
        })

        try:
            # Get LLM to summarize the result
            response = await self._llm.complete(
                messages=session.conversation_history,
                task="summarize_results",
                tenant_id=user.tenant_id,
                trace_id=str(uuid.uuid4()),
            )
            response_text = response.content
            session.conversation_history.append(
                {"role": "assistant", "content": response_text}
            )
        except (LLMUnavailableError, LLMCreditExhaustedError):
            response_text = (
                f"Action completed: {action.result_summary or 'success'}"
            )
            session.conversation_history.append(
                {"role": "assistant", "content": response_text}
            )

        await self._sessions.save(session)

        return ChatResponse(
            message=response_text,
            session_id=session.session_id,
            actions=[action],
            pending_confirmation=None,
        )

    async def handle_cancel(
        self,
        session: SessionState,
        user: UserContext,
        confirmation_id: str,
    ) -> ChatResponse:
        """Handle cancellation of a pending destructive action."""
        if not session.pending_confirmation:
            return ChatResponse(
                message="No pending action to cancel.",
                session_id=session.session_id,
            )

        tool_name = session.pending_confirmation.tool_name
        await self._sessions.clear_pending_confirmation(session)

        logger.info(
            "action_cancelled",
            tool_name=tool_name,
            user_id=user.user_id,
            tenant_id=user.tenant_id,
        )

        response_text = f"Cancelled. The {tool_name} action was not executed."
        session.conversation_history.append(
            {"role": "assistant", "content": response_text}
        )
        await self._sessions.save(session)

        return ChatResponse(
            message=response_text,
            session_id=session.session_id,
            actions=[],
            pending_confirmation=None,
        )

    async def _run_loop(
        self,
        session: SessionState,
        user: UserContext,
    ) -> ChatResponse:
        """Execute the multi-round tool use loop.

        Up to max_tool_rounds iterations. Each round:
        1. Send messages + tools to LLM
        2. If tool_calls in response: execute via MCP, append results
        3. If text response: done
        4. If tool needs confirmation: pause and return
        """
        tools = session.tools_cache or []
        llm_tools = self._format_tools_for_llm(tools)
        actions: list[ToolAction] = []
        max_rounds = settings.max_tool_rounds

        for round_num in range(max_rounds):
            task = "tool_selection" if round_num == 0 else "skill_execution"

            start_time = time.perf_counter()
            response = await self._llm.complete(
                messages=session.conversation_history,
                task=task,
                tenant_id=user.tenant_id,
                tools=llm_tools if tools else None,
                trace_id=str(uuid.uuid4()),
            )
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

            logger.info(
                "llm_call",
                agent="compliance-assistant",
                task=task,
                model_used=response.model_used,
                latency_ms=latency_ms,
                tool_calls_count=len(response.tool_calls),
                round_num=round_num,
                success=True,
            )

            # No tool calls - final text response
            if not response.tool_calls:
                session.conversation_history.append(
                    {"role": "assistant", "content": response.content}
                )
                await self._sessions.save(session)

                # Update playbook state if active
                if session.active_playbook:
                    await self._playbook_engine.advance_step(session)

                return ChatResponse(
                    message=response.content,
                    session_id=session.session_id,
                    actions=actions,
                    pending_confirmation=None,
                )

            # Execute tool calls
            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name", tool_call.get("function", {}).get("name", ""))
                tool_params = tool_call.get("arguments", tool_call.get("function", {}).get("arguments", {}))
                tool_id = tool_call.get("id", str(uuid.uuid4()))

                if isinstance(tool_params, str):
                    import json
                    try:
                        tool_params = json.loads(tool_params)
                    except (json.JSONDecodeError, TypeError):
                        tool_params = {}

                # Execute via MCP
                tool_start = time.perf_counter()
                result = await self._mcp.call_tool(
                    tool_name=tool_name,
                    params=tool_params,
                    jwt_token="",
                )
                tool_latency = round((time.perf_counter() - tool_start) * 1000, 2)

                # Check if confirmation required
                if result.get("status") == "confirmation_required":
                    confirmation = PendingConfirmation(
                        confirmation_id=str(uuid.uuid4()),
                        tool_name=tool_name,
                        summary=result.get("summary", f"Confirm execution of {tool_name}"),
                        params=tool_params,
                    )
                    await self._sessions.set_pending_confirmation(session, confirmation)

                    # Add partial context to conversation
                    session.conversation_history.append({
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": response.tool_calls,
                    })
                    await self._sessions.save(session)

                    return ChatResponse(
                        message=result.get("summary", f"Please confirm: {tool_name}"),
                        session_id=session.session_id,
                        actions=actions,
                        pending_confirmation=confirmation,
                    )

                # Tool executed successfully
                tool_success = result.get("status") != "error"
                tool_result_str = str(result.get("data", result.get("result", result)))

                logger.info(
                    "tool_call",
                    tool_name=tool_name,
                    duration_ms=tool_latency,
                    success=tool_success,
                )

                actions.append(ToolAction(
                    tool_name=tool_name,
                    success=tool_success,
                    result_summary=tool_result_str[:200],
                ))

                # Append tool result to conversation
                session.conversation_history.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [tool_call],
                })
                session.conversation_history.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": tool_result_str[:4000],
                })

        # Max rounds exceeded - respond with partial results
        session.conversation_history.append({
            "role": "assistant",
            "content": (
                "I've reached the maximum number of tool operations for this turn. "
                "Here's what I was able to accomplish so far."
            ),
        })
        await self._sessions.save(session)

        return ChatResponse(
            message=(
                "I've completed several actions but reached my processing limit. "
                "Let me know if you'd like me to continue."
            ),
            session_id=session.session_id,
            actions=actions,
            pending_confirmation=None,
        )

    async def _handle_agent_naming(
        self,
        message: str,
        session: SessionState,
        user: UserContext,
    ) -> ChatResponse:
        """Capture the agent name from user's response on first launch."""
        # Extract name: strip quotes, punctuation, limit to 30 chars
        name = re.sub(r'["\'.!?]', "", message).strip()[:30]

        if not name:
            name = "Assistant"

        session.agent_name = name
        session.is_first_launch = False

        # Persist to user state doc
        if self._user_state_mgr:
            await self._user_state_mgr.set_agent_name(
                user.user_id, user.tenant_id, name
            )

        # Add to conversation and generate acknowledgment
        session.conversation_history.append({"role": "user", "content": message})

        ack_prompt = (
            f"The user has chosen to name you '{name}'. "
            f"Acknowledge the name warmly (one sentence), then transition to "
            f"showing their current compliance status and priorities."
        )
        session.conversation_history.append({"role": "user", "content": ack_prompt})

        try:
            response = await self._llm.complete(
                messages=session.conversation_history,
                task="chat_response",
                tenant_id=user.tenant_id,
                tools=self._format_tools_for_llm(session.tools_cache or []),
                trace_id=str(uuid.uuid4()),
            )

            # Remove the synthetic prompt, keep the real message
            session.conversation_history.pop()
            session.conversation_history.append(
                {"role": "assistant", "content": response.content}
            )
            await self._sessions.save(session)

            return ChatResponse(
                message=response.content,
                session_id=session.session_id,
                actions=[],
                pending_confirmation=None,
            )

        except (LLMUnavailableError, LLMCreditExhaustedError):
            session.conversation_history.pop()
            fallback = f"{name} it is! Let me show you where things stand."
            session.conversation_history.append(
                {"role": "assistant", "content": fallback}
            )
            await self._sessions.save(session)

            return ChatResponse(
                message=fallback,
                session_id=session.session_id,
                actions=[],
                pending_confirmation=None,
            )

    async def _run_reflection(
        self,
        session: SessionState,
        user: UserContext,
    ) -> None:
        """Run session reflection and merge into user state doc. Fire-and-forget."""
        try:
            if not self._reflector:
                return

            reflection = await self._reflector.reflect(
                session=session,
                user_id=user.user_id,
                tenant_id=user.tenant_id,
            )

            if reflection and self._user_state_mgr:
                doc = await self._user_state_mgr.load(user.user_id, user.tenant_id)
                if doc is None:
                    from src.agent.user_state import UserStateDoc
                    doc = UserStateDoc(
                        user_id=user.user_id,
                        tenant_id=user.tenant_id,
                        agent_name=session.agent_name,
                    )

                doc = self._user_state_mgr.merge_reflection(
                    doc=doc,
                    reflection=reflection,
                    active_skill=session.active_skill,
                    message_count=session.message_count,
                )
                await self._user_state_mgr.save(doc)

        except Exception as exc:
            logger.warning(
                "reflection_failed",
                session_id=session.session_id,
                error=str(exc),
            )

    async def _handle_data_only(
        self,
        message: str,
        session: SessionState,
        user: UserContext,
    ) -> ChatResponse:
        """Route message through data-only mode (keyword matching)."""
        # Check if LLM is back online (attempt a lightweight call)
        try:
            test_response = await self._llm.complete(
                messages=[{"role": "user", "content": "ping"}],
                task="chat_response",
                tenant_id=user.tenant_id,
                max_tokens=5,
            )
            # LLM is back! Switch to full mode
            session.mode = "full"
            logger.info("llm_recovered", tenant_id=user.tenant_id)
            return await self.handle_message(message, session, user)
        except (LLMUnavailableError, LLMCreditExhaustedError):
            pass  # Still in data-only mode

        result = await handle_data_only_message(
            message=message,
            session=session,
            user=user,
            mcp=self._mcp,
        )
        return ChatResponse(
            message=result,
            session_id=session.session_id,
            actions=[],
            pending_confirmation=None,
            data_only_mode=True,
        )

    async def _resolve_skill_context(
        self,
        message: str,
        session: SessionState,
        user: UserContext,
    ) -> tuple[str, str]:
        """Resolve active skill prompt and playbook step prompt."""
        skill_prompt = ""
        playbook_prompt = ""

        # If there's an active playbook, get current step prompt
        if session.active_playbook and session.playbook_step > 0:
            playbook_prompt = await self._playbook_engine.get_step_prompt(
                playbook_id=session.active_playbook,
                step=session.playbook_step,
                data=session.playbook_data,
                tenant_id=user.tenant_id,
            )

        # Try to match a new skill trigger
        matched_skill = self._skill_matcher.match(
            message=message,
            role=user.role,
            active_skill=session.active_skill,
        )

        if matched_skill:
            session.active_skill = matched_skill
            skill_prompt = await self._skill_loader.get_skill_prompt(
                skill_id=matched_skill,
                tenant_id=user.tenant_id,
            )

            # Check if skill has a playbook
            playbook_id = await self._skill_loader.get_skill_playbook(
                skill_id=matched_skill,
                tenant_id=user.tenant_id,
            )
            if playbook_id and not session.active_playbook:
                session.active_playbook = playbook_id
                session.playbook_step = 1
                session.playbook_data = {}
                playbook_prompt = await self._playbook_engine.get_step_prompt(
                    playbook_id=playbook_id,
                    step=1,
                    data={},
                    tenant_id=user.tenant_id,
                )
        elif session.active_skill and not matched_skill:
            # Continue with existing active skill
            skill_prompt = await self._skill_loader.get_skill_prompt(
                skill_id=session.active_skill,
                tenant_id=user.tenant_id,
            )

        return skill_prompt, playbook_prompt

    def _format_tools_for_llm(self, mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert MCP tool definitions to OpenAI function-calling format.

        The LLM gateway expects tools in the OpenAI format:
        {type: "function", function: {name, description, parameters}}
        """
        llm_tools: list[dict[str, Any]] = []

        for tool in mcp_tools:
            name = tool.get("name", "")
            description = tool.get("description", "")
            params = tool.get("inputSchema", tool.get("parameters", {}))

            llm_tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": params if params else {"type": "object", "properties": {}},
                },
            })

        return llm_tools
