# Service: Preprocessor (preprocessor)

## Purpose

File ingestion and processing service. Takes raw uploads (Excel, CSV, PDF, Word, images) and converts them into structured metadata that evaluation agents can consume. Runs independently — triggered by file upload events.

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

### R2: OCR/Text Extraction Agnostic

- MUST NOT depend on AWS Textract directly
- Extraction backends (configurable):
  - **Tesseract** (on-prem, free): for images and scanned PDFs
  - **PyMuPDF/pdfplumber** (on-prem, free): for digital PDFs
  - **Apache Tika** (on-prem, free): for Word/PowerPoint/email
  - **AWS Textract** (cloud): when available and configured
  - **Azure Document Intelligence** (cloud): alternative
- Backend selected via config, not hardcoded
- Fallback chain: try primary backend, fall back to secondary on failure

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
# Environment variables
STORAGE_ENDPOINT: http://minio:9000
STORAGE_BUCKET: compliance-artifacts
STORAGE_ACCESS_KEY: ${STORAGE_ACCESS_KEY}
STORAGE_SECRET_KEY: ${STORAGE_SECRET_KEY}
MEMORY_URL: http://memory-service:5000
LLM_GATEWAY_URL: http://llm-gateway:4000    # optional
TRIGGER_MODE: poll
POLL_INTERVAL_SEC: 30
WATCH_PREFIX: uploads/
OCR_BACKEND: tesseract       # tesseract | textract | azure_di
PDF_BACKEND: pdfplumber      # pdfplumber | pymupdf | tika
MAX_FILE_SIZE_MB: 100
LOG_LEVEL: info
PORT: 7000
```
