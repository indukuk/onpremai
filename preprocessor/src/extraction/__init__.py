"""Extraction backends for OCR and text extraction.

Each backend implements the ExtractionBackend ABC and is selected
via the OCR_BACKEND or PDF_BACKEND environment variable.
"""

from __future__ import annotations

from src.extraction.base import ExtractionBackend, ExtractionResult

__all__ = ["ExtractionBackend", "ExtractionResult"]
