"""
E2E test fixtures for the compliance AI platform.

Provides:
  - service_urls: dict of all service base URLs
  - s2s_headers: service-to-service auth headers
  - jwt_token_for(user_id): generate test JWTs
  - seed_data: runs testdata/setup.py once per session
  - httpx AsyncClient per service
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncGenerator

import httpx
import jwt
import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Service URLs (from docker-compose port mappings, accessible from host)
SERVICE_URLS = {
    "llm_gateway": os.environ.get("LLM_GATEWAY_URL", "http://localhost:4000"),
    "llm_gateway_admin": os.environ.get("LLM_GATEWAY_ADMIN_URL", "http://localhost:4001"),
    "memory_service": os.environ.get("MEMORY_SERVICE_URL", "http://localhost:5000"),
    "sandbox_service": os.environ.get("SANDBOX_SERVICE_URL", "http://localhost:6000"),
    "preprocessor": os.environ.get("PREPROCESSOR_URL", "http://localhost:7000"),
    "agent_eval": os.environ.get("AGENT_EVAL_URL", "http://localhost:8080"),
    "compliance_assistant": os.environ.get("COMPLIANCE_ASSISTANT_URL", "http://localhost:8081"),
    "observer": os.environ.get("OBSERVER_URL", "http://localhost:9002"),
    "minio": os.environ.get("MINIO_ENDPOINT", "http://localhost:9000"),
}

# Test JWT secret (must match services' dev-mode secret for test environments)
JWT_SECRET = os.environ.get("JWT_SECRET", "e2e-test-secret-key-do-not-use-in-production")
JWT_ALGORITHM = "HS256"

# Service-to-service authentication
S2S_SERVICE_ID = "test-harness"
S2S_SERVICE_KEY = "test-harness-key-dev"

# Test user data (loaded from testdata/users.json)
TESTDATA_DIR = Path(__file__).resolve().parent.parent.parent / "testdata"


# ---------------------------------------------------------------------------
# User lookup
# ---------------------------------------------------------------------------


def _load_users() -> dict:
    """Load user definitions from testdata."""
    users_file = TESTDATA_DIR / "users.json"
    with open(users_file) as f:
        data = json.load(f)
    return {u["id"]: u for u in data["users"]}


USERS = _load_users()


# ---------------------------------------------------------------------------
# JWT Token Helper
# ---------------------------------------------------------------------------


def generate_test_jwt(user_id: str) -> str:
    """
    Generate a test JWT for a given user_id.

    In development mode, services accept HS256-signed tokens with a shared secret.
    This mirrors the claims structure that Cognito would produce in production.
    """
    user = USERS.get(user_id)
    if not user:
        raise ValueError(f"Unknown test user: {user_id}")

    now = datetime.now(timezone.utc)
    payload = {
        "sub": user["id"],
        "email": user["email"],
        "custom:tenant_id": user["tenant_id"],
        "custom:role": user["role"],
        "cognito:groups": [user["role"]],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool",
        "aud": "test-client-id",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def service_urls() -> dict[str, str]:
    """All service base URLs from docker-compose port mappings."""
    return SERVICE_URLS


@pytest.fixture(scope="session")
def s2s_headers() -> dict[str, str]:
    """Service-to-service authentication headers."""
    return {
        "X-Service-Id": S2S_SERVICE_ID,
        "X-Service-Key": S2S_SERVICE_KEY,
        "Content-Type": "application/json",
    }


@pytest.fixture(scope="session")
def jwt_token_for():
    """Factory fixture: generate test JWT for a user_id."""
    return generate_test_jwt


@pytest.fixture(scope="session")
def seed_data():
    """
    Run testdata/setup.py once per test session to seed data.

    This fixture is session-scoped so seeding happens only once.
    """
    setup_script = TESTDATA_DIR / "setup.py"
    result = subprocess.run(
        [sys.executable, str(setup_script)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f"Seed script stdout:\n{result.stdout}")
        print(f"Seed script stderr:\n{result.stderr}")
        pytest.skip(f"Seed script failed with exit code {result.returncode}")
    return result.stdout


@pytest_asyncio.fixture(scope="session")
async def gateway_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client for llm-gateway."""
    async with httpx.AsyncClient(
        base_url=SERVICE_URLS["llm_gateway"],
        timeout=30.0,
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def gateway_admin_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client for llm-gateway admin API."""
    async with httpx.AsyncClient(
        base_url=SERVICE_URLS["llm_gateway_admin"],
        timeout=10.0,
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def memory_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client for memory-service."""
    async with httpx.AsyncClient(
        base_url=SERVICE_URLS["memory_service"],
        timeout=10.0,
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def eval_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client for agent-eval."""
    async with httpx.AsyncClient(
        base_url=SERVICE_URLS["agent_eval"],
        timeout=30.0,
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def assistant_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client for compliance-assistant."""
    async with httpx.AsyncClient(
        base_url=SERVICE_URLS["compliance_assistant"],
        timeout=30.0,
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def sandbox_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client for sandbox-service."""
    async with httpx.AsyncClient(
        base_url=SERVICE_URLS["sandbox_service"],
        timeout=10.0,
    ) as client:
        yield client


def auth_headers(user_id: str) -> dict[str, str]:
    """Generate Authorization headers for a test user."""
    token = generate_test_jwt(user_id)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
