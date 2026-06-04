"""pdfplumber extraction backend for digital PDFs.

Extracts text from PDFs that have an embedded text layer (not scanned).
Uses pdfplumber which provides clean text extraction with layout awareness.
"""

from __future__ import annotations

import io

import structlog

from src.extraction.base import ExtractionBackend, ExtractionResult

logger = structlog.get_logger(__name__)


class PdfplumberBackend(ExtractionBackend):
    """pdfplumber-based PDF text extraction.

    Handles digital PDFs with embedded text layers. Does not perform OCR.
    Falls back gracefully when pages contain only images (returns empty text
    for those pages, signaling that OCR may be needed).
    """

    async def extract_text(self, file_bytes: bytes, **kwargs: object) -> ExtractionResult:
        """Extract text from a digital PDF.

        Args:
            file_bytes: Raw PDF file bytes.
            **kwargs: Additional options:
                - max_pages (int): Maximum pages to process (default: all).

        Returns:
            ExtractionResult with extracted text and page count.
        """
        try:
            import pdfplumber

            max_pages = int(kwargs.get("max_pages", 0)) or None
            pages_text: list[str] = []

            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                page_count = len(pdf.pages)
                pages_to_process = pdf.pages[:max_pages] if max_pages else pdf.pages

                for page in pages_to_process:
                    text = page.extract_text() or ""
                    pages_text.append(text)

            full_text = "\n\n".join(pages_text)
            non_empty_pages = sum(1 for t in pages_text if t.strip())

            logger.info(
                "pdfplumber_extraction_complete",
                page_count=page_count,
                non_empty_pages=non_empty_pages,
                text_length=len(full_text),
            )

            # If most pages are empty, text layer may be missing (scanned PDF)
            has_text = non_empty_pages > 0

            return ExtractionResult(
                text=full_text.strip(),
                page_count=page_count,
                confidence=1.0 if has_text else 0.0,
                metadata={
                    "backend": "pdfplumber",
                    "non_empty_pages": non_empty_pages,
                    "needs_ocr": not has_text,
                },
            )

        except ImportError:
            return ExtractionResult.failure("pdfplumber not installed")
        except Exception as exc:
            logger.error(
                "pdfplumber_extraction_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return ExtractionResult.failure(f"pdfplumber extraction failed: {exc}")

    def is_available(self) -> bool:
        """Check if pdfplumber is installed."""
        try:
            import pdfplumber  # noqa: F401

            return True
        except ImportError:
            return False

    @property
    def name(self) -> str:
        """Backend name."""
        return "pdfplumber"

    @property
    def supports_digital_pdf(self) -> bool:
        """pdfplumber handles digital PDFs."""
        return True
