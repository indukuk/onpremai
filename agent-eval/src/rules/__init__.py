"""Deterministic rule engine for Layer 1 evaluation.

Each rule module implements a single check type that produces
PASS, FAIL, or NEEDS_JUDGMENT without any LLM call.
"""

from __future__ import annotations
