"""Sourcing Agent — LLM node.

Finds vendor options, evaluates them against budget and deadline,
recommends a vendor, and explains the cost-vs-speed trade-off.

Tools available: list_vendor_offers, get_vendor_performance,
                 build_vendor_options, recommend_vendor_option,
                 get_budget_position
"""

from __future__ import annotations

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from config import MODEL_NAME, OPENAI_API_KEY
from contracts.agent_outputs import SourcingResult
from nodes.audit import audit_node
from state.state import OptiStockState
from tools.langchain_tools import build_langchain_tools


# ── System prompt ──────────────────────────────────────────────────────────

SOURCING_PROMPT = """\
You are the Sourcing Agent in the OptiStock AI stockout resolution system.

## Your Objective
Find and evaluate vendor options for a SKU that has been identified as at-risk.
Recommend a vendor with a clear cost-vs-speed trade-off explanation.

## Process
1. Call list_vendor_offers to get all active, valid offers for the SKU.
2. Extract vendor IDs from the offers and call get_vendor_performance for each.
3. Call build_vendor_options with the stock risk, vendor offers, and performance data.
4. Call get_budget_position for the warehouse and current month.
5. Call recommend_vendor_option with the vendor options and a strategy:
   - Use "balanced" by default
   - Use "fastest" if the projected stockout is very soon (within lead time of cheapest)
   - Use "cheapest" if budget is tight and all options meet the deadline
6. Evaluate whether the recommended option fits the remaining budget.

## Decision Rules
- If no active offers exist → status = BLOCKED (explain why)
- If no eligible vendors (all unreliable or miss deadline) → status = BLOCKED
- If recommended option cost > remaining budget → status = BLOCKED (flag as over-budget)
- If a recommendation exists and fits budget → status = PROPOSAL_READY
- If vendor_performance or budget data has errors → status = NEEDS_INFORMATION

## Output Fields Formatting
- `all_options_summary`: MUST be a Markdown bulleted list of the top 3 available options, including each option's total cost, expected arrival date, and the reason for its selection or rejection.
- `trade_off_explanation`: MUST state the final recommendation and concisely explain the reason for choosing it over the alternatives (do NOT duplicate the full list here). If the cheapest option cannot arrive before stockout, state this explicitly.

## Critical Rules
- NEVER invent prices, lead times, reliability scores, or budget figures.
- Use ONLY tool outputs as authoritative evidence.
- Always cite evidence_id values in your reasoning.
"""


# ── Tool filtering ─────────────────────────────────────────────────────────

_SOURCING_TOOL_NAMES = frozenset(
    [
        "list_vendor_offers",
        "get_vendor_performance",
        "build_vendor_options",
        "recommend_vendor_option",
        "get_budget_position",
    ]
)


def _get_sourcing_tools():
    """Return only the tools this agent is permitted to use."""
    all_tools = build_langchain_tools(include_write_tools=False)
    return [t for t in all_tools if t.name in _SOURCING_TOOL_NAMES]


# ── Node function ──────────────────────────────────────────────────────────

def sourcing_agent_node(state: OptiStockState) -> dict:
    """Run the sourcing agent and return state updates."""
    llm = ChatOpenAI(model=MODEL_NAME, api_key=OPENAI_API_KEY, temperature=0)
    tools = _get_sourcing_tools()
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    # Build context from investigation results
    investigation = state.get("investigation_result", {})
    risk = state.get("stock_risk", {})

    context = (
        f"The Investigation Agent found SKU '{state['sku']}' at warehouse "
        f"'{state['warehouse_id']}' is AT RISK.\n"
        f"- Available units: {investigation.get('available_units', 'unknown')}\n"
        f"- Daily velocity: {investigation.get('daily_velocity', 'unknown')} units/day\n"
        f"- Cover days: {investigation.get('cover_days', 'unknown')}\n"
        f"- Target cover: {state['target_cover_days']} days\n"
        f"- Projected stockout: {investigation.get('projected_stockout_date', 'unknown')}\n"
        f"Case ID: {state['case_id']}.\n"
        f"Current budget month: use the current month in YYYY-MM format.\n"
    )

    # Add revision feedback if this is a re-run
    if state.get("revision_count", 0) > 0 and state.get("review_result"):
        review = state["review_result"]
        context += (
            f"\n⚠️ REVISION REQUEST: The Review Agent flagged these concerns:\n"
            f"- Violations: {review.get('policy_violations', [])}\n"
            f"- Reasoning: {review.get('reasoning', '')}\n"
            f"Please adjust your recommendation to address these issues.\n"
        )

    messages = [
        SystemMessage(content=SOURCING_PROMPT),
        HumanMessage(content=context),
    ]

    # Evidence storage
    evidence_updates = {}

    # ReAct loop
    max_iterations = 12
    for _ in range(max_iterations):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            if tool_name in tool_map:
                result = tool_map[tool_name].invoke(tool_args)
                tool_msg = ToolMessage(
                    content=str(result),
                    tool_call_id=tool_call["id"],
                )
                messages.append(tool_msg)

                # Store evidence
                if tool_name == "list_vendor_offers":
                    evidence_updates["vendor_offers"] = result if isinstance(result, dict) else result
                elif tool_name == "get_vendor_performance":
                    evidence_updates["vendor_performance"] = result if isinstance(result, dict) else result
                elif tool_name == "build_vendor_options":
                    evidence_updates["vendor_options"] = result if isinstance(result, dict) else result
                elif tool_name == "recommend_vendor_option":
                    evidence_updates["vendor_recommendation"] = result if isinstance(result, dict) else result
                elif tool_name == "get_budget_position":
                    evidence_updates["budget_position"] = result if isinstance(result, dict) else result

    # Produce structured output
    structured_llm = ChatOpenAI(
        model=MODEL_NAME, api_key=OPENAI_API_KEY, temperature=0
    ).with_structured_output(SourcingResult)

    messages.append(
        HumanMessage(content="Based on all evidence gathered, produce your structured SourcingResult now.")
    )

    try:
        result: SourcingResult = structured_llm.invoke(messages)
        result_dict = result.model_dump(mode="json")
    except Exception as e:
        result_dict = SourcingResult(
            status="BLOCKED",
            reasoning=f"Agent output validation failed: {str(e)}",
            error_code="INVALID_INPUT",
            error_message=str(e),
        ).model_dump(mode="json")

    # Log audit
    audit_update = audit_node(
        state,
        actor="agent:sourcing",
        event_type="sourcing_completed",
        payload={
            "status": result_dict.get("status"),
            "recommended_vendor_id": result_dict.get("recommended_vendor_id"),
            "total_cost": result_dict.get("total_cost"),
            "is_over_budget": result_dict.get("is_over_budget"),
        },
    )

    updates = {
        "sourcing_result": result_dict,
        "messages": messages,
        **evidence_updates,
        **audit_update,
    }

    # Set outcome for terminal statuses
    status = result_dict.get("status")
    if status in ("BLOCKED", "NEEDS_INFORMATION"):
        updates["outcome"] = status
        updates["error_code"] = result_dict.get("error_code")
        updates["error_message"] = result_dict.get("error_message", result_dict.get("reasoning", ""))

    return updates
