# Service: Sandbox Service (sandbox-service)

## Purpose

Isolated code execution service. Any agent submits Python code + data references, gets stdout/stderr back. Runs untrusted LLM-generated code safely in ephemeral containers with no network access, no persistence, and strict resource limits.

## System Requirements Covered

| System Requirement | This module's role | Requirement ID |
|---|---|---|
| Storage Agnostic | Downloads evidence files from S3/MinIO via StorageClient | R3 |
| AWS-First w/ Adapters | S3 for file downloads, same adapter as other services | R10 |
| Graceful Degradation | Returns success=false on failure (never crashes caller) | R1 |
| PII-Aware Logging | All logs via AgentLogger, execution logs PII-free | R8 |
| Observability | Logs each execution with duration, memory, timeout, OOM stats | R8 |
| Security Isolation | Ephemeral containers, no network, no secrets, allowlisted imports only | R2, R6 |
| Independent Deploy | Own image (service + runtime), SANDBOX_VERSION tag | R9 |

## Why a Separate Service

- **Security isolation**: LLM-generated code is untrusted. Running it inside an agent container means a malicious/buggy script can access agent memory, env vars, secrets, or network. Separate container = blast radius is zero.
- **Reusability**: agent-eval uses it for compliance data analysis. compliance-assistant could use it for ad-hoc queries. Future agents get it for free.
- **Resource control**: sandbox can be given specific CPU/memory limits independent of agent sizing.
- **Scaling**: sandbox executions are CPU-bound and bursty. Can scale independently (multiple replicas).

## Requirements

### R1: API

```
POST /execute
{
  "code": "import pandas as pd\n...\nprint(json.dumps(result))",
  "files": [
    {"storage_key": "acme/soc2/cc8.1/processed/access_logs.csv", "load_as": "df1", "type": "csv"},
    {"storage_key": "acme/soc2/cc8.1/processed/approvals.xlsx", "load_as": "df2", "type": "excel"}
  ],
  "timeout_sec": 60,
  "memory_limit_mb": 512
}
```

Response (success):
```json
{
  "success": true,
  "stdout": "{\"total\": 1523, \"violations\": 12, \"rate\": 0.008}",
  "stderr": "",
  "duration_ms": 3420,
  "memory_used_mb": 187
}
```

Response (error):
```json
{
  "success": false,
  "stdout": "Population: 1523\nMatched: 1200\n",
  "stderr": "Traceback (most recent call last):\n  File ...\nKeyError: 'approval_date'",
  "duration_ms": 1200,
  "memory_used_mb": 95
}
```

Response (timeout):
```json
{
  "success": false,
  "stdout": "",
  "stderr": "Execution timed out after 60 seconds",
  "duration_ms": 60000,
  "memory_used_mb": 512
}
```

### R2: Execution Isolation

- Each execution runs in an **ephemeral container** from the pre-built runtime image
- Runtime image has ALL libraries pre-installed — no pip install, no download at execution time
- First `import pandas` takes <100ms (already on disk in the image layer)
- Execution environment:
  - Python 3.11+ with full library stack (see R13)
  - NO network access (`--network=none`)
  - NO access to host filesystem (only `/tmp/data` with loaded evidence files)
  - NO environment variables from host (clean env)
  - NO access to other containers or services
  - Process killed after timeout (SIGKILL, no grace period)
  - Temp filesystem wiped after execution (ephemeral, `--rm`)

### R3: Data Loading

- Sandbox service receives `files` array with storage keys
- Before executing user code, sandbox service:
  1. Downloads files from storage (via `StorageClient`) into a temp directory
  2. Generates a data-loading preamble:
     ```python
     import pandas as pd
     import json
     import warnings
     warnings.filterwarnings('ignore')
     
     df1 = pd.read_csv('/tmp/data/access_logs.csv')
     df2 = pd.read_excel('/tmp/data/approvals.xlsx')
     ```
  3. Prepends preamble to user code
  4. Executes combined code in isolated environment
- File download happens in the **service process** (which HAS storage access), NOT in the sandbox
- Only the loaded temp files are mounted into the sandbox execution environment

### R4: Resource Limits

