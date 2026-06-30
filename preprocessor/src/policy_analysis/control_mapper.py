"""Map extracted obligations to compliance framework controls via LLM.

Takes obligations from the graph extractor and asks the LLM which
framework control(s) each obligation satisfies. Batches obligations
to reduce LLM costs.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

from common.clients import LLMClient
from common.errors import LLMCreditExhaustedError, LLMUnavailableError

from src.policy_analysis.models import ControlMapping

logger = structlog.get_logger(__name__)

# Number of obligations to batch per LLM call
_BATCH_SIZE = 5

_MAPPING_PROMPT = """Map these compliance obligations to {framework} framework controls.

Obligations:
{obligations_list}

For each obligation, identify which {framework} control(s) it satisfies.
Common controls for SOC2: CC6.1 (access control), CC6.2 (credentials), CC6.3 (encryption), CC6.6 (external threats), CC6.7 (data transmission), CC7.1 (monitoring), CC7.2 (anomaly detection), CC8.1 (change management), CC9.1 (risk mitigation).
Common controls for ISO27001: A.5 (policies), A.6 (organization), A.7 (HR), A.8 (asset mgmt), A.9 (access control), A.10 (crypto), A.12 (operations), A.13 (comms), A.14 (acquisition), A.16 (incident), A.18 (compliance).

Respond in JSON:
{{"mappings": [{{"obligation_index": 0, "control_ids": ["CC6.1"], "confidence": 0.9}}]}}"""


class ControlMapper:
    """Maps extracted obligations to framework controls via LLM.

    Batches obligations (default 5 per call) to reduce LLM costs.
    On failure for a batch, logs a warning and skips that batch.
    """

    def __init__(self, llm: LLMClient) -> None:
        """Initialize the mapper.

        Args:
            llm: LLMClient instance for gateway calls.
        """
        self._llm = llm

    async def map_obligations(
        self,
        obligations: list[dict[str, Any]],
        framework: str,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        """Map obligations to framework controls.

        Processes obligations in batches of ``_BATCH_SIZE``. For each batch,
        sends the obligation texts to the LLM and parses the control mapping
        response.

        Args:
            obligations: List of obligation dicts. Each should have at
                minimum ``id`` and ``text`` keys.
            framework: Framework identifier (e.g., "SOC2", "ISO27001").
            tenant_id: Tenant ID for LLM budget tracking.

        Returns:
            List of mapping dicts with keys: ``obligation_id``, ``framework``,
            ``control_id``, ``confidence``.
        """
        if not obligations:
            return []

        all_mappings: list[dict[str, Any]] = []

        # Process in batches
        for batch_start in range(0, len(obligations), _BATCH_SIZE):
            batch = obligations[batch_start : batch_start + _BATCH_SIZE]

            try:
                batch_mappings = await self._map_batch(
                    batch=batch,
                    batch_offset=batch_start,
                    framework=framework,
                    tenant_id=tenant_id,
                )
                all_mappings.extend(batch_mappings)
            except (LLMUnavailableError, LLMCreditExhaustedError) as exc:
                logger.warning(
                    "control_mapping_llm_failure",
                    batch_start=batch_start,
                    batch_size=len(batch),
                    framework=framework,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                continue
            except Exception as exc:
                logger.warning(
                    "control_mapping_unexpected_error",
                    batch_start=batch_start,
                    batch_size=len(batch),
                    framework=framework,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                continue

        logger.info(
            "control_mapping_complete",
            framework=framework,
            obligations_count=len(obligations),
            mappings_count=len(all_mappings),
            tenant_id=tenant_id,
        )

        return all_mappings

    async def _map_batch(
        self,
        batch: list[dict[str, Any]],
        batch_offset: int,
        framework: str,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        """Map a single batch of obligations to controls.

        Args:
            batch: Subset of obligations to map.
            batch_offset: Starting index of this batch in the full list.
            framework: Target framework name.
            tenant_id: Tenant for budget tracking.

        Returns:
            List of mapping dicts for this batch.

        Raises:
            LLMUnavailableError: If the gateway is unreachable.
            LLMCreditExhaustedError: If budget is exhausted.
        """
        # Build numbered obligation list for the prompt
        obligation_lines: list[str] = []
        for i, obl in enumerate(batch):
            text = obl.get("text", obl.get("label", ""))
            subject = obl.get("subject", "")
            prefix = f"[{i}] "
            if subject:
                prefix += f"({subject}) "
            obligation_lines.append(f"{prefix}{text}")

        obligations_text = "\n".join(obligation_lines)

        prompt = _MAPPING_PROMPT.format(
            framework=framework,
            obligations_list=obligations_text,
        )

        response = await self._llm.complete(
            messages=[{"role": "user", "content": prompt}],
            task="map_obligation_to_control",
            tenant_id=tenant_id,
            temperature=0.0,
            max_tokens=1024,
        )

        parsed = self._parse_mapping_response(response.content)
        return self._build_mappings(parsed, batch, batch_offset, framework)

    def _parse_mapping_response(self, content: str) -> dict[str, Any]:
        """Parse the LLM mapping response as JSON.

        Args:
            content: Raw LLM response text.

        Returns:
            Parsed dict with ``mappings`` key. Returns empty on failure.
        """
        text = content.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(
                "control_mapping_json_parse_failed",
                content_preview=content[:200],
            )
            return {"mappings": []}

    def _build_mappings(
        self,
        parsed: dict[str, Any],
        batch: list[dict[str, Any]],
        batch_offset: int,
        framework: str,
    ) -> list[dict[str, Any]]:
        """Convert parsed LLM output to ControlMapping dicts.

        Args:
            parsed: Parsed JSON from the LLM response.
            batch: The batch of obligations that were sent.
            batch_offset: Index offset in the original obligation list.
            framework: Framework name.

        Returns:
            List of mapping dicts.
        """
        mappings: list[dict[str, Any]] = []

        for mapping_entry in parsed.get("mappings", []):
            obl_index = mapping_entry.get("obligation_index", -1)
            control_ids = mapping_entry.get("control_ids", [])
            confidence = mapping_entry.get("confidence", 0.8)

            # Validate index
            if not isinstance(obl_index, int) or obl_index < 0 or obl_index >= len(batch):
                continue

            obligation = batch[obl_index]
            obligation_id = obligation.get("id", str(uuid.uuid4()))

            for ctrl_id in control_ids:
                if isinstance(ctrl_id, str) and ctrl_id.strip():
                    mapping = ControlMapping(
                        obligation_id=obligation_id,
                        framework=framework,
                        control_id=ctrl_id.strip(),
                        confidence=min(max(float(confidence), 0.0), 1.0),
                        source_section=obligation.get("section_id", ""),
                    )
                    mappings.append(mapping.model_dump(mode="json"))

        return mappings
