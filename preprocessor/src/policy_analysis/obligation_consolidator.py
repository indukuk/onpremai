"""Merge obligation graphs from multiple policies and detect conflicts.

Combines nodes and edges from multiple PolicyGraph outputs, deduplicates
obligations by content similarity, and flags conflicting thresholds for
the same control.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from src.policy_analysis.models import (
    PolicyEntity,
    PolicyGraph,
    PolicyRelationship,
)

logger = structlog.get_logger(__name__)

# Minimum similarity ratio for treating two obligations as duplicates.
_DEDUP_THRESHOLD = 0.85


class ObligationConsolidator:
    """Merges multiple PolicyGraph dicts and detects conflicts.

    Handles:
    - Combining nodes and edges from multiple document graphs
    - Deduplicating obligations by simple content similarity (V1)
    - Detecting threshold conflicts for the same control
    """

    def merge_graphs(self, graphs: list[dict[str, Any]]) -> dict[str, Any]:
        """Combine multiple PolicyGraph dicts into a single consolidated graph.

        Deduplicates obligation nodes by content similarity. Other node
        types (roles, terms, thresholds, controls) are merged by label
        match.

        Args:
            graphs: List of PolicyGraph dicts (as returned by GraphExtractor).

        Returns:
            Dict with keys:
            - ``graph``: Consolidated PolicyGraph dict.
            - ``conflicts``: List of detected conflicts.
            - ``stats``: Merge statistics.
        """
        if not graphs:
            return {
                "graph": PolicyGraph(
                    tenant_id="", document_id="consolidated", document_name="Consolidated"
                ).model_dump(mode="json"),
                "conflicts": [],
                "stats": {"total_nodes": 0, "total_edges": 0, "duplicates_removed": 0},
            }

        # Determine tenant_id from first graph
        tenant_id = graphs[0].get("tenant_id", "")

        all_nodes: list[dict[str, Any]] = []
        all_edges: list[dict[str, Any]] = []

        for graph in graphs:
            nodes = graph.get("nodes", [])
            edges = graph.get("edges", [])
            all_nodes.extend(nodes)
            all_edges.extend(edges)

        original_count = len(all_nodes)

        # Deduplicate nodes
        deduped_nodes, id_map = self._deduplicate_nodes(all_nodes)

        # Remap edges to use deduplicated IDs
        remapped_edges = self._remap_edges(all_edges, id_map)

        # Remove duplicate edges
        unique_edges = self._deduplicate_edges(remapped_edges)

        duplicates_removed = original_count - len(deduped_nodes)

        # Detect conflicts among obligation nodes
        conflicts = self.detect_conflicts(
            [n for n in deduped_nodes if n.get("entity_type") == "obligation"]
        )

        consolidated = PolicyGraph(
            tenant_id=tenant_id,
            document_id="consolidated",
            document_name="Consolidated Policy Graph",
            nodes=[PolicyEntity(**n) for n in deduped_nodes],
            edges=[PolicyRelationship(**e) for e in unique_edges],
        )

        logger.info(
            "graphs_merged",
            input_graphs=len(graphs),
            total_nodes=len(deduped_nodes),
            total_edges=len(unique_edges),
            duplicates_removed=duplicates_removed,
            conflicts_found=len(conflicts),
        )

        return {
            "graph": consolidated.model_dump(mode="json"),
            "conflicts": conflicts,
            "stats": {
                "total_nodes": len(deduped_nodes),
                "total_edges": len(unique_edges),
                "duplicates_removed": duplicates_removed,
                "input_graphs": len(graphs),
            },
        }

    def detect_conflicts(self, obligations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Detect conflicting obligations for the same control.

        Groups obligations by their associated control_id (from properties
        or linked control nodes), then checks for contradicting thresholds.

        Args:
            obligations: List of obligation node dicts.

        Returns:
            List of conflict dicts with keys: ``control_id``, ``conflict``,
            ``source_a``, ``source_b``.
        """
        conflicts: list[dict[str, Any]] = []

        # Group obligations that mention thresholds by action similarity
        threshold_groups: dict[str, list[dict[str, Any]]] = {}
        for obl in obligations:
            props = obl.get("properties", {})
            threshold = props.get("threshold", "")
            action = props.get("action", "").lower().strip()

            if not threshold or not action:
                continue

            # Group by a normalized action key
            key = self._normalize_action(action)
            if key not in threshold_groups:
                threshold_groups[key] = []
            threshold_groups[key].append(obl)

        # Check each group for conflicting thresholds
        for action_key, group in threshold_groups.items():
            if len(group) < 2:
                continue

            # Compare all pairs
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    obl_a = group[i]
                    obl_b = group[j]
                    props_a = obl_a.get("properties", {})
                    props_b = obl_b.get("properties", {})

                    threshold_a = props_a.get("threshold", "")
                    threshold_b = props_b.get("threshold", "")

                    # If thresholds differ for same action, flag as conflict
                    if threshold_a and threshold_b and threshold_a != threshold_b:
                        conflicts.append({
                            "control_id": action_key,
                            "conflict": (
                                f"Conflicting thresholds for '{action_key}': "
                                f"'{threshold_a}' vs '{threshold_b}'"
                            ),
                            "source_a": {
                                "id": obl_a.get("id", ""),
                                "section_id": obl_a.get("section_id", ""),
                                "text": props_a.get("full_text", obl_a.get("label", "")),
                                "threshold": threshold_a,
                            },
                            "source_b": {
                                "id": obl_b.get("id", ""),
                                "section_id": obl_b.get("section_id", ""),
                                "text": props_b.get("full_text", obl_b.get("label", "")),
                                "threshold": threshold_b,
                            },
                        })

        return conflicts

    def _deduplicate_nodes(
        self, nodes: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Deduplicate nodes by content similarity.

        For obligation nodes, uses text similarity. For other node types,
        deduplicates by exact label match.

        Args:
            nodes: All nodes from all graphs.

        Returns:
            Tuple of (deduplicated node list, ID remap dict mapping old->new IDs).
        """
        id_map: dict[str, str] = {}  # old_id -> canonical_id
        unique_nodes: list[dict[str, Any]] = []

        # Process by entity type
        obligations: list[dict[str, Any]] = []
        other_nodes: list[dict[str, Any]] = []

        for node in nodes:
            if node.get("entity_type") == "obligation":
                obligations.append(node)
            else:
                other_nodes.append(node)

        # Deduplicate obligations by text similarity
        for obl in obligations:
            obl_id = obl.get("id", "")
            obl_text = obl.get("source_text", obl.get("label", ""))

            # Check if similar obligation already exists
            found_match = False
            for existing in unique_nodes:
                if existing.get("entity_type") != "obligation":
                    continue
                existing_text = existing.get("source_text", existing.get("label", ""))
                if self._text_similarity(obl_text, existing_text) >= _DEDUP_THRESHOLD:
                    id_map[obl_id] = existing.get("id", "")
                    found_match = True
                    break

            if not found_match:
                id_map[obl_id] = obl_id
                unique_nodes.append(obl)

        # Deduplicate other nodes by exact label+type match
        seen_labels: dict[str, str] = {}  # (type, label) -> canonical id
        for node in other_nodes:
            node_id = node.get("id", "")
            entity_type = node.get("entity_type", "")
            label = node.get("label", "").lower().strip()
            key = f"{entity_type}::{label}"

            if key in seen_labels:
                id_map[node_id] = seen_labels[key]
            else:
                seen_labels[key] = node_id
                id_map[node_id] = node_id
                unique_nodes.append(node)

        return unique_nodes, id_map

    def _remap_edges(
        self, edges: list[dict[str, Any]], id_map: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Remap edge source/target IDs using the deduplication map.

        Args:
            edges: Original edges from all graphs.
            id_map: Mapping from old node IDs to canonical IDs.

        Returns:
            Edges with remapped IDs.
        """
        remapped: list[dict[str, Any]] = []
        for edge in edges:
            source = edge.get("source_id", "")
            target = edge.get("target_id", "")
            remapped.append({
                "source_id": id_map.get(source, source),
                "target_id": id_map.get(target, target),
                "relationship": edge.get("relationship", ""),
                "properties": edge.get("properties", {}),
            })
        return remapped

    @staticmethod
    def _deduplicate_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove duplicate edges (same source, target, relationship).

        Args:
            edges: Edges after ID remapping.

        Returns:
            List of unique edges.
        """
        seen: set[tuple[str, str, str]] = set()
        unique: list[dict[str, Any]] = []

        for edge in edges:
            key = (
                edge.get("source_id", ""),
                edge.get("target_id", ""),
                edge.get("relationship", ""),
            )
            if key not in seen:
                seen.add(key)
                unique.append(edge)

        return unique

    @staticmethod
    def _text_similarity(text_a: str, text_b: str) -> float:
        """Compute simple word-overlap similarity (Jaccard index).

        V1 implementation uses word-level Jaccard similarity. Future
        versions may use embeddings for semantic similarity.

        Args:
            text_a: First text.
            text_b: Second text.

        Returns:
            Similarity score between 0.0 and 1.0.
        """
        if not text_a or not text_b:
            return 0.0

        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())

        if not words_a or not words_b:
            return 0.0

        intersection = words_a & words_b
        union = words_a | words_b

        return len(intersection) / len(union) if union else 0.0

    @staticmethod
    def _normalize_action(action: str) -> str:
        """Normalize an action string for grouping.

        Removes common words and standardizes for comparison.

        Args:
            action: Raw action text.

        Returns:
            Normalized key for grouping.
        """
        # Remove very common words, keep the semantic core
        stop_words = {"the", "a", "an", "is", "are", "be", "to", "of", "and", "or", "in", "for", "on", "at"}
        words = [w for w in action.lower().split() if w not in stop_words]
        return " ".join(sorted(words[:5]))  # Take first 5 meaningful words, sorted
