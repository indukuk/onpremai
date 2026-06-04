"""Static analysis of user code for blocked imports using AST parsing.

Before any container is created, user code is parsed and checked against
the module blocklist. If any blocked module is found, execution is refused
immediately without resource expenditure.

Two layers of enforcement:
1. This module (pre-execution, static AST analysis)
2. Runtime import hook in the preamble (defense in depth)
"""

from __future__ import annotations

import ast
from typing import Final

# Modules that are explicitly blocked from import.
# These modules provide shell access, network access, database access,
# deserialization, native code execution, or dynamic module loading.
BLOCKED_MODULES: Final[frozenset[str]] = frozenset({
    # Shell / process execution
    "os",
    "subprocess",
    "shutil",
    "pty",
    "pipes",
    "multiprocessing",
    "threading",
    "signal",
    # Network
    "socket",
    "http",
    "urllib",
    "requests",
    "httpx",
    "ftplib",
    "smtplib",
    "telnetlib",
    "xmlrpc",
    "webbrowser",
    # Databases
    "sqlite3",
    "psycopg2",
    "pymongo",
    "mysql",
    # Deserialization
    "pickle",
    "shelve",
    "marshal",
    # Native code / FFI
    "ctypes",
    "cffi",
    # Dynamic imports
    "importlib",
    # System internals
    "sys",
    "code",
    "codeop",
    "compile",
    "compileall",
    "py_compile",
    "inspect",
    # Misc dangerous
    "antigravity",
    "turtle",
})

# Specific attribute accesses that are blocked even if the module is allowed.
BLOCKED_ATTRIBUTES: Final[frozenset[tuple[str, str]]] = frozenset({
    ("os", "system"),
    ("os", "popen"),
    ("os", "exec"),
    ("os", "execv"),
    ("os", "execve"),
    ("os", "spawn"),
    ("os", "spawnl"),
    ("os", "fork"),
    ("os", "kill"),
    ("os", "unlink"),
    ("os", "remove"),
    ("os", "rmdir"),
    ("shutil", "rmtree"),
    ("shutil", "move"),
})


def check_code_safety(code: str) -> list[str]:
    """Perform AST-based static analysis to detect blocked imports.

    Parses the user code into an AST and walks all nodes looking for:
    - import statements referencing blocked modules
    - from...import statements referencing blocked modules
    - eval/exec calls (potential dynamic code execution)

    Args:
        code: Python source code submitted by the agent.

    Returns:
        List of violation descriptions. Empty list means code passes validation.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"SyntaxError: {e.msg} (line {e.lineno})"]

    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_module = alias.name.split(".")[0]
                if top_module in BLOCKED_MODULES:
                    violations.append(
                        f"Blocked import: '{alias.name}' "
                        f"(module '{top_module}' is not available in sandbox)"
                    )

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top_module = node.module.split(".")[0]
                if top_module in BLOCKED_MODULES:
                    violations.append(
                        f"Blocked import: 'from {node.module} import ...' "
                        f"(module '{top_module}' is not available in sandbox)"
                    )

        elif isinstance(node, ast.Call):
            # Check for eval() and exec() calls
            if isinstance(node.func, ast.Name):
                if node.func.id in ("eval", "exec", "compile", "__import__"):
                    violations.append(
                        f"Blocked call: '{node.func.id}()' is not allowed in sandbox"
                    )
            # Check for attribute calls like os.system()
            elif isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    pair = (node.func.value.id, node.func.attr)
                    if pair in BLOCKED_ATTRIBUTES:
                        violations.append(
                            f"Blocked call: '{node.func.value.id}.{node.func.attr}()' "
                            f"is not allowed in sandbox"
                        )

    return violations
