# Preprocessor Service - Design Document

## Overview

The preprocessor is a file ingestion service that converts raw uploads (Excel, CSV, PDF, Word, images) into structured metadata consumable by evaluation agents. It runs independently, triggered by file upload events, and does not perform any evaluation or require GPU resources.

**Core principle:** Prepare data, never evaluate it.

---

## High-Level Architecture

```mermaid
graph TB
    subgraph "Trigger Layer"
        POLL[Poll Mode<br/>Check every 30s]
        WEBHOOK[Webhook Mode<br/>MinIO notifications]
        EVENT[Event Mode<br/>S3/Lambda trigger]
    end

    subgraph "Preprocessor Service"
        TRIGGER[Trigger Handler]
        IDEM[Idempotency Check]
        DETECT[File Type Detector]
        ROUTE[File Router]
        EXTRACT[Content Extractor]
        SCHEMA[Schema Generator]
        JOINS[Join Detector]
        META[Metadata Writer]
    end

    subgraph "External Services"
        STORAGE[(Storage<br/>MinIO / S3)]
        MEMORY[Memory Service]
        LLM[LLM Gateway<br/>optional]
    end

    POLL --> TRIGGER
    WEBHOOK --> TRIGGER
    EVENT --> TRIGGER

    TRIGGER --> IDEM
    IDEM -->|new/changed| DETECT
    IDEM -->|unchanged| SKIP[Skip]
    DETECT --> ROUTE
    ROUTE --> EXTRACT
    EXTRACT --> SCHEMA
    SCHEMA --> JOINS
    JOINS --> META

    META --> STORAGE
    META --> MEMORY
    EXTRACT -.->|optional| LLM
    TRIGGER --> STORAGE
```

---

## Processing Pipeline

```mermaid
flowchart LR
    A[New File Detected] --> B{Idempotency<br/>Check}
    B -->|Hash matches<br/>existing| Z[Skip - Already Processed]
    B -->|New or changed| C[Detect File Type]
    C --> D[Route to Processor]
    D --> E[Extract Content]
    E --> F[Generate Schema]
    F --> G{Multiple structured<br/>files for control?}
    G -->|Yes| H[Detect Joins]
    G -->|No| I[Write metadata.json]
    H --> I
    I --> J[Notify Memory Service]
    J --> K[Mark as Processed]
```

---

## File Type Routing

```mermaid
flowchart TD
    FILE[Incoming File] --> DETECT{Detect Type<br/>extension + magic bytes}

    DETECT -->|.xlsx .xls| EXCEL[Excel Processor<br/>openpyxl]
    DETECT -->|.csv .tsv| CSV[CSV Processor<br/>pandas/csv]
    DETECT -->|.pdf| PDF_CHECK{Digital or<br/>Scanned?}
    DETECT -->|.docx .doc .pptx| WORD[Document Processor<br/>Apache Tika / python-docx]
    DETECT -->|.png .jpg .tiff| IMAGE[Image Processor<br/>OCR Backend]
    DETECT -->|.json| JSON_PROC[JSON Processor<br/>Schema inference]
    DETECT -->|unknown| UNSUPPORTED[Log Warning<br/>Skip file]

    PDF_CHECK -->|Digital text| PDF_DIG[PDF Text Extractor<br/>pdfplumber / PyMuPDF]
    PDF_CHECK -->|Scanned/image| PDF_OCR[PDF OCR Extractor<br/>OCR Backend]

    EXCEL --> OUTPUT[metadata.json]
    CSV --> OUTPUT
    PDF_DIG --> OUTPUT
    PDF_OCR --> OUTPUT
    WORD --> OUTPUT
    IMAGE --> OUTPUT
    JSON_PROC --> OUTPUT

    subgraph "OCR Backend (configurable)"
        OCR_T[Tesseract<br/>on-prem, free]
        OCR_TX[AWS Textract<br/>cloud]
        OCR_AZ[Azure Document Intelligence<br/>cloud]
    end

    IMAGE -.-> OCR_T
    IMAGE -.-> OCR_TX
    IMAGE -.-> OCR_AZ
    PDF_OCR -.-> OCR_T
    PDF_OCR -.-> OCR_TX
    PDF_OCR -.-> OCR_AZ
```

