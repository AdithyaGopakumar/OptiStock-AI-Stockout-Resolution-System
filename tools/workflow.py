"""Simple workflow helpers for proposal recommendation and human review.

These helpers are intentionally small: they package repeated orchestration
logic into typed functions so notebooks and future agents can follow the
same human-style process without rebuilding the glue each time.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from domain.tool_models import (
    ApprovalRequest,
    BudgetPosition,
    HumanReviewResult,
    ProposalDraftInput,
    ProposalStatus,
    ReplenishmentProposal,
    SalesVelocity,
    StockPosition,
    StockRisk,
    VendorOption,
    VendorOptionList,
    VendorRecommendation,
)


def recommend_vendor_option(
    case_id: str,
    sku: str,
    warehouse_id: str,
    vendor_options: VendorOptionList,
    strategy: str = "balanced",
) -> VendorRecommendation:
    """Choose a recommended option and explain the tradeoff."""
    strategy = strategy.lower()
    eligible = vendor_options.eligible_options

    if not eligible:
        return VendorRecommendation(
            case_id=case_id,
            sku=sku,
            warehouse_id=warehouse_id,
            strategy=strategy,
            recommended_option=None,
            rationale="No vendor can meet both the timing and reliability requirements.",
            blocked=True,
            blocked_reason="NO_ELIGIBLE_VENDOR",
        )

    if strategy == "cheapest":
        chosen = min(eligible, key=lambda option: option.total_cost)
        rationale = "Recommended the lowest-cost eligible option that still meets the deadline."
    elif strategy == "fastest":
        chosen = min(eligible, key=lambda option: option.lead_time_days)
        rationale = "Recommended the fastest eligible option to reduce stockout risk sooner."
    else:
        cheapest = min(eligible, key=lambda option: option.total_cost)
        fastest = min(eligible, key=lambda option: option.lead_time_days)
        chosen = cheapest
        rationale = "Recommended the lowest-cost eligible option."
        if fastest.vendor_id != cheapest.vendor_id:
            rationale = (
                f"Recommended {chosen.vendor_name} as the balanced choice because it is eligible "
                f"and cheaper than the fastest alternative {fastest.vendor_name}."
            )

    return VendorRecommendation(
        case_id=case_id,
        sku=sku,
        warehouse_id=warehouse_id,
        strategy=strategy,
        recommended_option=chosen,
        rationale=rationale,
        blocked=False,
        blocked_reason=None,
    )


def draft_replenishment_proposal(input: ProposalDraftInput) -> ReplenishmentProposal:
    """Turn validated evidence and a recommendation into a reviewable proposal."""
    option = input.recommendation.recommended_option
    if option is None:
        raise ValueError("Cannot draft a proposal without a recommended vendor option.")

    proposal_id = f"PROP-{input.case_id}"
    proposal_hash = hashlib.sha256(
        "|".join(
            [
                input.case_id,
                input.sku,
                input.warehouse_id,
                option.vendor_id,
                str(option.quantity),
                str(option.unit_price),
                str(input.target_cover_days),
            ]
        ).encode()
    ).hexdigest()

    cheapest = input.recommendation.recommended_option.flag_cheapest
    fastest = input.recommendation.recommended_option.flag_fastest
    tradeoff = input.recommendation.rationale
    if not cheapest and fastest:
        tradeoff = "Fastest option chosen even though it is not the cheapest."

    return ReplenishmentProposal(
        proposal_id=proposal_id,
        proposal_hash=proposal_hash,
        case_id=input.case_id,
        sku=input.sku,
        warehouse_id=input.warehouse_id,
        stock_evidence_id=input.stock.evidence_id,
        sales_evidence_id=input.sales.evidence_id,
        vendor_evidence_ids=[option.offer_id],  # Trace back to the specific offer
        budget_evidence_id=input.budget.evidence_id,
        available_units=input.risk.available_units,
        daily_velocity=input.risk.daily_velocity,
        target_cover_days=input.target_cover_days,
        projected_stockout_date=input.risk.projected_stockout_date,
        recommended_vendor_id=option.vendor_id,
        recommended_vendor_name=option.vendor_name,
        quantity=option.quantity,
        unit_price=option.unit_price,
        total_cost=option.total_cost,
        expected_arrival=option.expected_arrival,
        cost_vs_speed_trade_off=tradeoff,
        other_options_summary="See vendor options evidence for alternative eligible and ineligible choices.",
        budget_remaining=input.budget.remaining,
        policy_passed=False,
        policy_violations=[],
        created_at=datetime.utcnow(),
    )


def prepare_approval_request(proposal: ReplenishmentProposal) -> ApprovalRequest:
    """Create the pause payload shown to a human approver."""
    return ApprovalRequest(case_id=proposal.case_id, proposal=proposal, approval_required=True)


def record_human_review(
    case_id: str,
    proposal: ReplenishmentProposal,
    approver: str,
    decision: str,
    comments: str | None = None,
) -> HumanReviewResult:
    """Normalize human review choices into workflow-friendly status values."""
    normalized = decision.upper()
    if normalized == "APPROVED":
        next_status = ProposalStatus.AWAITING_APPROVAL
        summary = f"{approver} approved proposal {proposal.proposal_id} pending revalidation."
    elif normalized == "REJECTED":
        next_status = ProposalStatus.BLOCKED
        summary = f"{approver} rejected proposal {proposal.proposal_id}."
    else:
        normalized = "REVISE"
        next_status = ProposalStatus.NEEDS_INFORMATION
        summary = f"{approver} requested revisions for proposal {proposal.proposal_id}."

    return HumanReviewResult(
        case_id=case_id,
        proposal_id=proposal.proposal_id,
        decision=normalized,
        approver=approver,
        comments=comments,
        next_status=next_status,
        review_summary=summary,
        reviewed_at=datetime.utcnow(),
    )
