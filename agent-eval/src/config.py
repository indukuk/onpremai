"""Configuration for agent-eval service.

All settings have sensible defaults for docker-compose deployment.
Override via environment variables or .env file.
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/app")

from common.config import CommonSettings


class EvalSettings(CommonSettings):
    """Agent-eval specific settings extending CommonSettings."""

    service_name: str = "agent-eval"
    agent_type: str = "evaluator"

    # --- Endpoints ---
    preprocessor_url: str = "http://preprocessor:7000"

    # --- Evaluation ---
    max_eval_timeout_sec: int = 300
    max_sandbox_retries: int = 2
    rag_index_path: str = "/data/rag/"

    # --- Concurrency ---
    max_concurrent_evaluations: int = 10

    # --- Caching ---
    cache_staleness_hours: int = 168  # 7 days default

    # --- LLM Judgment (Adversarial Tribunal) ---
    consensus_weight_threshold: float = 0.20  # >= this: full tribunal
    tribunal_confidence_threshold: float = 0.70  # below this: escalate to retry
    tribunal_max_retries: int = 1  # max re-tribunals on low confidence


def get_settings() -> EvalSettings:
    """Get cached settings instance."""
    return EvalSettings()
