from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Tier(str, Enum):
    """Model capability tiers."""

    FAST = "fast"
    MID = "mid"
    STRONG = "strong"


class MessageRole(str, Enum):
    """Message roles in a conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    """A single message in a conversation."""

    model_config = ConfigDict(extra="allow")

    role: MessageRole
    content: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


class ToolFunction(BaseModel):
    """Function definition within a tool."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class Tool(BaseModel):
    """Tool definition in OpenAI function-calling format."""

    type: str = "function"
    function: ToolFunction


class ToolCallFunction(BaseModel):
    """A function call returned by the model."""

    name: str
    arguments: str  # JSON string


class ToolCall(BaseModel):
    """A tool call from model response."""

    id: str
    type: str = "function"
    function: ToolCallFunction


class ResponseFormat(BaseModel):
    """Requested response format."""

    type: str = "text"
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")

    model_config = ConfigDict(populate_by_name=True)


class CompletionRequest(BaseModel):
    """Request to the /v1/complete endpoint."""

    model_config = ConfigDict(extra="ignore")

    messages: list[Message]
    task: str = Field(description="Task name for routing, e.g. evaluate_control")
    agent: str = Field(default="unknown", description="Agent identifier")
    tenant_id: str = Field(description="Tenant identifier for budget/routing")
    trace_id: str = Field(default="", description="Distributed trace ID")
    confidence_threshold: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum confidence to accept without escalation",
    )
    max_tokens: int = Field(default=4096, ge=1, le=128000)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    response_format: ResponseFormat | None = None
    tools: list[Tool] | None = None
    stop: list[str] | None = None


class Usage(BaseModel):
    """Token usage statistics."""

    input_tokens: int = 0
    output_tokens: int = 0


class CompletionResponse(BaseModel):
    """Response from the /v1/complete endpoint."""

    content: str | None = None
    model_used: str = ""
    tier_used: str = ""
    escalated: bool = False
    escalation_path: list[str] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = 0
    confidence: float = 0.0
    tool_calls: list[ToolCall] | None = None
    cost_usd: float = 0.0
    trace_id: str = ""


class EmbedRequest(BaseModel):
    """Request to the /v1/embed endpoint."""

    texts: list[str] = Field(min_length=1, description="Texts to embed")
    tenant_id: str = Field(description="Tenant identifier")
    trace_id: str = Field(default="", description="Distributed trace ID")


class EmbedResponse(BaseModel):
    """Response from the /v1/embed endpoint."""

    embeddings: list[list[float]]
    model_used: str = ""
    latency_ms: int = 0


class ModelConfig(BaseModel):
    """Configuration for a single model within a tier."""

    model_config = ConfigDict(extra="ignore")

    id: str
    provider: str
    model: str
    endpoint: str = ""
    api_key: str = ""
    max_tokens: int = 4096
    timeout_ms: int = 60000
    healthy: bool = True
    enabled: bool = True


class TierConfig(BaseModel):
    """Configuration for a model tier."""

    models: list[ModelConfig] = Field(default_factory=list)


class CanaryConfig(BaseModel):
    """Canary experiment configuration."""

    model: str
    traffic_pct: int = Field(default=20, ge=1, le=100)
    min_samples: int = Field(default=30, ge=1)
    min_duration_hours: int = Field(default=4, ge=1)


class EscalationConfig(BaseModel):
    """Escalation configuration."""

    enabled: bool = True
    max_escalations: int = 2
    path: list[str] = Field(default_factory=lambda: ["fast", "mid", "strong"])


class RateLimitConfig(BaseModel):
    """Rate limiting configuration."""

    requests_per_minute: int = 60
    tokens_per_minute: int = 100000


class CostConfig(BaseModel):
    """Cost ceiling configuration."""

    max_per_request_usd: float = 1.00
    max_per_tenant_per_day_usd: float = 50.00


class EmbeddingModelConfig(BaseModel):
    """Embedding model configuration."""

    provider: str = "ollama"
    model: str = "nomic-embed-text"
    endpoint: str = "http://ollama:11434"


class EmbeddingConfig(BaseModel):
    """Embedding configuration."""

    model: EmbeddingModelConfig = Field(default_factory=EmbeddingModelConfig)


class RoutingConfig(BaseModel):
    """Complete routing configuration loaded from YAML."""

    model_config = ConfigDict(extra="ignore")

    tiers: dict[str, TierConfig] = Field(default_factory=dict)
    task_routing: dict[str, str] = Field(default_factory=dict)
    agent_routing: dict[str, dict[str, Any]] = Field(default_factory=dict)
    tenant_routing: dict[str, dict[str, Any]] = Field(default_factory=dict)
    canary: dict[str, CanaryConfig] = Field(default_factory=dict)
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    rate_limits: dict[str, Any] = Field(default_factory=dict)
    cost: CostConfig = Field(default_factory=CostConfig)


class NormalizedRequest(BaseModel):
    """Provider-agnostic normalized request for adapters."""

    messages: list[Message]
    tools: list[Tool] | None = None
    max_tokens: int = 4096
    temperature: float = 0.0
    response_format: ResponseFormat | None = None
    stop: list[str] | None = None
    model: str = ""


class NormalizedResponse(BaseModel):
    """Provider-agnostic normalized response from adapters."""

    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    usage: Usage = Field(default_factory=Usage)
    finish_reason: str = "stop"
    raw_response: dict[str, Any] = Field(default_factory=dict)


class CanaryMetrics(BaseModel):
    """Metrics for a canary experiment variant."""

    sample_count: int = 0
    avg_confidence: float = 0.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    error_rate: float = 0.0
    escalation_rate: float = 0.0
    avg_cost_usd: float = 0.0


class CanaryStatus(BaseModel):
    """Complete canary experiment status."""

    task: str
    active: bool = False
    model: str = ""
    traffic_pct: int = 0
    started_at: float = Field(default_factory=time.time)
    control: CanaryMetrics = Field(default_factory=CanaryMetrics)
    canary: CanaryMetrics = Field(default_factory=CanaryMetrics)


class BudgetStatus(BaseModel):
    """Per-tenant budget status."""

    tenant_id: str
    daily_spend_usd: float = 0.0
    daily_limit_usd: float = 50.0
    degradation_level: int = 0
    requests_today: int = 0
    queued_requests: int = 0


class ModelHealth(BaseModel):
    """Model health status."""

    id: str
    provider: str
    model: str
    healthy: bool = True
    enabled: bool = True
    last_check_ms: int = 0
    consecutive_failures: int = 0
    tier: str = ""