- Per-execution limits (configurable per request, with hard maximums):
  | Resource | Default | Maximum |
  |----------|---------|---------|
  | Timeout | 60s | 300s |
  | Memory | 512MB | 2GB |
  | CPU | 1 core | 2 cores |
  | Output size (stdout) | 1MB | 5MB |
  | File count | 10 | 20 |
  | Total file size | 100MB | 500MB |

- Hard maximums enforced by service — agent cannot request more
- Execution killed immediately on limit breach (no warning)

### R5: Concurrency

- Supports multiple concurrent executions
- Configurable max concurrent: `MAX_CONCURRENT_EXECUTIONS` (default 5)
- Queue additional requests (return 429 if queue full)
- Each execution is fully isolated from others (separate process/container)
- No shared state between executions

### R6: Security

- **No network**: execution environment has zero network access
- **No secrets**: no env vars, no credentials, no tokens in execution environment
- **No escape**: chroot/container boundary prevents filesystem access outside temp
- **No persistence**: everything wiped after execution completes
- **No imports**: only allowlisted modules available (no `os.system`, no `subprocess`, no `socket`, no `requests`)
  - Allowlist: `pandas, numpy, json, re, datetime, collections, math, statistics, csv, io, hashlib, itertools, functools, operator`
  - If code tries to import blocked module → ImportError
- **Read-only code**: execution cannot modify the loaded data files (copy-on-write or read-only mount)
- **Resource jail**: ulimit/cgroup enforcement on memory, CPU, file descriptors

### R7: Execution Backends

Configurable — pick one based on deployment:

**Backend A: Docker-in-Docker (recommended for production)**
- Sandbox service has access to Docker socket (or uses Docker SDK)
- Each execution: `docker run --rm --network=none --memory=512m --cpus=1 --read-only sandbox-runtime:latest python /tmp/code.py`
- Runtime image (`sandbox-runtime`) is pre-built with pandas/numpy
- Fastest cold start: image already pulled, just creates container
- Strongest isolation

**Backend B: subprocess + nsjail/firejail (lighter, no Docker dependency)**
- Uses nsjail or firejail for namespace isolation
- Runs as subprocess with cgroups for resource limits
- No Docker socket needed
- Good for edge/small deployments

**Backend C: subprocess + ulimit (simplest, weakest isolation)**
- Plain subprocess with ulimit for resource limits
- Minimal isolation (same filesystem namespace, just restricted)
- For development/testing only
- NOT recommended for production

### R8: Health & Observability

- `GET /health` — service alive
- `GET /ready` — can accept executions (storage reachable, backend functional)
- `GET /metrics` — execution stats:
  ```json
  {
    "total_executions": 1847,
    "success_rate": 0.82,
    "avg_duration_ms": 3200,
    "active_executions": 2,
    "queued": 0,
    "timeouts_last_hour": 3,
    "oom_kills_last_hour": 1
  }
  ```
- Each execution logged:
  ```json
  {
    "timestamp": "...",
    "trace_id": "...",
    "agent": "agent-eval",
    "duration_ms": 3420,
    "success": true,
    "memory_used_mb": 187,
    "file_count": 2,
    "total_file_size_mb": 12,
    "timeout": false,
    "oom_killed": false
  }
  ```

### R9: Container Packaging

- **Two images**:
  1. `yourorg/compliance-sandbox-service` — the API service (FastAPI, handles requests, downloads files, manages execution)
  2. `yourorg/compliance-sandbox-runtime` — the execution environment (Python + pandas + numpy, nothing else)
- Service image: independently versioned (`SANDBOX_VERSION`)
- Runtime image: rarely changes (only when adding new Python packages)
- Service needs access to: storage (to download files), Docker socket (if using Docker backend)
- Runtime needs access to: nothing (completely isolated)

### R10: Configuration

