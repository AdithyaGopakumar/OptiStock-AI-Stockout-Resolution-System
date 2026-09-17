"""Approval preparation node (deterministic).

Packages the proposal into an ``ApprovalRequest`` and sets up the
LangGraph interrupt for human review.
"""

from __future__ import annotations

from domain.tool_models import ReplenishmentProposal
from tools.workflow import prepare_approval_request
from nodes.audit import audit_node
from state.state import OptiStockState


def prepare_approval_node(state: OptiStockState) -> dict:
    """Create the approval payload and prepare for the human interrupt.

    Reads the proposal from state, delegates to the provided
    ``prepare_approval_request`` helper, and stores the result.
    """
    try:
        proposal = ReplenishmentProposal.model_validate(state["proposal"])
        approval_request = prepare_approval_request(proposal)
        approval_dict = approval_request.model_dump(mode="json")

        # Log audit event
        audit_update = audit_node(
            state,
            actor="system:prepare_approval",
            event_type="approval_requested",
            payload={
                "proposal_id": proposal.proposal_id,
                "case_id": state["case_id"],
            },
        )

        return {
            "approval_request": approval_dict,
            "outcome": "AWAITING_APPROVAL",
            **audit_update,
        }
    except Exception as e:
        return {
            "outcome": "BLOCKED",
            "error_code": "UNKNOWN_ERROR",
            "error_message": f"Failed to prepare approval: {str(e)}",
        }
