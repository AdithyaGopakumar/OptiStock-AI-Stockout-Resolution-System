"""Investigation Agent — LLM node.

Investigates one SKU at one warehouse by calling inventory and sales tools,
then running the deterministic stock-risk calculation to decide whether
replenishment action is needed.

Tools available: get_product, get_stock_position, get_sales_velocity,
                 calculate_stock_risk, get_pending_purchase_orders
"""

from __future__ import annotations

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI

from config import MODEL_NAME, OPENAI_API_KEY
from contracts.agent_outputs import InvestigationResult
from nodes.audit import audit_node
from state.state import OptiStockState
from tools.langchain_tools import build_langchain_tools


# ── System prompt ──────────────────────────────────────────────────────────

INVESTIGATION_PROMPT = """\
You are the Investigation Agent in the OptiStock AI stockout resolution system.

## Your Objective
Investigate one SKU at one warehouse. Determine if replenishment action is needed.

## Process
1. Call get_product to verify the SKU exists and is active.
2. Call get_stock_position to get the latest inventory snapshot.
3. Call get_sales_velocity to get 7-day and 30-day sales averages.
4. Call calculate_stock_risk with:
   - available_units = on_hand - reserved + confirmed_inbound
   - daily_velocity = the 7-day sales average (prefer recent data)
   - target_cover_days = from the case input
   - snapshot_captured_at = captured_at from the stock position
5. If at_risk = true, you MUST call get_pending_purchase_orders to check for existing active purchase orders.

## Decision Rules
- If get_product returns NOT_FOUND → status = INVALID_INPUT
- If get_product returns INACTIVE → status = BLOCKED
- If get_sales_velocity returns INSUFFICIENT_DATA → status = NEEDS_INFORMATION
- If calculate_stock_risk returns stale = true → status = BLOCKED (cite DATA_STALE)
- If at_risk = false → status = NO_ACTION
- If at_risk = true AND get_pending_purchase_orders shows a pending order that arrives BEFORE the projected_stockout_date → status = NO_ACTION (cite the incoming pending order in reasoning)
- If at_risk = true AND NO pending order arrives in time → status = AT_RISK

## Critical Rules
- NEVER invent stock levels, sales figures, or dates. Use ONLY tool outputs.
- Always cite evidence_id values from tool outputs in your reasoning.
- If a tool returns an error, report it immediately — do not guess around it.
- Your reasoning field must explain WHY you reached your conclusion using specific numbers. You MUST explicitly state how many days the current stock will last and the projected date when the stock will run out.
"""


# ── Tool filtering ─────────────────────────────────────────────────────────

_INVESTIGATION_TOOL_NAMES = frozenset(
    ["get_product", "get_warehouse", "get_stock_position", "get_sales_velocity", "calculate_stock_risk", "get_pending_purchase_orders"]
)


def _get_investigation_tools():
    """Return only the tools this agent is permitted to use."""
    all_tools = build_langchain_tools(include_write_tools=False)
    return [t for t in all_tools if t.name in _INVESTIGATION_TOOL_NAMES]


# ── Agent constructor ──────────────────────────────────────────────────────

def _build_investigation_agent():
    """Create the investigation agent with bound tools and structured output."""
    llm = ChatOpenAI(
        model=MODEL_NAME,
        api_key=OPENAI_API_KEY,
        temperature=0,
    )
    tools = _get_investigation_tools()
    llm_with_tools = llm.bind_tools(tools)
    return llm_with_tools, tools


# ── Node function ──────────────────────────────────────────────────────────