---

## Trigger Modes Comparison

```mermaid
flowchart LR
    subgraph "Poll Mode"
        direction TB
        P1[Timer: every 30s] --> P2[List files in watch prefix]
        P2 --> P3[Compare with processed set]
        P3 --> P4[Process new/changed files]
    end

    subgraph "Webhook Mode"
        direction TB
        W1[MinIO sends POST /notify] --> W2[Parse bucket notification]
        W2 --> W3[Extract file key]
        W3 --> W4[Process file immediately]
    end

    subgraph "Event Mode"
        direction TB
        E1[S3 Event / Lambda trigger] --> E2[Receive event payload]
        E2 --> E3[Extract file key]
        E3 --> E4[Process file immediately]
    end

    style P1 fill:#e1f5fe
    style W1 fill:#e8f5e9
    style E1 fill:#fff3e0
```

| Mode | Latency | Complexity | Best For |
|------|---------|------------|----------|
| Poll | Up to 30s delay | Lowest | On-prem, simple deployments |
| Webhook | Near real-time | Medium | MinIO with notifications enabled |
| Event | Real-time | Highest | AWS with Lambda/EventBridge |

---

## Idempotency Check Flow

```mermaid
flowchart TD
    A[File detected for processing] --> B[Compute content hash<br/>SHA-256 of file bytes]
    B --> C{metadata.json exists<br/>for this file?}
    C -->|No| D[Process file]
    C -->|Yes| E[Read existing metadata.json]
    E --> F{content_hash in metadata<br/>matches current hash?}
    F -->|Yes| G[SKIP - File unchanged<br/>Log: already processed]
    F -->|No| H[File content changed<br/>Re-process]
    H --> D
    D --> I[Write metadata.json<br/>including content_hash]
    I --> J[Record in processed tracker<br/>path + hash + timestamp]
```

**Idempotency guarantees:**
- Same file content always produces identical `metadata.json` output
- Content hash (SHA-256) is the source of truth for change detection
- Processed tracker prevents redundant work across restarts
- No side effects on skip (no memory notification, no re-write)

---

## Module Structure

```mermaid
graph TD
    subgraph "src/"
        MAIN[main.py<br/>Entry point, trigger setup]
        CONFIG[config.py<br/>Environment-based configuration]

        subgraph "triggers/"
            T_POLL[poll.py<br/>Polling loop]
            T_WEBHOOK[webhook.py<br/>HTTP endpoint]
            T_EVENT[event.py<br/>Lambda/event handler]
        end

        subgraph "processors/"
            P_EXCEL[excel.py<br/>Excel/CSV processing]
            P_PDF[pdf.py<br/>PDF text extraction]
            P_DOC[document.py<br/>Word/PowerPoint]
            P_IMAGE[image.py<br/>Image OCR]
            P_JSON[json_proc.py<br/>JSON schema inference]
        end

        subgraph "extractors/"
            E_TESSERACT[tesseract.py<br/>On-prem OCR]
            E_TEXTRACT[textract.py<br/>AWS Textract]
            E_AZURE[azure_di.py<br/>Azure Document Intelligence]
            E_PDFPLUMBER[pdfplumber_ext.py<br/>Digital PDF text]
            E_PYMUPDF[pymupdf_ext.py<br/>PDF fallback]
            E_TIKA[tika_ext.py<br/>Apache Tika]
        end

        subgraph "core/"
            C_PIPELINE[pipeline.py<br/>Orchestrates processing steps]
            C_DETECT[file_detector.py<br/>Type detection]
            C_SCHEMA[schema.py<br/>Schema generation]
            C_JOINS[join_detector.py<br/>Cross-file join analysis]
            C_IDEM[idempotency.py<br/>Hash tracking, skip logic]
            C_META[metadata.py<br/>metadata.json builder]
        end

        HEALTH[health.py<br/>GET /health endpoint]
    end

    MAIN --> CONFIG
    MAIN --> T_POLL
    MAIN --> T_WEBHOOK
    MAIN --> T_EVENT
    T_POLL --> C_PIPELINE
    T_WEBHOOK --> C_PIPELINE
    T_EVENT --> C_PIPELINE
    C_PIPELINE --> C_IDEM
    C_PIPELINE --> C_DETECT
    C_PIPELINE --> P_EXCEL
    C_PIPELINE --> P_PDF
    C_PIPELINE --> P_DOC
    C_PIPELINE --> P_IMAGE
    C_PIPELINE --> P_JSON
    C_PIPELINE --> C_SCHEMA
    C_PIPELINE --> C_JOINS
    C_PIPELINE --> C_META
    P_PDF --> E_PDFPLUMBER
    P_PDF --> E_PYMUPDF
    P_PDF --> E_TESSERACT
    P_PDF --> E_TEXTRACT
    P_IMAGE --> E_TESSERACT
    P_IMAGE --> E_TEXTRACT
    P_IMAGE --> E_AZURE
    P_DOC --> E_TIKA
```

