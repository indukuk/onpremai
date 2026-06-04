#!/usr/bin/env python3
"""
Seed test data into the running compliance AI platform.

Requires:
  - docker compose up -d (all services running)
  - MinIO reachable at localhost:9000
  - memory-service reachable at localhost:5000

Uploads evidence files, inserts tenants/users, loads testing criteria, and creates sessions.
"""

import json
import os
import sys
import time
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin_dev")
MEMORY_SERVICE_URL = os.environ.get("MEMORY_SERVICE_URL", "http://localhost:5000")
EVIDENCE_BUCKET = "evidence"

# Service-to-service auth headers for seeding
S2S_HEADERS = {
    "X-Service-Id": "test-harness",
    "X-Service-Key": "test-harness-key-dev",
    "Content-Type": "application/json",
}


# ---------------------------------------------------------------------------
# MinIO helpers (using S3-compatible REST API via minio SDK)
# ---------------------------------------------------------------------------


def seed_minio():
    """Upload all evidence files to MinIO bucket."""
    try:
        from minio import Minio
        from minio.error import S3Error
    except ImportError:
        print("ERROR: minio package required. Install with: pip install minio")
        sys.exit(1)

    endpoint = MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
    client = Minio(
        endpoint,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )

    # Create bucket if not exists
    if not client.bucket_exists(EVIDENCE_BUCKET):
        client.make_bucket(EVIDENCE_BUCKET)
        print(f"  Created bucket: {EVIDENCE_BUCKET}")

    # Upload all evidence files
    evidence_dir = BASE_DIR / "evidence"
    uploaded = 0
    for tenant_dir in evidence_dir.iterdir():
        if not tenant_dir.is_dir():
            continue
        tenant_name = tenant_dir.name  # e.g., "acme-corp"
        for control_dir in tenant_dir.iterdir():
            if not control_dir.is_dir():
                continue
            control_id = control_dir.name  # e.g., "CC8.1"
            for file_path in control_dir.iterdir():
                if file_path.is_file():
                    object_name = f"{tenant_name}/{control_id}/{file_path.name}"
                    client.fput_object(
                        EVIDENCE_BUCKET,
                        object_name,
                        str(file_path),
                    )
                    uploaded += 1

    print(f"  Uploaded {uploaded} evidence files to MinIO bucket '{EVIDENCE_BUCKET}'")
    return uploaded


# ---------------------------------------------------------------------------
# Memory Service helpers
# ---------------------------------------------------------------------------


def seed_tenants():
    """Insert tenants into memory-service."""
    tenants_file = BASE_DIR / "tenants.json"
    with open(tenants_file) as f:
        data = json.load(f)

    count = 0
    for tenant in data["tenants"]:
        resp = httpx.post(
            f"{MEMORY_SERVICE_URL}/api/v1/tenants",
            headers=S2S_HEADERS,
            json=tenant,
            timeout=10.0,
        )
        if resp.status_code in (200, 201, 409):  # 409 = already exists
            count += 1
        else:
            print(f"  WARNING: Failed to seed tenant {tenant['id']}: {resp.status_code} {resp.text}")

    print(f"  Seeded {count} tenants into memory-service")
    return count


def seed_users():
    """Insert users into memory-service."""
    users_file = BASE_DIR / "users.json"
    with open(users_file) as f:
        data = json.load(f)

    count = 0
    for user in data["users"]:
        resp = httpx.post(
            f"{MEMORY_SERVICE_URL}/api/v1/users",
            headers=S2S_HEADERS,
            json=user,
            timeout=10.0,
        )
        if resp.status_code in (200, 201, 409):
            count += 1
        else:
            print(f"  WARNING: Failed to seed user {user['id']}: {resp.status_code} {resp.text}")

    print(f"  Seeded {count} users into memory-service")
    return count


