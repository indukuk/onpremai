"""Trigger layer for detecting new files to process.

Supports multiple trigger modes:
- poll: Periodically scan storage prefix for new/changed files.
- webhook: Receive HTTP notifications from MinIO/S3 bucket events.
"""

from __future__ import annotations
