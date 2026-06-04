"""Abstract base class for all extraction backends.

Defines the interface that Textract, Tesseract, pdfplumber, and Tika
adapters must implement. Allows runtime backend selection via config.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ExtractionResult:
    """Result from a text extraction operation.

    Attributes:
        text: Extracted text content.
        page_count: Number of pages (for multi-page documents).
        confidence: Extraction confidence score (0.0 - 1.0), if available.
        metadata: Additional backend-specific metadata.
        success: Whether extraction completed without error.
        error_message: Error description if extraction failed.
    """

    text: str = ""
    page_count: int = 0
    confidence: float = 1.0
    metadata: dict[str, object] = field(default_factory=dict)
    success: bool = True
    error_message: str = ""

    @classmethod
    def failure(cls, message: str) -> "ExtractionResult":
        """Create a failed extraction result."""
        return cls(success=False, error_message=message)


class ExtractionBackend(ABC):
    """Abstract base class for text extraction backends.

    All extraction backends (Tesseract, Textract, pdfplumber, etc.)
    implement this interface. The processing pipeline selects the
    appropriate backend based on configuration and file type.
    """

    @abstractmethod
    async def extract_text(self, file_bytes: bytes, **kwargs: object) -> ExtractionResult:
        """Extract text content from file bytes.

        Args:
            file_bytes: Raw bytes of the file to process.
            **kwargs: Backend-specific options (e.g., language, page range).

        Returns:
            ExtractionResult with extracted text and metadata.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend is available and properly configured.

        Returns:
            True if the backend can process files right now.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this extraction backend."""
        ...

    @property
    def supports_ocr(self) -> bool:
        """Whether this backend can handle scanned/image documents."""
        return False

    @property
    def supports_digital_pdf(self) -> bool:
        """Whether this backend handles digital (text-layer) PDFs."""
        return False
