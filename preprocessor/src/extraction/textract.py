"""AWS Textract extraction backend.

Uses AWS Textract for OCR and document analysis. Requires valid AWS
credentials (IAM role or access keys) and network access to the Textract API.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

from src.extraction.base import ExtractionBackend, ExtractionResult

logger = structlog.get_logger(__name__)


class TextractBackend(ExtractionBackend):
    """AWS Textract-based text extraction.

    Supports OCR for scanned documents and images. Uses the DetectDocumentText
    API for simple text extraction and AnalyzeDocument for structured analysis.
    """

    def __init__(self) -> None:
        """Initialize Textract client (lazy - created on first use)."""
        self._client: Any | None = None
        self._region = os.environ.get("AWS_REGION", "us-east-1")

    def _get_client(self) -> Any:
        """Lazily create the boto3 Textract client."""
        if self._client is None:
            import boto3

            self._client = boto3.client("textract", region_name=self._region)
        return self._client

    async def extract_text(self, file_bytes: bytes, **kwargs: object) -> ExtractionResult:
        """Extract text from document bytes using Textract.

        Args:
            file_bytes: Raw document bytes (PDF, image).
            **kwargs: Additional options (unused for Textract).

        Returns:
            ExtractionResult with extracted text.
        """
        try:
            client = self._get_client()

            # Use synchronous API (Textract sync is simpler for single documents)
            response = client.detect_document_text(
                Document={"Bytes": file_bytes}
            )

            # Collect all LINE blocks into text
            lines: list[str] = []
            for block in response.get("Blocks", []):
                if block.get("BlockType") == "LINE":
                    text = block.get("Text", "")
                    if text:
                        lines.append(text)

            extracted_text = "\n".join(lines)
            confidence_scores = [
                block.get("Confidence", 100.0)
                for block in response.get("Blocks", [])
                if block.get("BlockType") == "LINE"
            ]
            avg_confidence = (
                sum(confidence_scores) / len(confidence_scores) / 100.0
                if confidence_scores
                else 1.0
            )

            logger.info(
                "textract_extraction_complete",
                lines=len(lines),
                confidence=round(avg_confidence, 3),
            )

            return ExtractionResult(
                text=extracted_text,
                page_count=1,  # Sync API processes single page
                confidence=avg_confidence,
                metadata={"backend": "textract", "block_count": len(response.get("Blocks", []))},
            )

        except ImportError:
            return ExtractionResult.failure("boto3 not installed - Textract unavailable")
        except Exception as exc:
            logger.error(
                "textract_extraction_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return ExtractionResult.failure(f"Textract extraction failed: {exc}")

    def is_available(self) -> bool:
        """Check if Textract is available (boto3 installed + credentials exist)."""
        try:
            import boto3  # noqa: F401

            # Check for AWS credentials
            has_keys = bool(
                os.environ.get("AWS_ACCESS_KEY_ID")
                or os.environ.get("AWS_ROLE_ARN")
                or os.path.exists(os.path.expanduser("~/.aws/credentials"))
            )
            return has_keys
        except ImportError:
            return False

    @property
    def name(self) -> str:
        """Backend name."""
        return "textract"

    @property
    def supports_ocr(self) -> bool:
        """Textract supports OCR."""
        return True
