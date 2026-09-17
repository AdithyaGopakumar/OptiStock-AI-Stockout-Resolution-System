"""LangChain-friendly wrappers for the OptiStock AI toolset.

These wrappers keep the existing tool functions as the source of truth,
but expose them as Pydantic-validated ``StructuredTool`` instances so
agents can invoke them with plain dictionaries.
"""

from __future__ import annotations

from typing import Any, Dict, List

from langchain_core.tools import StructuredTool

from domain.tool_models import (
    ApprovalRequestInput,
    AuditEventInput,
    BudgetPositionInput,
    BuildVendorOptionsInput,
    HumanReviewInput,
    ProposalDraftInput,
    PolicyGuidanceInput,
    ProductInput,
    WarehouseInput,
    PendingPurchaseOrdersInput,
    PurchaseRequestInput,
    RevalidationInput,
    SalesInput,
    StockPositionInput,
    StockRiskInput,
    VendorOffersInput,
    VendorPerformanceInput,
    VendorRecommendationInput,
)
from tools.execution import (
    append_audit_event,
    create_purchase_request,
    revalidate_approved_proposal,
    get_pending_purchase_orders,
)
from tools.inventory import calculate_stock_risk, get_product, get_stock_position, get_warehouse
from tools.policy import get_budget_position, get_policy_guidance
from tools.sales import get_sales_velocity
from tools.vendors import build_vendor_options, get_vendor_performance, list_vendor_offers
from tools.workflow import (
    draft_replenishment_proposal,
    prepare_approval_request,
    recommend_vendor_option,
    record_human_review,
)


def _dump(model: Any) -> Dict[str, Any]:
    """Convert a Pydantic model into a JSON-safe dict."""
    return model.model_dump(mode="json")


def get_product_tool(sku: str) -> Dict[str, Any]:
    return _dump(get_product(sku))


def get_warehouse_tool(warehouse_id: str) -> Dict[str, Any]:
    return _dump(get_warehouse(warehouse_id))


def get_stock_position_tool(sku: str, warehouse_id: str) -> Dict[str, Any]:
    return _dump(get_stock_position(sku, warehouse_id))


def calculate_stock_risk_tool(
    available_units: int,
    daily_velocity: float,
    target_cover_days: int,
    snapshot_captured_at: Any,
) -> Dict[str, Any]:
    return _dump(
        calculate_stock_risk(
            available_units=available_units,
            daily_velocity=daily_velocity,
            target_cover_days=target_cover_days,
            snapshot_captured_at=snapshot_captured_at,
        )
    )


def get_sales_velocity_tool(sku: str, warehouse_id: str, windows: tuple = (7, 30)) -> Dict[str, Any]:
    return _dump(get_sales_velocity(sku, warehouse_id, windows))


def list_vendor_offers_tool(sku: str) -> Dict[str, Any]:
    return _dump(list_vendor_offers(sku))


def get_vendor_performance_tool(vendor_ids: List[str]) -> Dict[str, Any]:
    return _dump(get_vendor_performance(vendor_ids))


def build_vendor_options_tool(
    stock_risk: Any,
    vendor_offers: Any,
    vendor_performance: Any,
) -> Dict[str, Any]:
    return _dump(
        build_vendor_options(
            stock_risk=stock_risk,
            vendor_offers=vendor_offers,
            vendor_performance=vendor_performance,
        )
    )


def get_budget_position_tool(warehouse_id: str, budget_month: str) -> Dict[str, Any]:
    return _dump(get_budget_position(warehouse_id, budget_month))


def get_policy_guidance_tool(sku: str, warehouse_id: str, target_cover_days: int) -> Dict[str, Any]:
    return _dump(get_policy_guidance(sku, warehouse_id, target_cover_days))


def revalidate_approved_proposal_tool(proposal_id: str, proposal_hash: str) -> Dict[str, Any]:
    return _dump(revalidate_approved_proposal(proposal_id, proposal_hash))


def create_purchase_request_tool(
    proposal: Any,
    idempotency_key: str,
    approved_by: str,
) -> Dict[str, Any]:
    return _dump(create_purchase_request(proposal, idempotency_key, approved_by))


def append_audit_event_tool(
    case_id: str,
    trace_id: str,
    actor: str,
    event_type: str,
    payload: dict,
) -> Dict[str, Any]:
    return _dump(
        append_audit_event(
            case_id=case_id,
            trace_id=trace_id,
            actor=actor,
            event_type=event_type,
            payload=payload,
        )
    )


def get_pending_purchase_orders_tool(sku: str, warehouse_id: str) -> dict:
    return get_pending_purchase_orders(sku, warehouse_id)


def recommend_vendor_option_tool(
    case_id: str,
    sku: str,
    warehouse_id: str,
    vendor_options: Any,
    strategy: str = "balanced",
) -> Dict[str, Any]:
    input = VendorRecommendationInput(
        case_id=case_id,
        sku=sku,
        warehouse_id=warehouse_id,
        vendor_options=vendor_options,
        strategy=strategy,
    )
    return _dump(
        recommend_vendor_option(
            input.case_id,
            input.sku,
            input.warehouse_id,
            input.vendor_options,
            input.strategy,
        )
    )


def draft_replenishment_proposal_tool(**kwargs: Any) -> Dict[str, Any]:
    return _dump(draft_replenishment_proposal(ProposalDraftInput(**kwargs)))