```yaml
# Environment variables (AWS-first defaults)
STORAGE_BACKEND: s3
STORAGE_BUCKET: compliance-artifacts
AWS_REGION: us-east-1
EXECUTION_BACKEND: docker          # docker | nsjail | subprocess
DOCKER_SOCKET: /var/run/docker.sock
RUNTIME_IMAGE: yourorg/compliance-sandbox-runtime:latest
MAX_CONCURRENT_EXECUTIONS: 5
DEFAULT_TIMEOUT_SEC: 60
MAX_TIMEOUT_SEC: 300
DEFAULT_MEMORY_MB: 512
MAX_MEMORY_MB: 2048
MAX_OUTPUT_SIZE_MB: 1
MAX_FILE_COUNT: 10
MAX_TOTAL_FILE_SIZE_MB: 100
QUEUE_SIZE: 20                     # max queued requests before 429
LOG_LEVEL: info
PORT: 9000

# Local development overrides:
# STORAGE_BACKEND: minio
# STORAGE_ENDPOINT: http://minio:9000
# STORAGE_ACCESS_KEY: minioadmin
# STORAGE_SECRET_KEY: minioadmin
```

### R11: Docker Compose Integration

```yaml
services:
  sandbox-service:
    image: yourorg/compliance-sandbox-service:${SANDBOX_VERSION:-1.0.0}
    environment:
      - STORAGE_ENDPOINT=http://minio:9000
      - EXECUTION_BACKEND=docker
      - DOCKER_SOCKET=/var/run/docker.sock
      - RUNTIME_IMAGE=yourorg/compliance-sandbox-runtime:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock  # for Docker backend
      - sandbox-tmp:/tmp/sandbox                    # temp file staging
    ports: ["9000:9000"]
    depends_on: [minio]
    deploy:
      resources:
        limits:
          memory: 1G    # service itself (not execution memory)
          cpus: "2.0"

  # The runtime image doesn't run as a service — it's pulled and used
  # by sandbox-service to create ephemeral execution containers
```

### R12: Interaction Flow

```
Agent (agent-eval)                    Sandbox Service                  Storage
      │                                     │                            │
      │  POST /execute                      │                            │
      │  {code, files: [{key, load_as}]}    │                            │
      │────────────────────────────────────>│                            │
      │                                     │                            │
      │                                     │  GET files by storage_key  │
      │                                     │───────────────────────────>│
      │                                     │<───────────────────────────│
      │                                     │  (downloads to /tmp/)      │
      │                                     │                            │
      │                                     │  Create isolated container │
      │                                     │  Mount /tmp/data (read-only)
      │                                     │  Execute: preamble + code  │
      │                                     │  Wait for completion/timeout
      │                                     │  Capture stdout/stderr     │
      │                                     │  Destroy container         │
      │                                     │  Clean up temp files       │
      │                                     │                            │
      │  {success, stdout, stderr,          │                            │
      │   duration_ms, memory_used}         │                            │
      │<────────────────────────────────────│                            │
      │                                     │                            │
```

### R13: Runtime Image Contents

The runtime image is **pre-built with all libraries installed**. No pip install at execution time — everything is warm and ready. This is critical for sub-second startup.

```dockerfile
# Dockerfile.runtime
FROM python:3.11-slim

# --- Data manipulation & analysis ---
RUN pip install --no-cache-dir \
    pandas==2.2.* \
    numpy==1.26.* \
    polars==1.* \
    dask[dataframe]==2024.*

# --- File format support ---
RUN pip install --no-cache-dir \
    openpyxl==3.1.* \
    xlrd==2.0.* \
    xlsxwriter==3.2.* \
    python-docx==1.1.* \
    pdfplumber==0.11.* \
    PyPDF2==3.* \
    odfpy==1.4.* \
    pyarrow==15.* \
    fastparquet==2024.* \
    python-pptx==0.6.*

# --- Date/time handling ---
RUN pip install --no-cache-dir \
    python-dateutil==2.9.* \
    pytz==2024.*

# --- Text processing & pattern matching ---
RUN pip install --no-cache-dir \
    regex==2024.* \
    fuzzywuzzy==0.18.* \
    python-Levenshtein==0.25.* \
    chardet==5.* \
    ftfy==6.*

# --- Data validation & schemas ---
RUN pip install --no-cache-dir \
    jsonschema==4.* \
    pydantic==2.* \
    cerberus==1.3.*

# --- Statistics & math ---
RUN pip install --no-cache-dir \
    scipy==1.13.* \
    scikit-learn==1.5.*

# --- Visualization (output as files, not display) ---
RUN pip install --no-cache-dir \
    matplotlib==3.9.* \
    seaborn==0.13.*

# --- Crypto/hashing (for evidence fingerprinting) ---
# (hashlib is stdlib, but add these for advanced use)
RUN pip install --no-cache-dir \
    cryptography==42.*

# Strip unnecessary OS tools
RUN apt-get purge -y curl wget && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# No CMD — code is passed in at execution time
USER 65534
WORKDIR /tmp
```

