"""Code fixer node for sandbox execution errors.

When sandbox execution fails, this node sends the error back to the LLM
with context to generate a corrected version of the code. Retries up to
MAX_SANDBOX_RETRIES times before giving up.
"""

from __future__ import annotations

from typing import Any

import structlog

from common.clients import LLMClient, SandboxClient

from src.config import get_settings
from src.graph.state import EvalGraphState

logger = structlog.get_logger(__name__)

FIX_CODE_PROMPT = """The following Python code failed during execution in a sandbox.

## Original Code
```python
{code}
```

## Error
```
{error}
```

## Instructions
Fix the code to resolve the error. Common issues:
- Missing imports (add import statements)
- File not found (check filename spelling)
- Type errors (ensure proper type conversion)
- Index errors (add bounds checking)

Return ONLY the corrected Python code, no markdown fences or explanation."""


async def code_fixer_node(state: EvalGraphState) -> dict[str, Any]:
    """Fix failed sandbox code and retry execution.

    Takes the failed code and error message, asks LLM to fix it,
    then re-executes in sandbox. Increments retry counter.
    """
    settings = get_settings()
    sandbox_code = state.get("sandbox_code", "")
    sandbox_output = state.get("sandbox_output", "")
    sandbox_retries = state.get("sandbox_retries", 0)
    tenant_id = state.get("tenant_id", "")
    trace_id = state.get("trace_id", "")
    evidence_metadata = state.get("evidence_metadata", [])

    # Check retry limit
    if sandbox_retries >= settings.max_sandbox_retries:
        logger.warning(
            "sandbox_max_retries",
            retries=sandbox_retries,
            trace_id=trace_id,
        )
        return {
            "sandbox_output": f"Max retries ({settings.max_sandbox_retries}) exceeded. Last error: {sandbox_output[:500]}",
            "sandbox_retries": sandbox_retries,
        }

    llm = LLMClient()
    sandbox = SandboxClient()

    try:
        # Ask LLM to fix the code
        prompt = FIX_CODE_PROMPT.format(
            code=sandbox_code,
            error=sandbox_output[:2000],
        )

        response = await llm.complete(
            messages=[{"role": "user", "content": prompt}],
            task="fix_code",
            tenant_id=tenant_id,
            trace_id=trace_id,
            temperature=0.0,
            max_tokens=2000,
        )

        fixed_code = _extract_code(response.content)

        # Prepare files for sandbox
        files: dict[str, str] = {}
        for meta in evidence_metadata:
            if meta.file_type in ("spreadsheet", "csv", "json"):
                filename = meta.storage_key.rsplit("/", 1)[-1] if "/" in meta.storage_key else meta.storage_key
                files[filename] = meta.storage_key

        # Re-execute fixed code
        result = await sandbox.execute(
            code=fixed_code,
            files=files,
            timeout_sec=60,
            trace_id=trace_id,
        )

        new_retries = sandbox_retries + 1

        if result.success:
            logger.info(
                "code_fix_success",
                retry=new_retries,
                trace_id=trace_id,
            )
            return {
                "sandbox_code": fixed_code,
                "sandbox_output": result.stdout,
                "sandbox_retries": new_retries,
            }
        else:
            logger.warning(
                "code_fix_still_failing",
                retry=new_retries,
                stderr=result.stderr[:300],
                trace_id=trace_id,
            )
            return {
                "sandbox_code": fixed_code,
                "sandbox_output": result.stderr,
                "sandbox_retries": new_retries,
            }

    finally:
        await llm.close()
        await sandbox.close()


def _extract_code(content: str) -> str:
    """Extract Python code from LLM response, handling markdown fences."""
    content = content.strip()

    if content.startswith("```python"):
        content = content[len("```python"):].strip()
    elif content.startswith("```"):
        content = content[3:].strip()

    if content.endswith("```"):
        content = content[:-3].strip()

    return content
