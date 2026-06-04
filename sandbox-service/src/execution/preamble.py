"""Generate Python preamble code that loads evidence files into DataFrames.

The preamble is prepended to user code before execution inside the container.
It provides standard imports and variables pre-loaded with evidence data.
"""

from __future__ import annotations

from src.models import FileReference, FileType

# Standard imports always included in preamble
_STANDARD_IMPORTS = """\
import builtins as _builtins
_original_import = _builtins.__import__
_BLOCKED_MODULES = frozenset({
    'os', 'subprocess', 'shutil', 'socket', 'http', 'urllib',
    'requests', 'httpx', 'sqlite3', 'psycopg2', 'pymongo',
    'pickle', 'shelve', 'ctypes', 'cffi', 'importlib',
    'multiprocessing', 'threading', 'signal', 'pty', 'pipes',
    'webbrowser', 'antigravity', 'turtle',
})

def _safe_import(name, *args, **kwargs):
    top_level = name.split('.')[0]
    if top_level in _BLOCKED_MODULES:
        raise ImportError(f"Module '{name}' is not available in sandbox")
    return _original_import(name, *args, **kwargs)

_builtins.__import__ = _safe_import
del _original_import

import pandas as pd
import numpy as np
import json
import re
import hashlib
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')
"""

# Map file type to the pandas reader expression
_READER_MAP: dict[FileType, str] = {
    FileType.csv: "pd.read_csv('{path}')",
    FileType.excel: "pd.read_excel('{path}')",
    FileType.parquet: "pd.read_parquet('{path}')",
    FileType.json: "pd.read_json('{path}')",
}


def generate_preamble(files: list[FileReference]) -> str:
    """Generate the full preamble including imports and file loading statements.

    Args:
        files: List of file references describing what to load and how.

    Returns:
        Complete preamble Python code as a string.
    """
    lines: list[str] = [_STANDARD_IMPORTS]

    for file_ref in files:
        # Filename derived from storage_key (last path component)
        filename = file_ref.storage_key.rsplit("/", 1)[-1]
        data_path = f"/tmp/data/{filename}"

        if file_ref.type == FileType.pdf:
            # PDFs are not loaded as DataFrames; just assign the path
            lines.append(f"{file_ref.load_as} = '{data_path}'")
        else:
            reader_template = _READER_MAP[file_ref.type]
            reader_call = reader_template.replace("{path}", data_path)
            lines.append(f"{file_ref.load_as} = {reader_call}")

    lines.append("")  # trailing newline separator before user code
    return "\n".join(lines)
