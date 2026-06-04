from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

import structlog
import yaml
from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.models import (
    CanaryConfig,
    CostConfig,
    EmbeddingConfig,
    EmbeddingModelConfig,
    EscalationConfig,
    ModelConfig,
    RoutingConfig,
    TierConfig,
)

logger = structlog.get_logger(__name__)


def _expand_env_vars(value: str) -> str:
    """Expand ${ENV_VAR} references in a string value."""
    if not isinstance(value, str):
        return value
    if "${" not in value:
        return value
    result = value
    start = 0
    while True:
        idx = result.find("${", start)
        if idx == -1:
            break
        end = result.find("}", idx)
        if end == -1:
            break
        var_name = result[idx + 2 : end]
        env_value = os.environ.get(var_name, "")
        result = result[:idx] + env_value + result[end + 1 :]
        start = idx + len(env_value)
    return result


def _process_dict_env_vars(data: Any) -> Any:
    """Recursively expand env vars in a dictionary."""
    if isinstance(data, dict):
        return {k: _process_dict_env_vars(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_process_dict_env_vars(item) for item in data]
    if isinstance(data, str):
        return _expand_env_vars(data)
    return data


def _parse_model_config(raw: dict[str, Any]) -> ModelConfig:
    """Parse a raw model config dict into a ModelConfig."""
    return ModelConfig(
        id=raw.get("id", ""),
        provider=raw.get("provider", ""),
        model=raw.get("model", ""),
        endpoint=raw.get("endpoint", ""),
        api_key=raw.get("api_key", ""),
        max_tokens=raw.get("max_tokens", 4096),
        timeout_ms=raw.get("timeout_ms", 60000),
    )


def _parse_tier_config(raw: dict[str, Any]) -> TierConfig:
    """Parse a raw tier config dict into a TierConfig."""
    models_raw = raw.get("models", [])
    models = [_parse_model_config(m) for m in models_raw]
    return TierConfig(models=models)


def _parse_canary_config(raw: dict[str, Any]) -> dict[str, CanaryConfig]:
    """Parse canary configurations."""
    result: dict[str, CanaryConfig] = {}
    for key, val in raw.items():
        if isinstance(val, dict):
            result[key] = CanaryConfig(
                model=val.get("model", ""),
                traffic_pct=val.get("traffic_pct", 20),
                min_samples=val.get("min_samples", 30),
                min_duration_hours=val.get("min_duration_hours", 4),
            )
    return result


def parse_routing_config(raw_data: dict[str, Any]) -> RoutingConfig:
    """Parse raw YAML data into a validated RoutingConfig."""
    # Parse tiers
    tiers: dict[str, TierConfig] = {}
    for tier_name, tier_data in raw_data.get("tiers", {}).items():
        if isinstance(tier_data, dict):
            tiers[tier_name] = _parse_tier_config(tier_data)

    # Parse escalation
    esc_raw = raw_data.get("escalation", {})
    escalation = EscalationConfig(
        enabled=esc_raw.get("enabled", True),
        max_escalations=esc_raw.get("max_escalations", 2),
        path=esc_raw.get("path", ["fast", "mid", "strong"]),
    )

    # Parse embedding
    emb_raw = raw_data.get("embedding", {})
    emb_model_raw = emb_raw.get("model", {})
    embedding = EmbeddingConfig(
        model=EmbeddingModelConfig(
            provider=emb_model_raw.get("provider", "ollama"),
            model=emb_model_raw.get("model", "nomic-embed-text"),
            endpoint=emb_model_raw.get("endpoint", "http://ollama:11434"),
        )
    )

    # Parse cost
    cost_raw = raw_data.get("cost", {})
    cost = CostConfig(
        max_per_request_usd=cost_raw.get("max_per_request_usd", 1.00),
        max_per_tenant_per_day_usd=cost_raw.get("max_per_tenant_per_day_usd", 50.00),
    )

    # Parse canary
    canary = _parse_canary_config(raw_data.get("canary", {}))

    return RoutingConfig(
        tiers=tiers,
        task_routing=raw_data.get("task_routing", {}),
        agent_routing=raw_data.get("agent_routing", {}),
        tenant_routing=raw_data.get("tenant_routing", {}),
        canary=canary,
        escalation=escalation,
        embedding=embedding,
        rate_limits=raw_data.get("rate_limits", {}),
        cost=cost,
    )


class ConfigLoader:
    """Loads and hot-reloads routing configuration from YAML.

    Uses watchdog file watcher to detect changes and atomically
    swap the config snapshot. Readers never see partial config.
    """

    def __init__(self, config_path: str) -> None:
        self._config_path = Path(config_path)
        self._config: RoutingConfig = RoutingConfig()
        self._lock = threading.Lock()
        self._observer: Observer | None = None
        self._on_reload_callbacks: list[Callable[[RoutingConfig], None]] = []
        self._last_load_time: float = 0.0

    @property
    def config(self) -> RoutingConfig:
        """Get the current routing config (immutable snapshot)."""
        return self._config

    def register_on_reload(self, callback: Callable[[RoutingConfig], None]) -> None:
        """Register a callback invoked after successful config reload."""
        self._on_reload_callbacks.append(callback)

    def load(self) -> RoutingConfig:
        """Load configuration from disk. Returns the parsed config or raises on I/O error."""
        if not self._config_path.exists():
            logger.warning(
                "routing_config_not_found",
                path=str(self._config_path),
            )
            return self._config

        raw_text = self._config_path.read_text(encoding="utf-8")
        raw_data = yaml.safe_load(raw_text) or {}
        raw_data = _process_dict_env_vars(raw_data)

        new_config = parse_routing_config(raw_data)

        with self._lock:
            self._config = new_config
            self._last_load_time = time.time()

        logger.info(
            "routing_config_loaded",
            path=str(self._config_path),
            tiers=list(new_config.tiers.keys()),
            task_routes=len(new_config.task_routing),
        )

        for cb in self._on_reload_callbacks:
            try:
                cb(new_config)
            except Exception as exc:
                logger.error("on_reload_callback_error", error=str(exc))

        return new_config

    def reload(self) -> RoutingConfig:
        """Force reload from disk. Returns new config or keeps old on failure."""
        try:
            return self.load()
        except Exception as exc:
            logger.error(
                "config_reload_failed",
                error=str(exc),
                path=str(self._config_path),
            )
            return self._config

    def start_watching(self) -> None:
        """Start the file watcher for hot-reload."""
        if self._observer is not None:
            return

        watch_dir = str(self._config_path.parent)
        if not Path(watch_dir).exists():
            logger.warning("config_watch_dir_missing", path=watch_dir)
            return

        handler = _ConfigFileHandler(
            target_path=str(self._config_path),
            on_change=self._on_file_changed,
        )
        self._observer = Observer()
        self._observer.schedule(handler, watch_dir, recursive=False)
        self._observer.daemon = True
        self._observer.start()
        logger.info("config_watcher_started", path=watch_dir)

    def stop_watching(self) -> None:
        """Stop the file watcher."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
            logger.info("config_watcher_stopped")

    def _on_file_changed(self) -> None:
        """Handle file change notification with debounce."""
        now = time.time()
        if now - self._last_load_time < 1.0:
            return  # debounce: ignore changes within 1 second of last load
        self.reload()

    def update_routing(self, updates: dict[str, Any]) -> RoutingConfig:
        """Apply routing updates programmatically (from admin API).

        Merges updates into current config and returns the new config.
        """
        # Reload current state from disk as base
        if self._config_path.exists():
            raw_text = self._config_path.read_text(encoding="utf-8")
            raw_data = yaml.safe_load(raw_text) or {}
        else:
            raw_data = {}

        # Merge updates
        for key, value in updates.items():
            if key in raw_data and isinstance(raw_data[key], dict) and isinstance(value, dict):
                raw_data[key].update(value)
            else:
                raw_data[key] = value

        raw_data = _process_dict_env_vars(raw_data)
        new_config = parse_routing_config(raw_data)

        with self._lock:
            self._config = new_config
            self._last_load_time = time.time()

        for cb in self._on_reload_callbacks:
            try:
                cb(new_config)
            except Exception as exc:
                logger.error("on_reload_callback_error", error=str(exc))

        logger.info("routing_config_updated_via_api", updates=list(updates.keys()))
        return new_config


class _ConfigFileHandler(FileSystemEventHandler):
    """Watchdog handler that fires callback on target file modification."""

    def __init__(self, target_path: str, on_change: Callable[[], None]) -> None:
        super().__init__()
        self._target_path = os.path.abspath(target_path)
        self._on_change = on_change

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        if os.path.abspath(str(event.src_path)) == self._target_path:
            self._on_change()
