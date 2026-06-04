"""Tests for sandbox-service preamble generation.

Covers:
- Standard imports are included
- Import hook is installed (_builtins.__import__ = _safe_import)
- _original_import is deleted from scope
- CSV file generates pd.read_csv
- Excel file generates pd.read_excel
- Parquet file generates pd.read_parquet
- JSON file generates pd.read_json
- PDF file assigns path string instead of DataFrame
- Multiple files produce multiple load statements
- Empty file list still produces valid preamble
- Generated code is syntactically valid Python
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-service"))

from src.execution.preamble import _READER_MAP, _STANDARD_IMPORTS, generate_preamble
from src.models import FileReference, FileType


class TestStandardImports:
    """The standard imports section of the preamble."""

    def test_contains_pandas_import(self):
        assert "import pandas as pd" in _STANDARD_IMPORTS

    def test_contains_numpy_import(self):
        assert "import numpy as np" in _STANDARD_IMPORTS

    def test_contains_json_import(self):
        assert "import json" in _STANDARD_IMPORTS

    def test_contains_re_import(self):
        assert "import re" in _STANDARD_IMPORTS

    def test_contains_hashlib_import(self):
        assert "import hashlib" in _STANDARD_IMPORTS

    def test_contains_datetime_import(self):
        assert "from datetime import datetime, timedelta" in _STANDARD_IMPORTS

    def test_contains_collections_import(self):
        assert "from collections import Counter, defaultdict" in _STANDARD_IMPORTS

    def test_contains_pathlib_import(self):
        assert "from pathlib import Path" in _STANDARD_IMPORTS

    def test_contains_warnings_filter(self):
        assert "warnings.filterwarnings('ignore')" in _STANDARD_IMPORTS


class TestImportHookInstalled:
    """The preamble installs a runtime import hook for defense in depth."""

    def test_import_hook_assigned(self):
        assert "_builtins.__import__ = _safe_import" in _STANDARD_IMPORTS

    def test_safe_import_function_defined(self):
        assert "def _safe_import(name, *args, **kwargs):" in _STANDARD_IMPORTS

    def test_blocked_modules_frozenset_defined(self):
        assert "_BLOCKED_MODULES = frozenset({" in _STANDARD_IMPORTS

    def test_original_import_saved(self):
        assert "_original_import = _builtins.__import__" in _STANDARD_IMPORTS

    def test_original_import_deleted(self):
        """_original_import should be deleted from scope after hook is installed."""
        assert "del _original_import" in _STANDARD_IMPORTS

    def test_safe_import_raises_import_error(self):
        """The _safe_import function raises ImportError for blocked modules."""
        assert "raise ImportError" in _STANDARD_IMPORTS

    def test_blocked_modules_include_os(self):
        assert "'os'" in _STANDARD_IMPORTS

    def test_blocked_modules_include_subprocess(self):
        assert "'subprocess'" in _STANDARD_IMPORTS

    def test_blocked_modules_include_socket(self):
        assert "'socket'" in _STANDARD_IMPORTS

    def test_blocked_modules_include_importlib(self):
        assert "'importlib'" in _STANDARD_IMPORTS


class TestDataLoading:
    """File loading statements generated based on file type."""

    def test_csv_generates_read_csv(self):
        files = [
            FileReference(
                storage_key="tenant/evidence/data.csv",
                load_as="df",
                type=FileType.csv,
            )
        ]
        preamble = generate_preamble(files)
        assert "df = pd.read_csv('/tmp/data/data.csv')" in preamble

    def test_excel_generates_read_excel(self):
        files = [
            FileReference(
                storage_key="tenant/evidence/report.xlsx",
                load_as="report",
                type=FileType.excel,
            )
        ]
        preamble = generate_preamble(files)
        assert "report = pd.read_excel('/tmp/data/report.xlsx')" in preamble

    def test_parquet_generates_read_parquet(self):
        files = [
            FileReference(
                storage_key="tenant/metrics/data.parquet",
                load_as="metrics",
                type=FileType.parquet,
            )
        ]
        preamble = generate_preamble(files)
        assert "metrics = pd.read_parquet('/tmp/data/data.parquet')" in preamble

    def test_json_generates_read_json(self):
        files = [
            FileReference(
                storage_key="tenant/config/schema.json",
                load_as="schema",
                type=FileType.json,
            )
        ]
        preamble = generate_preamble(files)
        assert "schema = pd.read_json('/tmp/data/schema.json')" in preamble

    def test_pdf_assigns_path_string(self):
        files = [
            FileReference(
                storage_key="tenant/evidence/policy.pdf",
                load_as="policy_path",
                type=FileType.pdf,
            )
        ]
        preamble = generate_preamble(files)
        assert "policy_path = '/tmp/data/policy.pdf'" in preamble

    def test_multiple_files(self):
        files = [
            FileReference(
                storage_key="tenant/evidence/users.csv",
                load_as="users",
                type=FileType.csv,
            ),
            FileReference(
                storage_key="tenant/evidence/logs.parquet",
                load_as="logs",
                type=FileType.parquet,
            ),
            FileReference(
                storage_key="tenant/evidence/doc.pdf",
                load_as="doc_path",
                type=FileType.pdf,
            ),
        ]
        preamble = generate_preamble(files)
        assert "users = pd.read_csv('/tmp/data/users.csv')" in preamble
        assert "logs = pd.read_parquet('/tmp/data/logs.parquet')" in preamble
        assert "doc_path = '/tmp/data/doc.pdf'" in preamble


class TestEmptyFileList:
    """Empty file list still produces valid preamble."""

    def test_empty_files_has_standard_imports(self):
        preamble = generate_preamble([])
        assert "import pandas as pd" in preamble
        assert "import numpy as np" in preamble

    def test_empty_files_no_load_statements(self):
        preamble = generate_preamble([])
        assert "pd.read_csv" not in preamble
        assert "pd.read_excel" not in preamble
        assert "pd.read_parquet" not in preamble
        assert "pd.read_json" not in preamble


class TestPreambleSyntaxValidity:
    """Generated preamble code must be syntactically valid Python."""

    def test_standard_imports_parse(self):
        """Standard imports section alone should parse without error."""
        ast.parse(_STANDARD_IMPORTS)

    def test_preamble_with_csv_parses(self):
        files = [
            FileReference(
                storage_key="tenant/data.csv",
                load_as="df",
                type=FileType.csv,
            )
        ]
        preamble = generate_preamble(files)
        ast.parse(preamble)

    def test_preamble_with_all_types_parses(self):
        files = [
            FileReference(storage_key="a/b.csv", load_as="csv_data", type=FileType.csv),
            FileReference(storage_key="a/b.xlsx", load_as="excel_data", type=FileType.excel),
            FileReference(storage_key="a/b.parquet", load_as="parquet_data", type=FileType.parquet),
            FileReference(storage_key="a/b.json", load_as="json_data", type=FileType.json),
            FileReference(storage_key="a/b.pdf", load_as="pdf_path", type=FileType.pdf),
        ]
        preamble = generate_preamble(files)
        ast.parse(preamble)

    def test_empty_preamble_parses(self):
        preamble = generate_preamble([])
        ast.parse(preamble)

    def test_preamble_plus_user_code_parses(self):
        """Full code (preamble + user code) should be valid Python."""
        files = [
            FileReference(
                storage_key="tenant/data.csv",
                load_as="df",
                type=FileType.csv,
            )
        ]
        preamble = generate_preamble(files)
        user_code = "print(df.shape)\nresult = df.describe()"
        full_code = preamble + user_code
        ast.parse(full_code)


class TestStorageKeyPathExtraction:
    """Filename is extracted from the last component of storage_key."""

    def test_nested_path_extracts_filename(self):
        files = [
            FileReference(
                storage_key="deep/nested/path/to/file.csv",
                load_as="df",
                type=FileType.csv,
            )
        ]
        preamble = generate_preamble(files)
        assert "/tmp/data/file.csv" in preamble

    def test_single_component_path(self):
        files = [
            FileReference(
                storage_key="simple.csv",
                load_as="df",
                type=FileType.csv,
            )
        ]
        preamble = generate_preamble(files)
        assert "/tmp/data/simple.csv" in preamble


class TestReaderMap:
    """Verify the reader map covers expected file types."""

    def test_csv_in_reader_map(self):
        assert FileType.csv in _READER_MAP

    def test_excel_in_reader_map(self):
        assert FileType.excel in _READER_MAP

    def test_parquet_in_reader_map(self):
        assert FileType.parquet in _READER_MAP

    def test_json_in_reader_map(self):
        assert FileType.json in _READER_MAP

    def test_pdf_not_in_reader_map(self):
        """PDFs are handled separately (path assignment, not DataFrame)."""
        assert FileType.pdf not in _READER_MAP