---

## Detailed Source Layout

```
preprocessor/
├── Dockerfile
├── requirements.txt
├── REQUIREMENTS.md
├── DESIGN.md
├── src/
│   ├── main.py                  # Entry point: parse config, select trigger, start
│   ├── config.py                # Pydantic settings from env vars
│   ├── health.py                # GET /health (Flask/FastAPI minimal)
│   ├── triggers/
│   │   ├── __init__.py
│   │   ├── poll.py              # Periodic scan of watch prefix
│   │   ├── webhook.py           # HTTP POST receiver (MinIO notifications)
│   │   └── event.py            # Lambda/EventBridge event handler
│   ├── core/
│   │   ├── __init__.py
│   │   ├── pipeline.py          # Main orchestration: detect → extract → schema → joins → write
│   │   ├── file_detector.py     # File type detection (extension + python-magic)
│   │   ├── schema.py            # Column type inference, sample rows, row counts
│   │   ├── join_detector.py     # Cross-file common column detection
│   │   ├── idempotency.py       # Content hash computation, processed file tracking
│   │   └── metadata.py          # Build and serialize metadata.json
│   ├── processors/
│   │   ├── __init__.py
│   │   ├── excel.py             # openpyxl for .xlsx, xlrd for .xls, csv module for .csv
│   │   ├── pdf.py               # Route to digital extractor or OCR based on content
│   │   ├── document.py          # python-docx, python-pptx, or Tika fallback
│   │   ├── image.py             # Route to configured OCR backend
│   │   └── json_proc.py         # Parse JSON, infer schema, summarize structure
│   └── extractors/
│       ├── __init__.py
│       ├── base.py              # Abstract base class for all extractors
│       ├── tesseract.py         # pytesseract wrapper (on-prem OCR)
│       ├── textract.py          # AWS Textract client (cloud OCR)
│       ├── azure_di.py          # Azure Document Intelligence client
│       ├── pdfplumber_ext.py    # pdfplumber for digital PDF text extraction
│       ├── pymupdf_ext.py       # PyMuPDF/fitz as fallback PDF extractor
│       └── tika_ext.py          # Apache Tika for Word/PowerPoint
├── tests/
│   ├── test_pipeline.py
│   ├── test_processors.py
│   ├── test_extractors.py
│   ├── test_idempotency.py
│   ├── test_join_detector.py
│   └── fixtures/                # Sample Excel, PDF, Word, image files
└── common/                      # Copied from /common at build time
    ├── storage_client.py
    ├── memory_client.py
    ├── llm_client.py
    └── logger.py
```

---

## Key Design Decisions

### 1. No GPU Required

All OCR processing uses CPU-based Tesseract. The Docker image includes the Tesseract binary and language data. This keeps the image portable to any machine without GPU drivers or CUDA setup.

### 2. Configurable Extraction Backends

Backends are selected via `OCR_BACKEND` and `PDF_BACKEND` environment variables. The extractor layer uses a strategy pattern with a common interface:

```python
class BaseExtractor(ABC):
    @abstractmethod
    def extract_text(self, file_bytes: bytes, **kwargs) -> str: ...

    @abstractmethod
    def is_available(self) -> bool: ...
```

Fallback chain: if the primary backend fails or is unavailable, the system tries the next configured backend before raising an error.

