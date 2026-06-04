"""Code generation and sandbox execution node.

For criteria requiring structured data analysis (cross-references,
quantitative thresholds), this node:
1. Generates Python code via LLM
2. Sends it to the sandbox service for execution
3. Returns the analysis results

The sandbox service handles file loading, isolation, and execution.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from common.clients import LLMClient, SandboxClient

from src.config import get_settings
from src.graph.state import EvalGraphState
from src.models import EvidenceMetadata, TimingStats

logger = structlog.get_logger(__name__)

CODE_GENERATION_PROMPT = """Generate Python code to analyze the following data for a compliance check.

## Task
{task_description}

## Available Files
{file_descriptions}

## Requirements
- Use pandas for data analysis
- Print results as JSON to stdout using json.dumps()
- The output JSON should have: {{"result": "PASS"|"FAIL", "details": "...", "metrics": {{...}}}}
- Handle missing data gracefully
- Do NOT use any external network calls
- Files are available in the current working directory

## Code (Python only, no markdown):"""


async def sandbox_node(state: EvalGraphState) -> dict[str, Any]:
    """Generate analysis code and execute in sandbox.

    This node is invoked when structured data needs programmatic analysis
    that goes beyond simple rule checks (e.g., cross-referencing datasets,
    computing SLA metrics).
    """
    start_time = time.time()

    evidence_metadata: list[EvidenceMetadata] = state.get("evidence_metadata", [])
    tenant_id = state.get("tenant_id", "")
    trace_id = state.get("trace_id", "")
    testing_criteria = state.get("testing_criteria")

    settings = get_settings()
    llm = LLMClient()
    sandbox = SandboxClient()

    try:
        # Determine what analysis is needed
        task_description = _build_task_description(state)
        file_descriptions = _describe_files(evidence_metadata)

        if not file_descriptions:
            return {"sandbox_output": "", "sandbox_code": ""}

        # Generate code
        prompt = CODE_GENERATION_PROMPT.format(
            task_description=task_description,
            file_descriptions=file_descriptions,
        )

        response = await llm.complete(
            messages=[{"role": "user", "content": prompt}],
            task="generate_code",
            tenant_id=tenant_id,
            trace_id=trace_id,
            temperature=0.0,
            max_tokens=2000,
        )

        code = _extract_code(response.content)

        # Prepare file references for sandbox
        files: dict[str, str] = {}
        for meta in evidence_metadata:
            if meta.file_type in ("spreadsheet", "csv", "json"):
                filename = meta.storage_key.rsplit("/", 1)[-1] if "/" in meta.storage_key else meta.storage_key
                files[filename] = meta.storage_key

        # Execute in sandbox
        result = await sandbox.execute(
            code=code,
            files=files,
            timeout_sec=60,
            trace_id=trace_id,
        )

        elapsed_ms = (time.time() - start_time) * 1000

        if result.success:
            logger.info(
                "sandbox_execution_success",
                duration_ms=result.duration_ms,
                trace_id=trace_id,
            )
        else:
            logger.warning(
                "sandbox_execution_failed",
                stderr=result.stderr[:500],
                trace_id=trace_id,
            )

        # Update timing
        existing_timing = state.get("timing")
        timing_dict: dict[str, float] = {}
        if existing_timing is not None:
            timing_dict["discovery_ms"] = existing_timing.discovery_ms
            timing_dict["extraction_ms"] = existing_timing.extraction_ms
            timing_dict["layer1_ms"] = existing_timing.layer1_ms
            timing_dict["layer2_ms"] = existing_timing.layer2_ms
            timing_dict["layer3_ms"] = existing_timing.layer3_ms
        timing_dict["sandbox_ms"] = elapsed_ms

        # Update layer stats
        existing_stats = state.get("layer_stats")
        stats_dict: dict[str, int] = {}
        if existing_stats is not None:
            stats_dict["layer1_resolved"] = existing_stats.layer1_resolved
            stats_dict["layer2_resolved"] = existing_stats.layer2_resolved
            stats_dict["total_criteria"] = existing_stats.total_criteria
            stats_dict["llm_calls"] = existing_stats.llm_calls
        stats_dict["sandbox_calls"] = stats_dict.get("sandbox_calls", 0) + 1

        from src.models import LayerStats

        return {
            "sandbox_code": code,
            "sandbox_output": result.stdout if result.success else result.stderr,
            "sandbox_retries": state.get("sandbox_retries", 0),
            "timing": TimingStats(**timing_dict),
            "layer_stats": LayerStats(**stats_dict),
        }

    finally:
        await llm.close()
        await sandbox.close()


def _build_task_description(state: EvalGraphState) -> str:
    """Build a description of what the sandbox code should analyze."""
    control_id = state.get("control_id", "")
    framework = state.get("framework", "")
    testing_criteria = state.get("testing_criteria")

    needs_judgment = state.get("needs_judgment", [])

    parts = [f"Analyze data for control {control_id} ({framework})."]

    if testing_criteria is not None:
        for criterion in testing_criteria.criteria:
            if criterion.id in needs_judgment and criterion.evidence_type == "structured_data":
                parts.append(
                    f"- {criterion.question} (pass condition: {criterion.pass_condition})"
                )

    return "\n".join(parts)


def _describe_files(evidence_metadata: list[EvidenceMetadata]) -> str:
    """Describe available data files for code generation prompt."""
    descriptions: list[str] = []
    for meta in evidence_metadata:
        if meta.file_type in ("spreadsheet", "csv", "json"):
            filename = meta.storage_key.rsplit("/", 1)[-1] if "/" in meta.storage_key else meta.storage_key
            desc = f"- {filename} ({meta.file_type})"
            if meta.columns:
                desc += f"\n  Columns: {', '.join(meta.columns[:20])}"
            if meta.row_count:
                desc += f"\n  Rows: {meta.row_count}"
            descriptions.append(desc)

    return "\n".join(descriptions)


def _extract_code(content: str) -> str:
    """Extract Python code from LLM response, handling markdown fences."""
    content = content.strip()

    # Remove markdown code fences if present
    if content.startswith("```python"):
        content = content[len("```python"):].strip()
    elif content.startswith("```"):
        content = content[3:].strip()

    if content.endswith("```"):
        content = content[:-3].strip()

    return content
