"""Stub common package for preprocessor service.

At build time, the real common/ library is COPY'd into the Docker image.
This stub exists so the source tree can be navigated without the full common
package installed locally during development.
"""

from __future__ import annotations
