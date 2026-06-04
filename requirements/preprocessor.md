# Service: Preprocessor (preprocessor)

## Purpose

File ingestion and processing service. Takes raw uploads (Excel, CSV, PDF, Word, images) and converts them into structured metadata that evaluation agents can consume. Runs independently — triggered by file upload events.

## System Requirements Covered

| System Requirement | This module's role | Requirement ID |
|---|---|---|
| LLM Agnostic | Uses task="extract_schema" (optional, fast tier) | R5 |
| Storage Agnostic | All file I/O via StorageClient (S3/MinIO) | R1 |
| AWS-First w/ Adapters | Textract primary for OCR, Tesseract fallback for on-prem | R2 |
| Graceful Degradation | Deterministic processing continues without LLM or Textract | R2, R5 |
| PII-Aware Logging | All logs via AgentLogger, PII-free operational output | R8 |
| Observability | Logs processing events, file types, errors | R8 |
| Memory is Shared | Writes evidence-available facts to memory service | R4 |
| Deterministic First | File parsing is deterministic (no LLM for most operations) | R3 |
| Independent Deploy | Own image, PREPROC_VERSION tag | R8 |

## Current State (what exists in /Users/indukuk/compliance)

- Lambda with S3 trigger
- Processes: Excel→CSV sheets, PDF→text (Textract), schema detection, join analysis
- Outputs: `metadata.json` per file with schema, sample rows, extracted text
- Hardcoded to AWS S3 + Textract

## Requirements for On-Prem/Hybrid

### R1: Storage Agnostic

- MUST use `common.storage_client.StorageClient` for all file read/write
- Watch for new files via:
  - Polling (check for new files every N seconds) — simplest, works everywhere
  - MinIO bucket notifications (webhook to preprocessor)
  - S3 event notifications (Lambda trigger in cloud mode)
- Input: raw file from storage
- Output: `metadata.json` written alongside the original file

### R2: OCR/Text Extraction — Adapter Pattern

- MUST NOT hardcode any single extraction provider in business logic
- Extraction backends (configurable via adapter pattern):
  - **AWS Textract** (cloud, default): primary for images and scanned PDFs — highest accuracy
  - **PyMuPDF/pdfplumber** (built-in, free): for digital PDFs — always available, no cloud cost
  - **Tesseract** (on-prem, free): for images/scanned PDFs in air-gapped deployments
  - **Apache Tika** (on-prem, free): for Word/PowerPoint/email
  - **Azure Document Intelligence** (cloud): alternative for Azure deployments
- Backend selected via `OCR_BACKEND` env var, not hardcoded
- Fallback chain: try primary backend, fall back to secondary on failure
- **AWS-first default**: Textract for OCR, pdfplumber for digital PDFs (no OCR needed)
- **Credit exhaustion**: if Textract returns throttling/quota errors, fall back to Tesseract automatically

### R3: Processing Pipeline

For each uploaded file:

1. **Detect file type** (by extension + magic bytes)
2. **Extract content**:
   - Excel/CSV → parse sheets, detect columns, sample rows, row counts
   - PDF → extract text (digital or OCR), page count
   - Word/PowerPoint → extract text
   - Images → OCR text extraction
   - JSON → parse and summarize schema
3. **Generate schema** (structured files):
   - Column names, types, row count
   - Sample rows (first 5)
   - Detected date columns, ID columns, numeric columns
4. **Detect joins** (when multiple structured files exist for same control):
   - Find common columns between files
   - Suggest join keys
5. **Write metadata.json**:
   ```json
   {
     "filename": "access_review_2024.xlsx",
     "file_type": "excel",
     "size_bytes": 245000,
     "processed_at": "2026-05-10T14:32:01Z",
     "evidence_type": "structured",
     "sheets": [
       {
         "name": "Sheet1",
         "columns": ["user_id", "reviewer", "review_date", "outcome"],
         "row_count": 1523,
         "sample_rows": [{...}, {...}, {...}, {...}, {...}],
         "column_types": {"user_id": "string", "review_date": "date", ...}
       }
     ],
     "join_candidates": [
       {"other_file": "user_list.csv", "join_column": "user_id", "confidence": 0.95}
     ]
   }
   ```

### R4: Memory Integration

- After processing: notify memory service that new evidence is available
- `memory.tenant_remember(tenant_id, "New file uploaded: {filename}, type: {type}", category="evidence")`
- Preprocessor does NOT evaluate — it only prepares data for the evaluation agent

### R5: LLM Usage (minimal)

- Preprocessor MAY use LLM for:
  - Schema understanding (ambiguous column types)
  - File relevance detection (is this file compliance evidence?)
- Task type: `extract_schema` (fast tier)
- Most processing is deterministic (no LLM needed for Excel parsing)
- LLM calls are optional — preprocessor works without LLM gateway

### R6: Trigger Modes

```yaml
trigger_mode: poll          # poll | webhook | event

# Poll mode (simplest, works everywhere)
poll:
  interval_sec: 30
  watch_prefix: "uploads/"  # only process files in this prefix
  marker_file: ".processed" # skip files that have this marker

# Webhook mode (MinIO notifications)
webhook:
  port: 7000
  path: /notify

# Event mode (cloud, S3 trigger)
event:
  # Configured externally (Lambda trigger or EventBridge)
```

### R7: Idempotency

- MUST be idempotent — processing the same file twice produces the same output
- Track processed files (by path + content hash)
- Skip already-processed files unless content hash changed
- If metadata.json already exists and file hash matches → skip

### R8: Container Packaging

- Single Docker image, independently versioned
- Version tag: `PREPROC_VERSION`
- Health check: `GET /health`
- Includes: Python libs for Excel (openpyxl), PDF (pdfplumber, PyMuPDF), OCR (tesseract)
- Tesseract binary included in image (for OCR without cloud)
- No GPU required
- Max file size: configurable (default 100MB)

### R9: Configuration

```yaml
# Environment variables (AWS-first defaults)
STORAGE_BACKEND: s3
STORAGE_BUCKET: compliance-artifacts
AWS_REGION: us-east-1
MEMORY_URL: http://memory-service:5000
LLM_GATEWAY_URL: http://llm-gateway:4000    # optional
TRIGGER_MODE: poll
POLL_INTERVAL_SEC: 30
WATCH_PREFIX: uploads/
OCR_BACKEND: textract        # textract | tesseract | azure_di
OCR_FALLBACK: tesseract      # fallback if primary fails or quota exceeded
PDF_BACKEND: pdfplumber      # pdfplumber | pymupdf | tika (for digital PDFs, no OCR)
MAX_FILE_SIZE_MB: 100
LOG_LEVEL: info
PORT: 7000

# Local development overrides:
# STORAGE_BACKEND: minio
# STORAGE_ENDPOINT: http://minio:9000
# STORAGE_ACCESS_KEY: minioadmin
# STORAGE_SECRET_KEY: minioadmin
# OCR_BACKEND: tesseract
```
