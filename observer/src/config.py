"""Observer service configuration.

All settings have sensible defaults for docker-compose deployment.
Override via environment variables or .env file.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ObserverSettings(BaseSettings):
    """Configuration for the Observer autonomous improvement agent."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_file_encoding="utf-8",
    )

    # --- Service Identity ---
    service_name: str = "observer"
    service_version: str = "0.1.0"
    port: int = 6000
    log_level: str = "info"

    # --- External Services ---
    llm_gateway_url: str = "http://llm-gateway:4000"
    llm_gateway_admin_url: str = "http://llm-gateway:4001"
    memory_url: str = "http://memory-service:5000"

    # --- Log Ingestion ---
    log_path: str = "/logs"
    log_retention_days: int = 7
    aggregate_retention_days: int = 30

    # --- AWS ---
    aws_region: str = "us-east-1"

    # --- Schedule (seconds) ---
    schedule_quality_sec: int = 3600
    schedule_prompts_sec: int = 21600
    schedule_model_fit_sec: int = 86400
    schedule_self_eval_sec: int = 604800

    # --- Auto-Apply Policy ---
    auto_apply_enabled: bool = True
    auto_apply_min_confidence: float = 0.80
    auto_apply_min_samples: int = 20
    max_auto_applies_per_day: int = 10

    # --- Canary Policy ---
    canary_traffic_pct: int = 20
    canary_min_duration_hours: int = 4
    canary_min_samples: int = 30
    max_concurrent_canaries: int = 3

    # --- Circuit Breaker ---
    circuit_breaker_max_rollbacks: int = 3
    circuit_breaker_window_hours: int = 6
    circuit_breaker_cooldown_hours: int = 12

    # --- Budget ---
    observer_budget_per_cycle_usd: float = 5.00

    # --- Validation ---
    validation_delay_minutes: int = 60

    # --- Self-Regulation Bounds ---
    self_reg_min_confidence_floor: float = 0.60
    self_reg_min_confidence_ceiling: float = 0.95
    self_reg_min_samples_floor: int = 10
    self_reg_min_samples_ceiling: int = 100

    # --- Notifications ---
    notify_webhook_url: str = ""
    notify_on_auto_apply: bool = True
    notify_on_canary: bool = True
    notify_on_rollback: bool = True
    notify_on_circuit_break: bool = True
    notify_on_credit_exhaustion: bool = True

    # --- Detection Thresholds ---
    detect_escalation_rate: float = 0.40
    detect_low_confidence: float = 0.70
    detect_parse_failure_rate: float = 0.15
    detect_cost_spike_multiplier: float = 2.0
    detect_error_rate: float = 0.05
    detect_latency_spike_multiplier: float = 2.0
    detect_stale_pattern_days: int = 90
    detect_min_samples: int = 10

    # --- Model Risk Governance ---
    model_governance_enabled: bool = True
    drift_detection_window_days: int = 7
    drift_threshold_ks_pvalue: float = 0.05
    bias_variance_threshold: float = 0.15
    governance_report_weekly: bool = True
    governance_report_monthly: bool = True

    # --- Database ---
    db_path: str = "/data/observer.db"


# Singleton settings instance
_settings: ObserverSettings | None = None


def get_settings() -> ObserverSettings:
    """Get or create the settings singleton."""
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = ObserverSettings()
    return _settings
