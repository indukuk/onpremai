"""Request/response models for the compliance-assistant HTTP API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class UserContext(BaseModel):
    """User context extracted from JWT and passed by frontend."""

    tenant_id: str
    user_id: str
    role: str
    email: str = ""
    name: str = ""


class ChatRequest(BaseModel):
    """POST /chat request body."""

    message: str
    session_id: str
    user_context: UserContext


class InitRequest(BaseModel):
    """POST /init request body - initialize a new session."""

    session_id: str
    user_context: UserContext


class ConfirmRequest(BaseModel):
    """POST /confirm request body - approve a pending destructive action."""

    session_id: str
    user_context: UserContext
    confirmation_id: str


class CancelRequest(BaseModel):
    """POST /cancel request body - reject a pending action."""

    session_id: str
    user_context: UserContext
    confirmation_id: str


class PendingConfirmation(BaseModel):
    """A pending human-in-the-loop confirmation."""

    confirmation_id: str
    tool_name: str
    summary: str
    params: dict[str, Any] = Field(default_factory=dict)


class ToolAction(BaseModel):
    """A tool action that was executed during the chat turn."""

    tool_name: str
    success: bool
    result_summary: str = ""


class ChatResponse(BaseModel):
    """Response for /chat, /init, /confirm, /cancel endpoints."""

    message: str
    session_id: str
    actions: list[ToolAction] = Field(default_factory=list)
    pending_confirmation: PendingConfirmation | None = None
    data_only_mode: bool = False


class SessionState(BaseModel):
    """Persistent session state stored in Redis via memory-service."""

    session_id: str
    tenant_id: str
    user_id: str
    role: str
    persona: str = ""
    mode: str = "full"  # "full" or "data_only"
    active_skill: str | None = None
    active_playbook: str | None = None
    playbook_step: int = 0
    playbook_data: dict[str, Any] = Field(default_factory=dict)
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)
    pending_confirmation: PendingConfirmation | None = None
    skills_loaded: list[str] = Field(default_factory=list)
    tools_cache: list[dict[str, Any]] = Field(default_factory=list)
    message_count: int = 0
    is_first_launch: bool = False
    agent_name: str = ""
