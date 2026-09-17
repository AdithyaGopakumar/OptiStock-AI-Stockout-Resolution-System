"""Review Agent — LLM node.

Reads policy.md guidance and reviews the assembled proposal against
all eight policy questions.  Decides whether the proposal should proceed
to human approval, be blocked, or be revised.

Tools available: get_policy_guidance (ONLY)
"""

from __future__ import annotations

import json

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from config import MODEL_NAME, OPENAI_API_KEY
from contracts.agent_outputs import ReviewResult
from nodes.audit import audit_node
from state.state import OptiStockState
from tools.langchain_tools import build_langchain_tools


# ── System prompt ──────────────────────────────────────────────────────────

REVIEW_PROMPT = """\
You are the Review Agent in the OptiStock AI stockout resolution system.

## Your Objective
Review the replenishment proposal against the procurement policy guidance.
Decide if the proposal is ready for human approval, needs revision, or should be blocked.

## Process
1. Call get_policy_guidance to load the current policy document.
2. Answer EACH of the 8 policy review questions using ONLY the evidence provided.
3. Determine whether the proposal passes all checks.

## The 8 Policy Questions (answer each explicitly)
Q1. Is the inventory snapshot fresh enough? (threshold: 2 days / 48 hours)
Q2. Is the SKU actually at risk? (check at_risk flag from stock risk)
Q3. Is the sales evidence sufficient? (check observation counts)
Q4. Are there valid vendor options? (check eligible options list)
Q5. Which trade-off is being made? (cost vs speed vs balanced)
Q6. Does the proposed arrival beat the projected stockout date?
Q7. Does the proposed cost fit the remaining monthly budget?
Q8. Is the proposal grounded in evidence IDs? (can every fact be traced?)

## Decision Rules
- All 8 questions answered satisfactorily → status = APPROVED_FOR_HUMAN
- Budget or timing concern that the sourcing agent could fix → status = NEEDS_REVISION
- Unresolvable issue (stale data, no vendors, impossible timing) → status = BLOCKED

## Critical Rules
- NEVER invent numbers. Use ONLY the evidence from the proposal and tool outputs.
- Your policy_questions_answered dict must map Q1-Q8 to specific evidence-based answers.
- Your recommendation_for_approver must explicitly include: why the vendor was selected, why the quantity is what it is, cost breakdown with per unit cost, estimated delivery date, and key policy details. Format it as a clear Markdown list.
- If evidence is missing, say so — do not fill in gaps with assumptions.
"""


# ── Tool filtering ─────────────────────────────────────────────────────────

_REVIEW_TOOL_NAMES = frozenset(["get_policy_guidance"])


def _get_review_tools():
    """Return only the tools this agent is permitted to use."""
    all_tools = build_langchain_tools(include_write_tools=False)
    return [t for t in all_tools if t.name in _REVIEW_TOOL_NAMES]


# ── Node function ──────────────────────────────────────────────────────────

def review_agent_node(state: OptiStockState) -> dict:
    """Run the review agent and return state updates."""
    llm = ChatOpenAI(model=MODEL_NAME, api_key=OPENAI_API_KEY, temperature=0)
    tools = _get_review_tools()
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    # Build rich context from state
    proposal = state.get("proposal", {})
    investigation = state.get("investigation_result", {})
    sourcing = state.get("sourcing_result", {})

    context = (
        f"## Proposal to Review\n"
        f"```json\n{json.dumps(proposal, indent=2, default=str)}\n```\n\n"
        f"## Investigation Evidence\n"
        f"- Available units: {investigation.get('available_units')}\n"
        f"- Daily velocity: {investigation.get('daily_velocity')}\n"
        f"- Cover days: {investigation.get('cover_days')}\n"
        f"- At risk: {investigation.get('at_risk')}\n"
        f"- Stale: {investigation.get('stale')}\n"
        f"- Projected stockout: {investigation.get('projected_stockout_date')}\n"
        f"- Stock evidence: {investigation.get('stock_evidence_id')}\n"
        f"- Sales evidence: {investigation.get('sales_evidence_id')}\n\n"
        f"## Sourcing Evidence\n"
        f"- Recommended vendor: {sourcing.get('recommended_vendor_name')}\n"
        f"- Valid vendor options: {', '.join([opt.get('vendor_name', '') for opt in state.get('vendor_options', {}).get('eligible_options', [])])}\n"
        f"- Total cost: ${sourcing.get('total_cost', 0):.2f}\n"
        f"- Budget remaining: ${sourcing.get('budget_remaining', 0):.2f}\n"
        f"- Over budget: {sourcing.get('is_over_budget')}\n"
        f"- Trade-off: {sourcing.get('trade_off_explanation')}\n"
        f"- Budget evidence: {sourcing.get('budget_evidence_id')}\n\n"
        f"Please call get_policy_guidance for SKU '{state['sku']}', "
        f"warehouse '{state['warehouse_id']}', and target cover {state['target_cover_days']} days, "
        f"then review the proposal against all 8 policy questions."
    )

    messages = [
        SystemMessage(content=REVIEW_PROMPT),
        HumanMessage(content=context),
    ]

    evidence_updates = {}

    # ReAct loop
    max_iterations = 6
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

                if tool_name == "get_policy_guidance":
                    evidence_updates["policy_guidance"] = result if isinstance(result, dict) else result

    # Produce structured output
    structured_llm = ChatOpenAI(
        model=MODEL_NAME, api_key=OPENAI_API_KEY, temperature=0
    ).with_structured_output(ReviewResult)

    messages.append(
        HumanMessage(content="Based on the policy and all evidence, produce your structured ReviewResult now.")
    )

    try:
        result: ReviewResult = structured_llm.invoke(messages)
        result_dict = result.model_dump(mode="json")
    except Exception as e:
        result_dict = ReviewResult(
            status="BLOCKED",
            policy_passed=False,
            reasoning=f"Agent output validation failed: {str(e)}",
        ).model_dump(mode="json")

    # Update proposal policy fields
    proposal_updates = {}
    if state.get("proposal"):
        updated_proposal = dict(state["proposal"])
        updated_proposal["policy_passed"] = result_dict.get("policy_passed", False)
        updated_proposal["policy_violations"] = result_dict.get("policy_violations", [])
        proposal_updates["proposal"] = updated_proposal

    # Log audit
    audit_update = audit_node(
        state,
        actor="agent:review",
        event_type="review_completed",
        payload={
            "status": result_dict.get("status"),
            "policy_passed": result_dict.get("policy_passed"),
            "policy_violations": result_dict.get("policy_violations", []),
            "timing_acceptable": result_dict.get("timing_acceptable"),
            "budget_acceptable": result_dict.get("budget_acceptable"),
        },
    )

    updates = {
        "review_result": result_dict,
        "messages": messages,
        **evidence_updates,
        **proposal_updates,
        **audit_update,
    }

    # Set outcome for terminal statuses
    status = result_dict.get("status")
    if status == "BLOCKED":
        updates["outcome"] = "BLOCKED"
        updates["error_message"] = result_dict.get("reasoning", "Policy review blocked the proposal")

    return updates
