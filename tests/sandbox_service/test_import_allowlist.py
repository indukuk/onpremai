"""Tests for sandbox-service import allowlist (static AST analysis).

Covers:
- Allowed imports pass validation
- Blocked modules (os, subprocess, socket, shutil) are caught
- from...import variants
- Nested/dotted module imports (e.g., os.path)
- eval/exec/compile/__import__ calls are blocked
- Blocked attribute calls (os.system, shutil.rmtree)
- importlib blocked
- SyntaxError handling
- Edge cases: empty code, comments-only, multi-import
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox-service"))

from src.security.import_allowlist import (
    BLOCKED_ATTRIBUTES,
    BLOCKED_MODULES,
    check_code_safety,
)


class TestAllowedImportsPass:
    """Allowed imports should produce no violations."""

    def test_pandas_import(self):
        code = "import pandas as pd"
        assert check_code_safety(code) == []

    def test_numpy_import(self):
        code = "import numpy as np"
        assert check_code_safety(code) == []

    def test_json_import(self):
        code = "import json"
        assert check_code_safety(code) == []

    def test_re_import(self):
        code = "import re"
        assert check_code_safety(code) == []

    def test_datetime_import(self):
        code = "from datetime import datetime, timedelta"
        assert check_code_safety(code) == []

    def test_collections_import(self):
        code = "from collections import Counter, defaultdict"
        assert check_code_safety(code) == []

    def test_hashlib_import(self):
        code = "import hashlib"
        assert check_code_safety(code) == []

    def test_pathlib_import(self):
        code = "from pathlib import Path"
        assert check_code_safety(code) == []

    def test_math_import(self):
        code = "import math"
        assert check_code_safety(code) == []

    def test_multiple_allowed_imports(self):
        code = "import pandas\nimport numpy\nimport json\nimport re"
        assert check_code_safety(code) == []

    def test_empty_code(self):
        code = ""
        assert check_code_safety(code) == []

    def test_comments_only(self):
        code = "# This is a comment\n# Another comment"
        assert check_code_safety(code) == []

    def test_pure_computation(self):
        code = "x = 1 + 2\ny = x * 3\nprint(y)"
        assert check_code_safety(code) == []


class TestBlockedModulesDetected:
    """Blocked modules should produce violations."""

    def test_import_os(self):
        code = "import os"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "os" in violations[0]

    def test_import_subprocess(self):
        code = "import subprocess"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "subprocess" in violations[0]

    def test_import_socket(self):
        code = "import socket"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "socket" in violations[0]

    def test_import_shutil(self):
        code = "import shutil"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "shutil" in violations[0]

    def test_import_pickle(self):
        code = "import pickle"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "pickle" in violations[0]

    def test_import_ctypes(self):
        code = "import ctypes"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "ctypes" in violations[0]

    def test_import_importlib(self):
        code = "import importlib"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "importlib" in violations[0]

    def test_import_sys(self):
        code = "import sys"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "sys" in violations[0]

    def test_import_multiprocessing(self):
        code = "import multiprocessing"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "multiprocessing" in violations[0]

    def test_import_http(self):
        code = "import http"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "http" in violations[0]


class TestFromImportBlocked:
    """from...import variants should also be caught."""

    def test_from_os_import_path(self):
        code = "from os import path"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "os" in violations[0]

    def test_from_subprocess_import_run(self):
        code = "from subprocess import run, check_output"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "subprocess" in violations[0]

    def test_from_socket_import_socket(self):
        code = "from socket import socket, AF_INET"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "socket" in violations[0]

    def test_from_shutil_import_rmtree(self):
        code = "from shutil import rmtree"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "shutil" in violations[0]

    def test_from_importlib_import_import_module(self):
        code = "from importlib import import_module"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "importlib" in violations[0]


class TestDottedModuleImports:
    """Dotted/nested imports (os.path, http.client) should be blocked by top-level module."""

    def test_import_os_path(self):
        code = "import os.path"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "os" in violations[0]

    def test_import_http_client(self):
        code = "import http.client"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "http" in violations[0]

    def test_import_urllib_request(self):
        code = "import urllib.request"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "urllib" in violations[0]

    def test_from_os_path_import_join(self):
        code = "from os.path import join, exists"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "os" in violations[0]


class TestDynamicCodeExecution:
    """eval, exec, compile, __import__ calls should be blocked."""

    def test_eval_call(self):
        code = "result = eval('1 + 1')"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "eval" in violations[0]

    def test_exec_call(self):
        code = "exec('import os')"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "exec" in violations[0]

    def test_compile_call(self):
        code = "code = compile('x=1', '<string>', 'exec')"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "compile" in violations[0]

    def test_dunder_import_call(self):
        code = "__import__('os')"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "__import__" in violations[0]


class TestBlockedAttributeCalls:
    """Blocked attribute access patterns (os.system, shutil.rmtree)."""

    def test_os_system(self):
        code = "os.system('rm -rf /')"
        violations = check_code_safety(code)
        assert any("os.system" in v for v in violations)

    def test_os_popen(self):
        code = "os.popen('ls')"
        violations = check_code_safety(code)
        assert any("os.popen" in v for v in violations)

    def test_shutil_rmtree(self):
        code = "shutil.rmtree('/tmp')"
        violations = check_code_safety(code)
        assert any("shutil.rmtree" in v for v in violations)


class TestMultipleViolations:
    """Code with multiple violations should report all of them."""

    def test_multiple_blocked_imports(self):
        code = "import os\nimport subprocess\nimport socket"
        violations = check_code_safety(code)
        assert len(violations) == 3

    def test_mixed_allowed_and_blocked(self):
        code = "import pandas\nimport os\nimport numpy\nimport socket"
        violations = check_code_safety(code)
        assert len(violations) == 2
        blocked_modules_in_violations = [v for v in violations if "os" in v or "socket" in v]
        assert len(blocked_modules_in_violations) == 2

    def test_import_plus_eval(self):
        code = "import subprocess\nresult = eval('x')"
        violations = check_code_safety(code)
        assert len(violations) == 2


class TestSyntaxErrors:
    """Malformed code should return syntax error violation."""

    def test_syntax_error(self):
        code = "def foo(:"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "SyntaxError" in violations[0]

    def test_incomplete_expression(self):
        code = "x = (1 + "
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "SyntaxError" in violations[0]


class TestEdgeCases:
    """Edge cases for import detection."""

    def test_string_containing_import(self):
        """A string literal that mentions 'import os' should NOT be flagged."""
        code = "x = 'import os'\nprint(x)"
        violations = check_code_safety(code)
        assert violations == []

    def test_comment_with_import(self):
        """A comment mentioning a blocked import should NOT be flagged."""
        code = "# import os\nprint('hello')"
        violations = check_code_safety(code)
        assert violations == []

    def test_variable_named_import(self):
        """A variable named after a blocked module should NOT be flagged."""
        code = "os = 'operating system'\nprint(os)"
        violations = check_code_safety(code)
        assert violations == []

    def test_function_named_eval_in_method(self):
        """A function call on an object named eval should NOT be flagged.
        Only bare eval() calls are caught by ast.Name check."""
        code = "obj.eval('test')"
        violations = check_code_safety(code)
        # Only ast.Name-based eval is blocked; obj.eval is ast.Attribute
        assert violations == []

    def test_nested_function_def_with_import(self):
        """Import inside a function body is still detected."""
        code = "def foo():\n    import os\n    return os.getcwd()"
        violations = check_code_safety(code)
        assert any("os" in v for v in violations)

    def test_try_except_with_import(self):
        """Import inside try/except is still detected."""
        code = "try:\n    import subprocess\nexcept ImportError:\n    pass"
        violations = check_code_safety(code)
        assert len(violations) == 1
        assert "subprocess" in violations[0]

    def test_all_blocked_modules_in_frozenset(self):
        """Verify the blocklist contains expected critical modules."""
        critical = {"os", "subprocess", "socket", "shutil", "importlib", "ctypes", "pickle"}
        assert critical.issubset(BLOCKED_MODULES)