def investigation_agent_node(state: OptiStockState) -> dict:
    """Run the investigation agent and return state updates.

    Uses the ReAct pattern: the LLM calls tools iteratively until it
    has enough evidence, then produces a structured InvestigationResult.
    """
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
    from tools.inventory import get_product, get_stock_position, get_warehouse
    from domain.tool_models import ErrorCode

    sku = state.get("sku", "")
    warehouse_id = state.get("warehouse_id", "")
    
    # Deterministic pre-flight checks
    prod_record = get_product(sku)
    if prod_record.error == ErrorCode.NOT_FOUND:
        return {
            "investigation_result": {
                "status": "INVALID_INPUT",
                "reasoning": f"Invalid request: Stock with given SKU '{sku}' does not exist.",
                "error_code": "INVALID_INPUT",
                "error_message": f"Stock with given SKU '{sku}' does not exist.",
                "sku": sku,
                "warehouse_id": warehouse_id
            },
            "outcome": "INVALID_INPUT"
        }
    
    warehouse_record = get_warehouse(warehouse_id)
    if warehouse_record.error == ErrorCode.NOT_FOUND:
        return {
            "investigation_result": {
                "status": "INVALID_INPUT",
                "reasoning": f"Invalid request: Warehouse with given ID '{warehouse_id}' does not exist.",
                "error_code": "INVALID_INPUT",
                "error_message": f"Warehouse with given ID '{warehouse_id}' does not exist.",
                "sku": sku,
                "warehouse_id": warehouse_id
            },
            "outcome": "INVALID_INPUT"
        }

    stock_record = get_stock_position(sku, warehouse_id)
    if stock_record.error == ErrorCode.NOT_FOUND:
        return {
            "investigation_result": {
                "status": "INVALID_INPUT",
                "reasoning": f"Invalid request: Inventory record for SKU '{sku}' at warehouse '{warehouse_id}' does not exist.",
                "error_code": "INVALID_INPUT",
                "error_message": f"Inventory record for SKU '{sku}' at warehouse '{warehouse_id}' does not exist.",
                "sku": sku,
                "warehouse_id": warehouse_id
            },
            "outcome": "INVALID_INPUT"
        }

    llm_with_tools, tools = _build_investigation_agent()
    tool_map = {t.name: t for t in tools}

    # Build initial messages
    messages = [
        SystemMessage(content=INVESTIGATION_PROMPT),
        HumanMessage(
            content=(
                f"Investigate SKU '{state['sku']}' at warehouse '{state['warehouse_id']}' "
                f"with target cover of {state['target_cover_days']} days. "
                f"Case ID: {state['case_id']}."
            )
        ),
    ]

    # ReAct loop: let the LLM call tools until it's done
    evidence_updates = {}
    max_iterations = 10
    for _ in range(max_iterations):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        # If no tool calls, the agent is done
        if not response.tool_calls:
            break

        # Execute each tool call
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

                # Store evidence in state
                if tool_name == "get_product":
                    evidence_updates["product"] = result if isinstance(result, dict) else result
                elif tool_name == "get_warehouse":
                    evidence_updates["warehouse"] = result if isinstance(result, dict) else result
                elif tool_name == "get_stock_position":
                    evidence_updates["stock_position"] = result if isinstance(result, dict) else result
                elif tool_name == "get_sales_velocity":
                    evidence_updates["sales_velocity"] = result if isinstance(result, dict) else result
                elif tool_name == "calculate_stock_risk":
                    evidence_updates["stock_risk"] = result if isinstance(result, dict) else result

    # Now ask the LLM to produce the structured output
    structured_llm = ChatOpenAI(
        model=MODEL_NAME,
        api_key=OPENAI_API_KEY,
        temperature=0,
    ).with_structured_output(InvestigationResult)

    messages.append(
        HumanMessage(
            content="Based on all the evidence gathered, produce your structured InvestigationResult now."
        )
    )

    try:
        result: InvestigationResult = structured_llm.invoke(messages)
        result_dict = result.model_dump(mode="json")
    except Exception as e:
        # Validation failed — return BLOCKED
        result_dict = InvestigationResult(
            status="BLOCKED",
            sku=state.get("sku", ""),
            warehouse_id=state.get("warehouse_id", ""),
            reasoning=f"Agent output validation failed: {str(e)}",
            error_code="INVALID_INPUT",
            error_message=str(e),
        ).model_dump(mode="json")

    # Log audit event
    audit_update = audit_node(
        state,
        actor="agent:investigation",
        event_type="investigation_completed",
        payload={
            "status": result_dict.get("status"),
            "at_risk": result_dict.get("at_risk"),
            "cover_days": result_dict.get("cover_days"),
            "stale": result_dict.get("stale"),
        },
    )

    # Build final state updates
    updates = {
        "investigation_result": result_dict,
        "messages": messages,
        **evidence_updates,
        **audit_update,
    }

    # Set outcome for terminal statuses
    status = result_dict.get("status")
    if status in ("NO_ACTION", "BLOCKED", "NEEDS_INFORMATION", "INVALID_INPUT"):
        updates["outcome"] = status
        if status in ("BLOCKED", "INVALID_INPUT"):
            updates["error_code"] = result_dict.get("error_code", "DATA_STALE")
            updates["error_message"] = result_dict.get("error_message", result_dict.get("reasoning", ""))

    return updates