def prepare_approval_request_tool(proposal: Any) -> Dict[str, Any]:
    input = ApprovalRequestInput(proposal=proposal)
    return _dump(prepare_approval_request(input.proposal))


def record_human_review_tool(
    case_id: str,
    proposal: Any,
    approver: str,
    decision: str,
    comments: str | None = None,
) -> Dict[str, Any]:
    input = HumanReviewInput(
        case_id=case_id,
        proposal=proposal,
        approver=approver,
        decision=decision,
        comments=comments,
    )
    return _dump(
        record_human_review(
            input.case_id,
            input.proposal,
            input.approver,
            input.decision,
            input.comments,
        )
    )


def build_langchain_tools(include_write_tools: bool = False) -> List[StructuredTool]:
    """Create a compact LangChain tool registry for agent nodes."""
    tools: List[StructuredTool] = [
        StructuredTool.from_function(
            func=get_product_tool,
            name="get_product",
            description="Look up a product by SKU and return typed product facts with evidence.",
            args_schema=ProductInput,
        ),
        StructuredTool.from_function(
            func=get_warehouse_tool,
            name="get_warehouse",
            description="Look up a warehouse by ID to verify it exists.",
            args_schema=WarehouseInput,
        ),
        StructuredTool.from_function(
            func=get_pending_purchase_orders_tool,
            name="get_pending_purchase_orders",
            description="Check for existing active (PENDING or CONFIRMED) purchase orders for a SKU at a warehouse.",
            args_schema=PendingPurchaseOrdersInput,
        ),
        StructuredTool.from_function(
            func=get_stock_position_tool,
            name="get_stock_position",
            description="Fetch the latest inventory snapshot for a SKU at one warehouse.",
            args_schema=StockPositionInput,
        ),
        StructuredTool.from_function(
            func=calculate_stock_risk_tool,
            name="calculate_stock_risk",
            description="Run the authoritative stock risk calculation from inventory and sales facts.",
            args_schema=StockRiskInput,
        ),
        StructuredTool.from_function(
            func=get_sales_velocity_tool,
            name="get_sales_velocity",
            description="Get 7-day and 30-day sales velocity for one SKU at one warehouse.",
            args_schema=SalesInput,
        ),
        StructuredTool.from_function(
            func=list_vendor_offers_tool,
            name="list_vendor_offers",
            description="List active, currently valid vendor offers for a SKU.",
            args_schema=VendorOffersInput,
        ),
        StructuredTool.from_function(
            func=get_vendor_performance_tool,
            name="get_vendor_performance",
            description="Return reliability metrics for one or more vendors.",
            args_schema=VendorPerformanceInput,
        ),
        StructuredTool.from_function(
            func=build_vendor_options_tool,
            name="build_vendor_options",
            description="Compare vendor options using deadline, reliability, MOQ, and total cost.",
            args_schema=BuildVendorOptionsInput,
        ),
        StructuredTool.from_function(
            func=recommend_vendor_option_tool,
            name="recommend_vendor_option",
            description="Choose a recommended vendor option and explain the tradeoff in plain English.",
            args_schema=VendorRecommendationInput,
        ),
        StructuredTool.from_function(
            func=get_budget_position_tool,
            name="get_budget_position",
            description="Get the current monthly budget position for a warehouse.",
            args_schema=BudgetPositionInput,
        ),
        StructuredTool.from_function(
            func=get_policy_guidance_tool,
            name="get_policy_guidance",
            description="Load the policy markdown the agent should use to review a proposal.",
            args_schema=PolicyGuidanceInput,
        ),
        StructuredTool.from_function(
            func=draft_replenishment_proposal_tool,
            name="draft_replenishment_proposal",
            description="Build a reviewable replenishment proposal from validated evidence and a recommendation.",
            args_schema=ProposalDraftInput,
        ),
        StructuredTool.from_function(
            func=prepare_approval_request_tool,
            name="prepare_approval_request",
            description="Package the exact proposal version that should be shown to a human approver.",
            args_schema=ApprovalRequestInput,
        ),
        StructuredTool.from_function(
            func=record_human_review_tool,
            name="record_human_review",
            description="Normalize a human approval, rejection, or revision request into workflow state.",
            args_schema=HumanReviewInput,
        ),
        StructuredTool.from_function(
            func=revalidate_approved_proposal_tool,
            name="revalidate_approved_proposal",
            description="Re-check an approved proposal before a deterministic write step.",
            args_schema=RevalidationInput,
        ),
    ]

    if include_write_tools:
        tools.extend(
            [
                StructuredTool.from_function(
                    func=create_purchase_request_tool,
                    name="create_purchase_request",
                    description="Create a purchase request after human approval and successful revalidation.",
                    args_schema=PurchaseRequestInput,
                ),
                StructuredTool.from_function(
                    func=append_audit_event_tool,
                    name="append_audit_event",
                    description="Append a structured audit event for orchestration or review flows.",
                    args_schema=AuditEventInput,
                ),
            ]
        )

    return tools


def build_tool_lookup(include_write_tools: bool = False) -> Dict[str, StructuredTool]:
    """Convenience mapping for ``tool.invoke`` usage in notebooks and demos."""
    return {tool.name: tool for tool in build_langchain_tools(include_write_tools=include_write_tools)}
