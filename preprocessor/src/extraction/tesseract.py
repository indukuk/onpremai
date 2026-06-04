"""Tesseract OCR extraction backend.

Uses pytesseract (Python wrapper for Tesseract-OCR) for on-premises
OCR processing. Requires the tesseract binary to be installed on the system.
"""

from __future__ import annotations

import io
import shutil
from typing import Any

import structlog

from src.extraction.base import ExtractionBackend, ExtractionResult

logger = structlog.get_logger(__name__)


class TesseractBackend(ExtractionBackend):
    """Tesseract-based OCR text extraction.

    Works entirely on-premises without cloud API calls.
    Requires tesseract binary and pytesseract Python package.
    """

    def __init__(self, language: str = "eng") -> None:
        """Initialize Tesseract backend.

        Args:
            language: Tesseract language code (default: English).
        """
        self._language = language

    async def extract_text(self, file_bytes: bytes, **kwargs: object) -> ExtractionResult:
        """Extract text from image bytes using Tesseract OCR.

        Args:
            file_bytes: Raw image bytes (PNG, JPEG, TIFF) or PDF bytes.
            **kwargs: Additional options:
                - language (str): Override language for this extraction.
                - psm (int): Page segmentation mode.

        Returns:
            ExtractionResult with OCR'd text.
        """
        try:
            import pytesseract
            from PIL import Image

            language = str(kwargs.get("language", self._language))

            # Try to open as image first
            try:
                image = Image.open(io.BytesIO(file_bytes))
            except Exception:
                # If it fails, it might be a PDF - try pdf2image or return failure
                return await self._extract_from_pdf_bytes(file_bytes, language)

            # Configure Tesseract options
            config = ""
            psm = kwargs.get("psm")
            if psm is not None:
                config = f"--psm {psm}"

            # Run OCR
            text: str = pytesseract.image_to_string(
                image, lang=language, config=config
            )

            # Get confidence data
            data: dict[str, Any] = pytesseract.image_to_data(
                image, lang=language, output_type=pytesseract.Output.DICT
            )
            confidences = [
                int(c) for c in data.get("conf", []) if int(c) > 0
            ]
            avg_confidence = (
                sum(confidences) / len(confidences) / 100.0
                if confidences
                else 0.0
            )

            logger.info(
                "tesseract_extraction_complete",
                text_length=len(text),
                confidence=round(avg_confidence, 3),
            )

            return ExtractionResult(
                text=text.strip(),
                page_count=1,
                confidence=avg_confidence,
                metadata={"backend": "tesseract", "language": language},
            )

        except ImportError as exc:
            return ExtractionResult.failure(f"Required package not installed: {exc}")
        except Exception as exc:
            logger.error(
                "tesseract_extraction_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return ExtractionResult.failure(f"Tesseract extraction failed: {exc}")

    async def _extract_from_pdf_bytes(
        self, file_bytes: bytes, language: str
    ) -> ExtractionResult:
        """Attempt OCR on PDF by converting pages to images.

        Falls back when the input bytes are a scanned PDF rather than an image.
        """
        try:
            import pytesseract
            from PIL import Image

            # Try using pdf2image if available
            try:
                from pdf2image import convert_from_bytes

                images = convert_from_bytes(file_bytes, dpi=300)
            except ImportError:
                return ExtractionResult.failure(
                    "Cannot OCR PDF: pdf2image not installed and input is not an image"
                )

            pages_text: list[str] = []
            all_confidences: list[float] = []

            for page_image in images:
                text: str = pytesseract.image_to_string(page_image, lang=language)
                pages_text.append(text.strip())

                data: dict[str, Any] = pytesseract.image_to_data(
                    page_image, lang=language, output_type=pytesseract.Output.DICT
                )
                confidences = [int(c) for c in data.get("conf", []) if int(c) > 0]
                if confidences:
                    all_confidences.extend(
                        c / 100.0 for c in confidences
                    )

            full_text = "\n\n".join(pages_text)
            avg_confidence = (
                sum(all_confidences) / len(all_confidences)
                if all_confidences
                else 0.0
            )

            return ExtractionResult(
                text=full_text,
                page_count=len(images),
                confidence=avg_confidence,
                metadata={"backend": "tesseract", "language": language, "pages": len(images)},
            )

        except Exception as exc:
            return ExtractionResult.failure(f"Tesseract PDF OCR failed: {exc}")

    def is_available(self) -> bool:
        """Check if Tesseract binary is installed and accessible."""
        return shutil.which("tesseract") is not None

    @property
    def name(self) -> str:
        """Backend name."""
        return "tesseract"

    @property
    def supports_ocr(self) -> bool:
        """Tesseract supports OCR."""
        return True
