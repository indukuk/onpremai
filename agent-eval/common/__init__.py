"""Symlink or copy of the shared common/ library.

In production, this is COPY'd from the root common/ package during Docker build.
For local development, ensure the root common/ is importable (e.g., via PYTHONPATH
or symlink).
"""

from __future__ import annotations