def seed_criteria():
    """Load testing criteria (SOC2 framework controls) into memory-service."""
    frameworks_dir = BASE_DIR / "frameworks"
    count = 0
    for framework_dir in frameworks_dir.iterdir():
        if not framework_dir.is_dir():
            continue
        framework_name = framework_dir.name.upper()  # e.g., "SOC2"
        for criteria_file in framework_dir.iterdir():
            if criteria_file.suffix == ".json" and criteria_file.is_file():
                with open(criteria_file) as f:
                    criteria_data = json.load(f)

                resp = httpx.post(
                    f"{MEMORY_SERVICE_URL}/api/v1/criteria",
                    headers=S2S_HEADERS,
                    json={
                        "framework": framework_name,
                        "criteria": criteria_data if isinstance(criteria_data, list) else [criteria_data],
                    },
                    timeout=10.0,
                )
                if resp.status_code in (200, 201, 409):
                    count += 1
                else:
                    print(
                        f"  WARNING: Failed to seed criteria {criteria_file.name}: "
                        f"{resp.status_code} {resp.text}"
                    )

    print(f"  Seeded {count} criteria files into memory-service")
    return count


def seed_sessions():
    """Create sample sessions for test users."""
    sessions = [
        {
            "user_id": "user-001",
            "tenant_id": "tenant-acme-corp",
            "session_id": "session-e2e-admin",
            "metadata": {"role": "admin", "test": True},
        },
        {
            "user_id": "user-003",
            "tenant_id": "tenant-acme-corp",
            "session_id": "session-e2e-contributor",
            "metadata": {"role": "contributor", "test": True},
        },
        {
            "user_id": "user-008",
            "tenant_id": "tenant-initech",
            "session_id": "session-e2e-initech-admin",
            "metadata": {"role": "admin", "test": True},
        },
    ]

    count = 0
    for session in sessions:
        resp = httpx.post(
            f"{MEMORY_SERVICE_URL}/api/v1/sessions",
            headers=S2S_HEADERS,
            json=session,
            timeout=10.0,
        )
        if resp.status_code in (200, 201, 409):
            count += 1
        else:
            print(
                f"  WARNING: Failed to create session {session['session_id']}: "
                f"{resp.status_code} {resp.text}"
            )

    print(f"  Created {count} test sessions")
    return count


def seed_budget_state():
    """Seed budget state so tenant-initech is marked as exhausted."""
    budget_data = {
        "tenant_id": "tenant-initech",
        "monthly_limit_usd": 5.0,
        "used_usd": 5.0,
        "status": "exhausted",
    }
    resp = httpx.post(
        f"{MEMORY_SERVICE_URL}/api/v1/budget",
        headers=S2S_HEADERS,
        json=budget_data,
        timeout=10.0,
    )
    if resp.status_code in (200, 201, 409):
        print("  Set budget state: tenant-initech marked as exhausted")
    else:
        print(f"  WARNING: Failed to set budget state: {resp.status_code} {resp.text}")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


def wait_for_services(max_wait: int = 60):
    """Wait until critical services respond to health checks."""
    services = {
        "memory-service": f"{MEMORY_SERVICE_URL}/health",
        "minio": f"{MINIO_ENDPOINT}/minio/health/live",
    }

    start = time.time()
    for name, url in services.items():
        while time.time() - start < max_wait:
            try:
                resp = httpx.get(url, timeout=3.0)
                if resp.status_code == 200:
                    break
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            print(f"  Waiting for {name}...")
            time.sleep(2)
        else:
            print(f"ERROR: {name} not available after {max_wait}s")
            sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=" * 60)
    print("E2E Test Data Seeder")
    print("=" * 60)

    print("\n[1/6] Waiting for services...")
    wait_for_services()

    print("\n[2/6] Seeding MinIO evidence files...")
    seed_minio()

    print("\n[3/6] Seeding tenants...")
    seed_tenants()

    print("\n[4/6] Seeding users...")
    seed_users()

    print("\n[5/6] Seeding criteria/frameworks...")
    seed_criteria()

    print("\n[6/6] Creating sessions and budget state...")
    seed_sessions()
    seed_budget_state()

    print("\n" + "=" * 60)
    print("SEED COMPLETE")
    print("=" * 60)
    print("\nSeeded data summary:")
    print("  - 3 tenants (acme-corp, globex-inc, initech)")
    print("  - 10 users across tenants")
    print("  - Evidence files for CC8.1, CC6.1, CC3.1, CC7.2")
    print("  - SOC2 + ISO27001 criteria")
    print("  - 3 test sessions")
    print("  - Budget exhausted state for tenant-initech")
    print("\nReady for E2E tests.")


if __name__ == "__main__":
    main()
