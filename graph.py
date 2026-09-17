"""OptiStock AI LangGraph Workflow

Wires all agent and deterministic nodes into a single StateGraph with
conditional routing, bounded revision, human approval interrupt, and
terminal states.
"""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command

from state.state import OptiStockState
from nodes.validate_input import validate_input_node
from nodes.draft_proposal import draft_proposal_node
from nodes.prepare_approval import prepare_approval_node
from nodes.revalidate import revalidate_node
from nodes.execute import execute_node
from nodes.audit import audit_node
from agents.investigation import investigation_agent_node
from agents.sourcing import sourcing_agent_node
from agents.review import review_agent_node
from config import MAX_REVISION_COUNT


# ============================================================================
# ROUTING FUNCTIONS
# ============================================================================

def route_after_validation(state: OptiStockState) -> str:
    """Route based on input validation result."""
    if state.get("outcome") == "NEEDS_INFORMATION":
        return "terminal"
    return "investigation_agent"


def route_after_investigation(state: OptiStockState) -> str:
    """Route based on investigation outcome."""
    result = state.get("investigation_result") or {}
    status = result.get("status", "BLOCKED")

    if status == "AT_RISK":
        return "sourcing_agent"
    # NO_ACTION, BLOCKED, NEEDS_INFORMATION → terminal
    return "terminal"


def route_after_sourcing(state: OptiStockState) -> str:
    """Route based on sourcing outcome."""
    result = state.get("sourcing_result") or {}
    status = result.get("status", "BLOCKED")

    if status == "PROPOSAL_READY":
        return "draft_proposal"
    # BLOCKED, NEEDS_INFORMATION → terminal
    return "terminal"


def route_after_review(state: OptiStockState) -> str:
    """Route based on review outcome.

    Supports bounded revision: if the reviewer requests revision and
    we haven't exceeded the revision limit, loop back to sourcing.
    """
    result = state.get("review_result") or {}
    status = result.get("status", "BLOCKED")

    if status == "APPROVED_FOR_HUMAN":
        return "prepare_approval"
    elif status == "NEEDS_REVISION":
        if state.get("revision_count", 0) < MAX_REVISION_COUNT:
            return "revision_bump"
        # Max revisions reached
        return "terminal"
    # BLOCKED → terminal
    return "terminal"


def route_after_approval(state: OptiStockState) -> str:
    """Route based on human approval decision."""
    decision = state.get("approval_decision") or {}
    if decision.get("decision") == "APPROVED":
        return "revalidate"
    # REJECTED → terminal
    return "terminal"


def route_after_revalidation(state: OptiStockState) -> str:
    """Route based on revalidation outcome."""
    result = state.get("revalidation_result") or {}
    if result.get("all_checks_pass"):
        return "execute"
    # Revalidation failed → terminal
    return "terminal"


def route_after_execution(state: OptiStockState) -> str:
    """Always route to terminal after execution."""
    return "terminal"


# ============================================================================
# WRAPPER NODES
# ============================================================================

def revision_bump_node(state: OptiStockState) -> dict:
    """Increment the revision counter before looping back to sourcing."""
    return {"revision_count": state.get("revision_count", 0) + 1}


def human_approval_node(state: OptiStockState) -> dict:
    """Pause the graph for human approval using LangGraph interrupt.

    The interrupt sends the approval request to the caller and waits
    for an ``ApprovalDecision`` to resume the graph.
    """
    approval_request = state.get("approval_request", {})

    # This pauses the graph and waits for human input
    decision = interrupt(approval_request)

    # When resumed, decision contains the ApprovalDecision dict
    # Log the decision
    decision_type = decision.get("decision", "UNKNOWN")
    audit_update = audit_node(
        state,
        actor=f"human:{decision.get('approver', 'unknown')}",
        event_type="approval_decision",
        payload={
            "decision": decision_type,
            "approver": decision.get("approver"),
            "comments": decision.get("comments"),
            "proposal_id": decision.get("proposal_id"),
        },
    )

    updates = {
        "approval_decision": decision,
        "approved_by": decision.get("approver"),
        **audit_update,
    }

    if decision_type == "REJECTED":
        updates["outcome"] = "BLOCKED"
        updates["error_message"] = (
            f"Proposal rejected by {decision.get('approver', 'unknown')}: "
            f"{decision.get('comments', 'No comments')}"
        )

    return updates


def terminal_node(state: OptiStockState) -> dict:
    """Final node — ensures outcome is set and logs terminal audit event."""
    outcome = state.get("outcome")
    if not outcome or outcome == "NEEDS_REVISION":
        # Infer from available results
        if state.get("purchase_request"):
            outcome = "PURCHASE_REQUEST_CREATED"
        elif (state.get("investigation_result") or {}).get("status") == "NO_ACTION":
            outcome = "NO_ACTION"
        else:
            outcome = "BLOCKED"

    # Log terminal event
    audit_update = audit_node(
        state,
        actor="system:terminal",
        event_type="case_closed",
        payload={
            "outcome": outcome,
            "error_code": state.get("error_code"),
            "error_message": state.get("error_message"),
        },
    )

    return {"outcome": outcome, **audit_update}


# ============================================================================
# GRAPH BUILDER
# ============================================================================

def build_graph(checkpointer=None):
    """Build and compile the OptiStock AI LangGraph workflow.

    Parameters
    ----------
    checkpointer : optional
        LangGraph checkpointer for state persistence.
        Defaults to ``MemorySaver`` (in-memory, for development).

    Returns
    -------
    CompiledGraph
        Ready-to-invoke LangGraph workflow.
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    graph = StateGraph(OptiStockState)

    # ── Add nodes ──
    graph.add_node("validate_input", validate_input_node)
    graph.add_node("investigation_agent", investigation_agent_node)
    graph.add_node("sourcing_agent", sourcing_agent_node)
    graph.add_node("draft_proposal", draft_proposal_node)
    graph.add_node("review_agent", review_agent_node)
    graph.add_node("revision_bump", revision_bump_node)
    graph.add_node("prepare_approval", prepare_approval_node)
    graph.add_node("human_approval", human_approval_node)
    graph.add_node("revalidate", revalidate_node)
    graph.add_node("execute", execute_node)
    graph.add_node("terminal", terminal_node)

    # ── Entry point ──
    graph.add_edge(START, "validate_input")

    # ── Conditional edges ──
    graph.add_conditional_edges("validate_input", route_after_validation)
    graph.add_conditional_edges("investigation_agent", route_after_investigation)
    graph.add_conditional_edges("sourcing_agent", route_after_sourcing)
    graph.add_edge("draft_proposal", "review_agent")
    graph.add_conditional_edges("review_agent", route_after_review)
    graph.add_edge("revision_bump", "sourcing_agent")
    graph.add_edge("prepare_approval", "human_approval")
    graph.add_conditional_edges("human_approval", route_after_approval)
    graph.add_conditional_edges("revalidate", route_after_revalidation)
    graph.add_conditional_edges("execute", route_after_execution)

    # ── Terminal → END ──
    graph.add_edge("terminal", END)

    return graph.compile(checkpointer=checkpointer)