#### Pre-imported in preamble (always available without import statement):

```python
import pandas as pd
import numpy as np
import json
import re
import hashlib
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')
```

#### Available for explicit import:

| Category | Libraries |
|----------|-----------|
| **DataFrames** | pandas, polars, dask |
| **Excel/Spreadsheets** | openpyxl, xlrd, xlsxwriter, odfpy |
| **CSV/Parquet** | csv (stdlib), pyarrow, fastparquet |
| **PDF** | pdfplumber, PyPDF2 |
| **Word/PowerPoint** | python-docx, python-pptx |
| **Dates** | datetime (stdlib), python-dateutil, pytz |
| **Text/Fuzzy matching** | re (stdlib), regex, fuzzywuzzy, chardet, ftfy |
| **Validation** | jsonschema, pydantic, cerberus |
| **Math/Stats** | math (stdlib), statistics (stdlib), numpy, scipy, scikit-learn |
| **Visualization** | matplotlib, seaborn |
| **Collections** | collections (stdlib), itertools (stdlib), functools (stdlib) |
| **Hashing** | hashlib (stdlib), cryptography |
| **IO** | io (stdlib), pathlib (stdlib), json (stdlib), csv (stdlib) |

#### BLOCKED (not installed, ImportError if attempted):

- `os.system`, `subprocess`, `shutil.rmtree` — shell access
- `socket`, `http`, `urllib`, `requests`, `httpx` — network
- `sqlite3`, `psycopg2`, `pymongo` — databases
- `pickle`, `shelve` — arbitrary deserialization
- `ctypes`, `cffi` — native code execution
- `importlib`, `__import__` for non-allowlisted modules

#### Why these specific libraries:

| Use case in compliance evaluation | Library needed |
|-----------------------------------|---------------|
| Read Excel evidence files | openpyxl, xlrd |
| Read CSV exports from GRC tools | pandas, csv |
| Parse PDF policies and procedures | pdfplumber, PyPDF2 |
| Read Word documents (policies) | python-docx |
| Cross-reference data between systems | pandas merge/join, fuzzywuzzy |
| Date range analysis (review periods) | python-dateutil |
| Statistical sampling for audit | scipy, scikit-learn |
| Detect encoding issues in exports | chardet, ftfy |
| Validate JSON evidence against schemas | jsonschema, pydantic |
| Calculate compliance metrics | numpy, statistics |
| Generate charts for reports | matplotlib, seaborn |
| Handle large datasets (>1M rows) | polars, dask |
| Read Parquet from data warehouses | pyarrow |
| Hash evidence for integrity checks | hashlib, cryptography |

### R14: Cold Pool (Simplicity First)

Architecture is async (agent-eval polls for results), so 300-500ms container startup overhead is irrelevant — the user is already waiting 30-45s for a full evaluation cycle.

- No warm pool needed. Fresh container per execution.
- `docker run --rm` on every request — simplest, cleanest, no state management.
- Container startup cost (~500ms) is noise within a 30-45s evaluation.
- Benefits:
  - No pool management code
  - No idle resource consumption
  - No stale container issues
  - Every execution is guaranteed clean
- If latency ever matters (future sync use case): add warm pool as an optimization later.

### R15: Future Extensibility

- **Other languages**: runtime image could include Node.js or R for future agent types
- **GPU access**: for ML-based analysis, runtime could mount GPU (optional flag in request)
- **Artifact output**: sandbox could write result files (charts, CSVs) to a temp location, service returns download URLs
- **Streaming**: for long-running code, stream stdout in real-time (WebSocket or SSE)
- These are NOT required now — just noting they don't conflict with the design