### 3. Idempotency by Content Hash

- SHA-256 of file bytes serves as the content fingerprint
- The hash is stored in `metadata.json` alongside the output
- On re-encounter, hash is compared before any processing begins
- This ensures correctness even across service restarts

### 4. Join Detection Strategy

When multiple structured files exist for the same control/tenant prefix:
1. Collect all column names from each file's schema
2. Find exact name matches across files
3. Score confidence based on: name match, type compatibility, value overlap (sampled)
4. Report join candidates with confidence score in metadata

### 5. Memory Notification (Not Evaluation)

After successful processing, the preprocessor notifies the memory service:
```python
memory.tenant_remember(
    tenant_id=tenant_id,
    fact=f"New file uploaded: {filename}, type: {file_type}",
    category="evidence",
    source="preprocessor"
)
```
This allows evaluation agents to discover new evidence without polling storage directly.

### 6. LLM Usage is Optional

The preprocessor works fully without an LLM gateway. LLM is only used for:
- Ambiguous column type detection (when heuristics fail)
- File relevance classification (is this compliance evidence?)

If `LLM_GATEWAY_URL` is not set, these steps are skipped gracefully.

---

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `STORAGE_ENDPOINT` | `http://minio:9000` | Storage service URL |
| `STORAGE_BUCKET` | `compliance-artifacts` | Primary bucket name |
| `MEMORY_URL` | `http://memory-service:5000` | Memory service URL |
| `LLM_GATEWAY_URL` | (none) | LLM gateway URL (optional) |
| `TRIGGER_MODE` | `poll` | `poll`, `webhook`, or `event` |
| `POLL_INTERVAL_SEC` | `30` | Seconds between poll cycles |
| `WATCH_PREFIX` | `uploads/` | Storage prefix to watch |
| `OCR_BACKEND` | `tesseract` | `tesseract`, `textract`, or `azure_di` |
| `PDF_BACKEND` | `pdfplumber` | `pdfplumber`, `pymupdf`, or `tika` |
| `MAX_FILE_SIZE_MB` | `100` | Maximum file size to process |
| `LOG_LEVEL` | `info` | Logging verbosity |
| `PORT` | `7000` | HTTP port for health check and webhook |

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| File exceeds `MAX_FILE_SIZE_MB` | Skip, log warning, write error metadata |
| OCR backend unavailable | Try fallback backend, then fail with error metadata |
| Storage unreachable | Retry 3x with backoff, then crash (trigger restart) |
| Memory service down | Log warning, continue (notification is best-effort) |
| LLM gateway down | Skip LLM-dependent steps, continue with heuristics |
| Corrupt file (cannot parse) | Write error metadata with reason, do not crash |
| Unsupported file type | Skip, log info |

---

## Health Check

`GET /health` on the configured `PORT` returns:

```json
{
  "status": "healthy",
  "trigger_mode": "poll",
  "ocr_backend": "tesseract",
  "pdf_backend": "pdfplumber",
  "files_processed": 142,
  "last_processed_at": "2026-05-10T14:32:01Z"
}
```

---

## Docker Image

```dockerfile
FROM python:3.11-slim

# Install Tesseract OCR
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ /app/common/
COPY src/ /app/src/

HEALTHCHECK --interval=30s --timeout=5s \
    CMD curl -f http://localhost:7000/health || exit 1

CMD ["python", "-m", "src.main"]
```

---

## Sequence: Full File Processing

```
1. Trigger detects new file "uploads/tenant-123/access_review.xlsx"
2. Idempotency check: compute SHA-256 of file bytes
3. Check if metadata.json exists with matching hash → does not exist
4. Detect type: extension=.xlsx, magic bytes confirm Excel
5. Route to Excel processor
6. Excel processor:
   a. Open with openpyxl
   b. For each sheet: read columns, types, row count, sample 5 rows
7. Schema generator: infer column types (string, date, numeric, ID)
8. Join detector: check other files in same prefix for common columns
9. Build metadata.json with all gathered information
10. Write metadata.json to storage alongside original file
11. Notify memory service: "New file uploaded: access_review.xlsx, type: excel"
12. Record file path + hash in processed tracker
13. Done
```
