"""Proposal drafting node (deterministic).

Assembles a ``ReplenishmentProposal`` from validated evidence using the
provided ``draft_replenishment_proposal`` helper.  No LLM involvement.
"""

from __future__ import annotations

from domain.tool_models import (
    BudgetPosition,
    ProposalDraftInput,
    SalesVelocity,
    StockPosition,
    StockRisk,
    VendorRecommendation,
)
from tools.workflow import draft_replenishment_proposal
from nodes.audit import audit_node
from state.state import OptiStockState


def draft_proposal_node(state: OptiStockState) -> dict:
    """Build a formal replenishment proposal from state evidence.

    Reads investigation and sourcing evidence from state, reconstructs
    Pydantic models, and delegates to the provided ``draft_replenishment_proposal``
    helper.  Sets ``proposal`` and ``proposal_hash`` in state.
    """
    try:
        stock = StockPosition.model_validate(state["stock_position"])
        sales = SalesVelocity.model_validate(state["sales_velocity"])
        risk = StockRisk.model_validate(state["stock_risk"])
        budget = BudgetPosition.model_validate(state["budget_position"])
        recommendation = VendorRecommendation.model_validate(state["vendor_recommendation"])

        draft_input = ProposalDraftInput(
            case_id=state["case_id"],
            sku=state["sku"],
            warehouse_id=state["warehouse_id"],
            target_cover_days=state["target_cover_days"],
            stock=stock,
            sales=sales,
            risk=risk,
            budget=budget,
            recommendation=recommendation,
        )

        proposal = draft_replenishment_proposal(draft_input)
        proposal_dict = proposal.model_dump(mode="json")

        # Log audit event
        audit_update = audit_node(
            state,
            actor="system:draft_proposal",
            event_type="proposal_drafted",
            payload={
                "proposal_id": proposal.proposal_id,
                "proposal_hash": proposal.proposal_hash,
                "vendor_id": proposal.recommended_vendor_id,
                "total_cost": proposal.total_cost,
                "quantity": proposal.quantity,
            },
        )

        return {
            "proposal": proposal_dict,
            "proposal_hash": proposal.proposal_hash,
            **audit_update,
        }
    except Exception as e:
        return {
            "outcome": "BLOCKED",
            "error_code": "UNKNOWN_ERROR",
            "error_message": f"Failed to draft proposal: {str(e)}",
        }
