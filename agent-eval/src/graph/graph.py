"""LangGraph evaluation pipeline definition.

Defines the graph structure with nodes and conditional edges.
The graph implements the 3-layer evaluation pipeline:
  router -> discovery -> extractor -> rules_engine ->
  evaluation (conditional) -> scoring -> formatter

Conditional edges:
- After router: route by intent (evaluate/chat/status)
- After discovery: skip to formatter if cached or no evidence
- After rules_engine: skip evaluation if no NEEDS_JUDGMENT
- After sandbox: retry via code_fixer or continue
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from src.config import get_settings
from src.graph.code_fixer import code_fixer_node
from src.graph.discovery import discovery_node
from src.graph.evaluation import evaluation_node
from src.graph.extractor import extractor_node
from src.graph.formatter import formatter_node
from src.graph.router import router_node
from src.graph.rules_engine import rules_engine_node
from src.graph.sandbox_node import sandbox_node
from src.graph.scoring import scoring_node
from src.graph.state import EvalGraphState
from src.rag.retriever import load_testing_criteria_node


def _route_after_router(state: EvalGraphState) -> str:
    """Route based on classified intent."""
    intent = state.get("intent", "evaluate")
    if intent == "evaluate":
        return "discovery"
    if intent == "chat":
        return "formatter"
    # status intent goes directly to formatter
    return "formatter"


def _route_after_discovery(state: EvalGraphState) -> str:
    """Route based on discovery results."""
    # If we got a cached result, skip to formatter
    cached = state.get("cached_result")
    if cached is not None:
        return "formatter"

    # If no evidence and there's an error, skip to formatter
    evidence_files = state.get("evidence_files", [])
    if not evidence_files and state.get("error"):
        return "formatter"

    return "extractor"


def _route_after_rules(state: EvalGraphState) -> str:
    """Route based on rule engine results.

    If all criteria resolved (no NEEDS_JUDGMENT), skip LLM evaluation.
    If structured data needs analysis, go to sandbox first.
    """
    needs_judgment = state.get("needs_judgment", [])

    if not needs_judgment:
        # All criteria resolved by rules - skip Layer 2 entirely
        return "scoring"

    # Check if any NEEDS_JUDGMENT criteria involve structured data
    # that needs sandbox execution
    testing_criteria = state.get("testing_criteria")
    if testing_criteria is not None:
        criteria_map = {c.id: c for c in testing_criteria.criteria}
        for criterion_id in needs_judgment:
            criterion = criteria_map.get(criterion_id)
            if criterion and criterion.evidence_type == "structured_data":
                has_structured_evidence = any(
                    m.file_type in ("spreadsheet", "csv", "json")
                    for m in state.get("evidence_metadata", [])
                )
                if has_structured_evidence:
                    return "sandbox"

    return "evaluation"


def _route_after_sandbox(state: EvalGraphState) -> str:
    """Route based on sandbox execution result."""
    sandbox_output = state.get("sandbox_output", "")
    sandbox_retries = state.get("sandbox_retries", 0)
    settings = get_settings()

    # If sandbox failed and we have retries left, go to code_fixer
    if not sandbox_output or (
        "error" in sandbox_output.lower()
        and sandbox_retries < settings.max_sandbox_retries
    ):
        return "code_fixer"

    # Move to LLM evaluation for remaining criteria
    return "evaluation"


def _route_after_code_fixer(state: EvalGraphState) -> str:
    """Route based on code fixer result."""
    sandbox_retries = state.get("sandbox_retries", 0)
    settings = get_settings()

    # If still failing after retries, skip to evaluation
    if sandbox_retries >= settings.max_sandbox_retries:
        return "evaluation"

    # Re-check sandbox output
    sandbox_output = state.get("sandbox_output", "")
    if sandbox_output and "error" not in sandbox_output.lower():
        return "evaluation"

    return "evaluation"


def build_eval_graph() -> Any:
    """Build and compile the LangGraph evaluation pipeline.

    Returns:
        Compiled LangGraph StateGraph ready for invocation.
    """
    graph = StateGraph(EvalGraphState)

    # Add nodes
    graph.add_node("router", router_node)
    graph.add_node("discovery", discovery_node)
    graph.add_node("extractor", extractor_node)
    graph.add_node("load_criteria", load_testing_criteria_node)
    graph.add_node("rules_engine", rules_engine_node)
    graph.add_node("evaluation", evaluation_node)
    graph.add_node("scoring", scoring_node)
    graph.add_node("sandbox", sandbox_node)
    graph.add_node("code_fixer", code_fixer_node)
    graph.add_node("formatter", formatter_node)

    # Set entry point
    graph.set_entry_point("router")

    # Conditional edges from router
    graph.add_conditional_edges(
        "router",
        _route_after_router,
        {
            "discovery": "discovery",
            "formatter": "formatter",
        },
    )

    # Conditional edges from discovery
    graph.add_conditional_edges(
        "discovery",
        _route_after_discovery,
        {
            "extractor": "extractor",
            "formatter": "formatter",
        },
    )

    # Extractor -> load_criteria
    graph.add_edge("extractor", "load_criteria")

    # load_criteria -> rules_engine
    graph.add_edge("load_criteria", "rules_engine")

    # Conditional edges from rules engine
    graph.add_conditional_edges(
        "rules_engine",
        _route_after_rules,
        {
            "scoring": "scoring",
            "evaluation": "evaluation",
            "sandbox": "sandbox",
        },
    )

    # Conditional edges from sandbox
    graph.add_conditional_edges(
        "sandbox",
        _route_after_sandbox,
        {
            "code_fixer": "code_fixer",
            "evaluation": "evaluation",
        },
    )

    # Conditional edges from code_fixer
    graph.add_conditional_edges(
        "code_fixer",
        _route_after_code_fixer,
        {
            "evaluation": "evaluation",
        },
    )

    # Evaluation -> scoring
    graph.add_edge("evaluation", "scoring")

    # Scoring -> formatter
    graph.add_edge("scoring", "formatter")

    # Formatter -> END
    graph.add_edge("formatter", END)

    return graph.compile()
