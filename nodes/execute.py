"""Purchase request execution node (deterministic).

Creates a purchase request ONLY after human approval and successful
revalidation.  Uses an idempotency key derived from case_id and
proposal_hash to prevent duplicate writes.

CRITICAL: This node is NEVER exposed to an LLM agent.
"""

from __future__ import annotations

from domain.tool_models import ReplenishmentProposal
from tools.execution import create_purchase_request
from nodes.audit import audit_node
from state.state import OptiStockState


def execute_node(state: OptiStockState) -> dict:
    """Create the purchase request and update state.

    Preconditions (enforced by graph routing):
    1. Human approval received (approval_decision.decision == "APPROVED")
    2. Revalidation passed (revalidation_result.all_checks_pass == True)

    The idempotency key ensures that resuming the same approval twice
    returns the existing purchase request rather than creating a duplicate.
    """
    try:
        proposal = ReplenishmentProposal.model_validate(state["proposal"])

        # Deterministic idempotency key: same case + same proposal = same key
        idempotency_key = f"{state['case_id']}:{state['proposal_hash']}"

        approved_by = state.get("approved_by", "unknown")

        result = create_purchase_request(
            proposal=proposal,
            idempotency_key=idempotency_key,
            approved_by=approved_by,
        )
        result_dict = result.model_dump(mode="json")

        # Log audit event
        audit_update = audit_node(
            state,
            actor="system:execution",
            event_type="purchase_request_created" if result.created else "purchase_request_idempotent",
            payload={
                "request_id": result.request_id,
                "case_id": result.case_id,
                "status": result.status,
                "created": result.created,
                "total_cost": result.total_cost,
                "idempotency_key": idempotency_key,
                "approved_by": approved_by,
            },
        )

        updates = {
            "purchase_request": result_dict,
            "idempotency_key": idempotency_key,
            **audit_update,
        }

        if result.error:
            updates["outcome"] = "BLOCKED"
            updates["error_code"] = result.error
            updates["error_message"] = result.error_details or "Purchase request write failed"
        else:
            updates["outcome"] = "PURCHASE_REQUEST_CREATED"

        return updates

    except Exception as e:
        return {
            "outcome": "BLOCKED",
            "error_code": "WRITE_FAILED",
            "error_message": f"Execution error: {str(e)}",
        }
