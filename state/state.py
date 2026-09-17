"""Optistock Shared State

Defines the LangGraph TypedDict state that flows through every node
and persists across the human-approval interrupt.

Design principles
-----------------
* All Pydantic models are stored as ``dict`` (JSON-serialisable) so that
  LangGraph's checkpointer can serialise/deserialise across the pause.
* Models are reconstructed via ``ModelClass.model_validate(state["field"])``
  when a node needs the typed version.
* ``messages`` uses LangGraph's ``add_messages`` reducer so that agent
  conversation history accumulates correctly.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class OptiStockState(TypedDict, total=False):
    """Shared workflow state for one stockout-resolution case.

    Categories: input, evidence (investigation + sourcing), proposal,
    review, approval, execution, workflow control, audit.
    """

    # ── INPUT ──────────────────────────────────────────────────────────
    case_id: str
    trace_id: str
    sku: Optional[str]
    warehouse_id: Optional[str]
    target_cover_days: int

    # ── INVESTIGATION EVIDENCE ─────────────────────────────────────────
    product: Optional[Dict[str, Any]]
    stock_position: Optional[Dict[str, Any]]
    sales_velocity: Optional[Dict[str, Any]]
    stock_risk: Optional[Dict[str, Any]]
    investigation_result: Optional[Dict[str, Any]]

    # ── SOURCING EVIDENCE ──────────────────────────────────────────────
    vendor_offers: Optional[Dict[str, Any]]
    vendor_performance: Optional[Dict[str, Any]]
    vendor_options: Optional[Dict[str, Any]]
    vendor_recommendation: Optional[Dict[str, Any]]
    budget_position: Optional[Dict[str, Any]]
    sourcing_result: Optional[Dict[str, Any]]

    # ── PROPOSAL ───────────────────────────────────────────────────────
    proposal: Optional[Dict[str, Any]]
    proposal_hash: Optional[str]

    # ── REVIEW ─────────────────────────────────────────────────────────
    review_result: Optional[Dict[str, Any]]
    policy_guidance: Optional[Dict[str, Any]]

    # ── APPROVAL ───────────────────────────────────────────────────────
    approval_request: Optional[Dict[str, Any]]
    approval_decision: Optional[Dict[str, Any]]
    approved_by: Optional[str]

    # ── EXECUTION ──────────────────────────────────────────────────────
    revalidation_result: Optional[Dict[str, Any]]
    purchase_request: Optional[Dict[str, Any]]
    idempotency_key: Optional[str]

    # ── WORKFLOW CONTROL ───────────────────────────────────────────────
    outcome: Optional[str]        # Final ProposalStatus value
    error_code: Optional[str]     # ErrorCode if the case failed
    error_message: Optional[str]  # Human-readable error
    retry_count: int              # Agent output validation retries (max 1)
    revision_count: int           # Proposal revision loops (max 1)

    # ── AUDIT ──────────────────────────────────────────────────────────
    audit_events: List[str]       # Accumulated audit event IDs

    # ── LANGGRAPH MESSAGES ─────────────────────────────────────────────
    messages: Annotated[list, add_messages]


def make_initial_state(
    sku: Optional[str],
    warehouse_id: Optional[str],
    target_cover_days: int = 14,
) -> OptiStockState:
    """Create a fresh state dict for a new case.

    Generates a unique ``case_id`` and ``trace_id`` automatically.
    """
    case_id = f"CASE-{uuid.uuid4().hex[:10].upper()}"
    trace_id = f"TRACE-{uuid.uuid4().hex[:10].upper()}"

    return OptiStockState(
        case_id=case_id,
        trace_id=trace_id,
        sku=sku,
        warehouse_id=warehouse_id,
        target_cover_days=target_cover_days,
        # Evidence
        product=None,
        stock_position=None,
        sales_velocity=None,
        stock_risk=None,
        investigation_result=None,
        vendor_offers=None,
        vendor_performance=None,
        vendor_options=None,
        vendor_recommendation=None,
        budget_position=None,
        sourcing_result=None,
        # Proposal
        proposal=None,
        proposal_hash=None,
        # Review
        review_result=None,
        policy_guidance=None,
        # Approval
        approval_request=None,
        approval_decision=None,
        approved_by=None,
        # Execution
        revalidation_result=None,
        purchase_request=None,
        idempotency_key=None,
        # Workflow control
        outcome=None,
        error_code=None,
        error_message=None,
        retry_count=0,
        revision_count=0,
        # Audit
        audit_events=[],
        # Messages
        messages=[],
    )
