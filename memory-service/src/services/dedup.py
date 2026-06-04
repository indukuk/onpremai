from __future__ import annotations

from src.config import settings


class DedupService:
    """
    Semantic deduplication logic.
    A fact with >threshold similarity to an existing fact is considered a duplicate.
    """

    def __init__(self, threshold: float | None = None) -> None:
        self._threshold = threshold if threshold is not None else settings.DEDUP_SIMILARITY_THRESHOLD

    @property
    def threshold(self) -> float:
        return self._threshold

    def is_duplicate(self, similarity: float) -> bool:
        """Returns True if similarity exceeds the dedup threshold."""
        return similarity >= self._threshold

    def merge_confidence(self, existing: float, incoming: float) -> float:
        """Merge confidence: take the higher value."""
        return max(existing, incoming)
