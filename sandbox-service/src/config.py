"""Configuration for Sandbox Service via environment variables.

All limits have defaults matching REQUIREMENTS.md R4/R10. Hard maximums
are enforced here -- agent requests exceeding them are rejected at the API layer.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class SandboxSettings(BaseSettings):
    """Sandbox service configuration loaded from environment variables."""

    # --- Service ---
    port: int = 6000
    log_level: str = "info"

    # --- Storage ---
    storage_endpoint: str = "http://minio:9000"
    storage_bucket: str = "compliance-artifacts"
    storage_access_key: str = ""
    storage_secret_key: str = ""
    storage_backend: str = "minio"

    # --- Execution backend ---
    execution_backend: str = "docker"
    docker_socket: str = "/var/run/docker.sock"
    runtime_image: str = "yourorg/compliance-sandbox-runtime:latest"

    # --- Concurrency ---
    max_concurrent_executions: int = 5
    queue_size: int = 20

    # --- Timeouts ---
    default_timeout_sec: int = 60
    max_timeout_sec: int = 300

    # --- Memory ---
    default_memory_mb: int = 512
    max_memory_mb: int = 2048

    # --- CPU ---
    default_cpus: float = 1.0
    max_cpus: float = 2.0

    # --- Output ---
    max_output_size_mb: int = 1

    # --- Files ---
    max_file_count: int = 10
    max_total_file_size_mb: int = 100

    # --- Temp directory ---
    sandbox_tmp_dir: str = "/tmp/sandbox"

    model_config = {"env_prefix": "", "case_sensitive": False}


def get_settings() -> SandboxSettings:
    """Return a cached settings instance."""
    return SandboxSettings()
