"""Pydantic output contracts for LLM agents.

Each agent produces a structured output validated against these models.
The next node in the workflow can rely on these fields being present
and correctly typed — no free-form prose parsing required.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ============================================================================
# Investigation Agent Output
# ============================================================================

class InvestigationResult(BaseModel):
    """Structured output from the Investigation Agent.

    The agent gathers product, stock, and sales data, then runs the
    deterministic stock-risk calculation to decide whether replenishment
    action is needed.
    """

    status: Literal["AT_RISK", "NO_ACTION", "BLOCKED", "NEEDS_INFORMATION", "INVALID_INPUT"] = Field(
        ...,
        description=(
            "AT_RISK: stock below target coverage, proceed to sourcing. "
            "NO_ACTION: stock is healthy. "
            "BLOCKED: stale data, inactive product, or unrecoverable error. "
            "NEEDS_INFORMATION: insufficient sales data or missing info. "
            "INVALID_INPUT: invalid or non-existent SKU or warehouse ID."
        ),
    )
    sku: str = Field(..., description="Product SKU investigated")
    warehouse_id: str = Field(..., description="Warehouse investigated")

    # Evidence references — populated from tool outputs
    product_evidence_id: str = Field(default="", description="Evidence ID from get_product")
    stock_evidence_id: str = Field(default="", description="Evidence ID from get_stock_position")
    sales_evidence_id: str = Field(default="", description="Evidence ID from get_sales_velocity")

    # Key facts from tools
    available_units: int = Field(default=0, description="on_hand - reserved + confirmed_inbound")
    daily_velocity: float = Field(default=0.0, description="Selected daily sales rate")
    cover_days: float = Field(default=0.0, description="Days of supply at current velocity")
    target_cover_days: int = Field(default=14, description="Target coverage days")
    at_risk: bool = Field(default=False, description="True if cover_days < target_cover_days")
    stale: bool = Field(default=False, description="True if inventory snapshot is stale (>48h)")
    projected_stockout_date: Optional[str] = Field(
        None, description="ISO-format projected stockout date"
    )

    # Agent reasoning
    reasoning: str = Field(
        ...,
        description="Human-readable explanation of findings. MUST explicitly state how many days stock will last and the projected stockout date.",
    )

    # Error details
    error_code: Optional[str] = Field(None, description="ErrorCode if a tool returned an error")
    error_message: Optional[str] = Field(None, description="Human-readable error detail")


# ============================================================================
# Sourcing Agent Output
# ============================================================================

class SourcingResult(BaseModel):
    """Structured output from the Sourcing Agent.

    The agent finds vendor options, evaluates them against budget and deadline,
    recommends a vendor, and explains the cost-vs-speed trade-off.
    """

    status: Literal["PROPOSAL_READY", "BLOCKED", "NEEDS_INFORMATION"] = Field(
        ...,
        description=(
            "PROPOSAL_READY: a vendor recommendation is ready for proposal drafting. "
            "BLOCKED: no eligible vendors, all expired, or over budget. "
            "NEEDS_INFORMATION: vendor or budget data is missing."
        ),
    )

    # Evidence references
    budget_evidence_id: str = Field(default="", description="Evidence ID from get_budget_position")
    vendor_offer_evidence_id: str = Field(
        default="", description="Evidence ID from list_vendor_offers"
    )

    # Budget facts
    budget_remaining: float = Field(default=0.0, description="Remaining monthly budget")
    total_cost: float = Field(default=0.0, description="Total cost of recommended option")
    is_over_budget: bool = Field(default=False, description="True if total_cost > budget_remaining")

    # Recommendation
    recommended_vendor_id: Optional[str] = Field(None, description="Selected vendor ID")
    recommended_vendor_name: Optional[str] = Field(None, description="Selected vendor name")
    quantity: int = Field(default=0, description="Order quantity")
    unit_price: float = Field(default=0.0, description="Unit price")
    lead_time_days: int = Field(default=0, description="Expected lead time in days")
    strategy_used: str = Field(default="balanced", description="Selection strategy used")

    # Explanations
    trade_off_explanation: str = Field(
        default="",
        description="Plain-English explanation of cost vs speed trade-off",
    )
    all_options_summary: str = Field(
        default="",
        description="MUST be a Markdown bulleted list of the top 3 available vendor options, including proper reasons why each was selected or not.",
    )
    reasoning: str = Field(
        ...,
        description="Human-readable explanation of sourcing decision",
    )

    # Error details
    error_code: Optional[str] = Field(None, description="ErrorCode if a tool returned an error")
    error_message: Optional[str] = Field(None, description="Human-readable error detail")


# ============================================================================
# Review Agent Output
# ============================================================================

class PolicyQuestionAnswer(BaseModel):
    """One policy review question and its evidence-based answer."""

    question: str = Field(..., description="The policy question (e.g., 'Q1: Is the inventory snapshot fresh enough?')")
    answer: str = Field(..., description="Evidence-based answer citing specific data points")
    passed: bool = Field(..., description="True if this question is satisfactorily answered")


class ReviewResult(BaseModel):
    """Structured output from the Review Agent.

    The agent reads policy.md guidance and reviews the proposal against
    all eight policy questions, using tool evidence as authoritative facts.
    """

    status: Literal["APPROVED_FOR_HUMAN", "BLOCKED", "NEEDS_REVISION"] = Field(
        ...,
        description=(
            "APPROVED_FOR_HUMAN: proposal passes all policy checks, ready for human approval. "
            "BLOCKED: unresolvable policy violations (e.g., impossible timing). "
            "NEEDS_REVISION: fixable concerns that the sourcing agent should address."
        ),
    )
    policy_passed: bool = Field(
        ..., description="True if the proposal satisfies all policy review questions"
    )
    policy_violations: List[str] = Field(
        default_factory=list,
        description="Specific policy concerns identified, referencing question numbers",
    )
    policy_questions_answered: List[PolicyQuestionAnswer] = Field(
        default_factory=list,
        description="List of policy review questions with evidence-based answers",
    )
    evidence_complete: bool = Field(
        default=True, description="True if all required evidence IDs are present"
    )
    timing_acceptable: bool = Field(
        default=True, description="True if expected arrival is before projected stockout"
    )
    budget_acceptable: bool = Field(
        default=True, description="True if total cost is within remaining budget"
    )
    reasoning: str = Field(
        ..., description="Plain-English review summary grounded in policy and evidence"
    )
    recommendation_for_approver: str = Field(
        default="",
        description="MUST explicitly include as a Markdown list: why the vendor was selected, why the quantity is what it is, cost breakdown with per unit cost, estimated delivery date, and key policy details.",
    )

