"""Acceptance Scenario Tests

Covers all acceptance scenarios using the OptiStock AI workflow graph.
Agents are mocked to isolate and test the workflow routing, deterministic nodes,
and shared state mechanics.
"""

from langgraph.types import Command

from graph import build_graph
from state.state import make_initial_state
from contracts.agent_outputs import (
    InvestigationResult,
    SourcingResult,
    ReviewResult,
)


def test_scenario_1_healthy_stock(fresh_db, mock_agents):
    """S1: HEALTHY_STOCK - AC-001 ends with NO_ACTION."""
    mock_agents["investigation"].return_value = {
        "investigation_result": InvestigationResult(
            status="NO_ACTION",
            sku="AC-001",
            warehouse_id="DEL-01",
            available_units=40,
            daily_velocity=3.0,
            cover_days=13.3,
            target_cover_days=14,
            at_risk=False,
            stale=False,
            reasoning="Stock is healthy enough.",
        ).model_dump(mode="json"),
        "outcome": "NO_ACTION"
    }

    graph = build_graph()
    state = make_initial_state("AC-001", "DEL-01")
    
    config = {"configurable": {"thread_id": state["case_id"]}}
    
    final_state = graph.invoke(state, config=config)
    
    assert final_state["outcome"] == "NO_ACTION"
    # Sourcing should not be called
    mock_agents["sourcing"].assert_not_called()


def test_scenario_2_missing_data(fresh_db, mock_agents):
    """S2: MISSING_DATA - validate_input blocks empty SKU."""
    graph = build_graph()
    # SKU is None
    state = make_initial_state(None, "DEL-01")
    
    config = {"configurable": {"thread_id": state["case_id"]}}
    
    final_state = graph.invoke(state, config=config)
    
    assert final_state["outcome"] == "NEEDS_INFORMATION"
    assert "error_code" in final_state
    mock_agents["investigation"].assert_not_called()


def test_scenario_3_stale_stock(fresh_db, mock_agents):
    """S3: STALE_STOCK - AC-002 blocked by stale inventory."""
    mock_agents["investigation"].return_value = {
        "investigation_result": InvestigationResult(
            status="BLOCKED",
            sku="AC-002",
            warehouse_id="DEL-01",
            at_risk=False,
            stale=True,
            error_code="DATA_STALE",
            reasoning="Data is older than 48h.",
        ).model_dump(mode="json"),
        "outcome": "BLOCKED",
        "error_code": "DATA_STALE"
    }

    graph = build_graph()
    state = make_initial_state("AC-002", "DEL-01")
    
    config = {"configurable": {"thread_id": state["case_id"]}}
    
    final_state = graph.invoke(state, config=config)
    
    assert final_state["outcome"] == "BLOCKED"
    assert final_state["error_code"] == "DATA_STALE"
    mock_agents["sourcing"].assert_not_called()


def test_scenario_4_cost_vs_speed(fresh_db, mock_agents):
    """S4: COST_VS_SPEED - AC-003 proceeds to human approval."""
    # Uses default happy path mocks from conftest
    graph = build_graph()
    state = make_initial_state("AC-003", "DEL-01")
    config = {"configurable": {"thread_id": state["case_id"]}}
    
    final_state = graph.invoke(state, config=config)
    
    # It should pause at human approval
    current_graph_state = graph.get_state(config)
    assert "human_approval" in current_graph_state.next
    assert final_state["outcome"] == "AWAITING_APPROVAL"


def test_scenario_5_over_budget(fresh_db, mock_agents):
    """S5: OVER_BUDGET - AC-004 blocked by budget."""
    mock_agents["sourcing"].return_value = {
        "sourcing_result": SourcingResult(
            status="BLOCKED",
            budget_remaining=15000.0,
            total_cost=20000.0,
            is_over_budget=True,
            reasoning="Cost exceeds budget.",
        ).model_dump(mode="json"),
        "outcome": "BLOCKED",
        "error_code": "BUDGET_EXCEEDED"
    }

    graph = build_graph()
    state = make_initial_state("AC-004", "DEL-01")
    
    config = {"configurable": {"thread_id": state["case_id"]}}
    
    final_state = graph.invoke(state, config=config)
    
    assert final_state["outcome"] == "BLOCKED"
    mock_agents["review"].assert_not_called()


def test_scenario_6_invalid_output(fresh_db, mock_agents):
    """S6: INVALID_OUTPUT - Agent fails validation retries."""
    # We simulate this by having the agent return BLOCKED due to INVALID_INPUT
    mock_agents["investigation"].return_value = {
        "investigation_result": InvestigationResult(
            status="BLOCKED",
            sku="AC-001",
            warehouse_id="DEL-01",
            error_code="INVALID_INPUT",
            reasoning="Validation failed.",
        ).model_dump(mode="json"),
        "outcome": "BLOCKED",
        "error_code": "INVALID_INPUT"
    }

    graph = build_graph()
    state = make_initial_state("AC-001", "DEL-01")
    
    config = {"configurable": {"thread_id": state["case_id"]}}
    
    final_state = graph.invoke(state, config=config)
    
    assert final_state["outcome"] == "BLOCKED"
    assert final_state["error_code"] == "INVALID_INPUT"


def test_scenario_7_approval_data_change(fresh_db, mock_agents):
    """S7: APPROVAL_DATA_CHANGE - Revalidation fails after approval."""
    graph = build_graph()
    state = make_initial_state("AC-003", "DEL-01")
    config = {"configurable": {"thread_id": state["case_id"]}}
    
    # 1. Run to pause
    graph.invoke(state, config=config)
    
    # 2. Tamper with the state hash before resuming to simulate data change
    current = graph.get_state(config)
    tampered_values = dict(current.values)
    tampered_values["proposal_hash"] = "TAMPERED_HASH"
    graph.update_state(config, tampered_values)
    
    # 3. Resume with approval
    decision = {"decision": "APPROVED", "approver": "Test"}
    final_state = graph.invoke(Command(resume=decision), config=config)
    
    assert final_state["outcome"] == "BLOCKED"
    assert final_state["error_code"] == "DATA_STALE"
    assert not final_state.get("purchase_request")


def test_scenario_8_duplicate_approval(fresh_db, mock_agents):
    """S8: DUPLICATE_APPROVAL - Idempotency prevents duplicates."""
    # Note: testing pure idempotency requires the DB write to happen.
    # We test it by running execute_node twice manually.
    from nodes.execute import execute_node

    state = make_initial_state("AC-003", "DEL-01")
    state["proposal"] = {
        "proposal_id": "PROP-1",
        "proposal_hash": "HASH-1",
        "case_id": state["case_id"],
        "sku": "AC-003",
        "warehouse_id": "DEL-01",
        "stock_evidence_id": "stock:INV-AC003-1",
        "sales_evidence_id": "sales:AC-003:DEL-01",
        "vendor_evidence_ids": ["offer:OFFER-003-1"],
        "budget_evidence_id": "budget:DEL-01:2026-09",
        "available_units": 15,
        "daily_velocity": 2.0,
        "target_cover_days": 14,
        "projected_stockout_date": "2026-01-01T00:00:00Z",
        "recommended_vendor_id": "V-BALANCED",
        "recommended_vendor_name": "Balanced Vendor",
        "quantity": 10,
        "unit_price": 10.0,
        "total_cost": 100.0,
        "expected_arrival": "2026-01-05T00:00:00Z",
        "budget_remaining": 15000.0,
        "policy_passed": True,
        "policy_violations": [],
        "cost_vs_speed_trade_off": "Test",
        "other_options_summary": "Test",
        "created_at": "2026-01-01T00:00:00Z",
    }
    state["proposal_hash"] = "HASH-1"
    state["approved_by"] = "TestUser"

    # First execution
    res1 = execute_node(state)
    assert res1["outcome"] == "PURCHASE_REQUEST_CREATED"
    assert res1["purchase_request"]["created"] is True

    # Second execution (duplicate)
    res2 = execute_node(state)
    assert res2["outcome"] == "PURCHASE_REQUEST_CREATED"
    assert res2["purchase_request"]["created"] is False  # Idempotent hit


def test_scenario_9_human_rejection(fresh_db, mock_agents):
    """S9: HUMAN_REJECTION - Human rejects proposal."""
    graph = build_graph()
    state = make_initial_state("AC-003", "DEL-01")
    config = {"configurable": {"thread_id": state["case_id"]}}
    
    # 1. Run to pause
    graph.invoke(state, config=config)
    
    # 2. Resume with rejection
    decision = {"decision": "REJECTED", "approver": "Test", "comments": "No budget"}
    final_state = graph.invoke(Command(resume=decision), config=config)
    
    assert final_state["outcome"] == "BLOCKED"
    assert "rejected" in final_state["error_message"].lower()


def test_scenario_10_write_failure(fresh_db, mock_agents, mocker):
    """S10: WRITE_FAILURE - DB write error handled gracefully."""
    # Mock the DB write to fail
    mocker.patch("nodes.execute.create_purchase_request", side_effect=Exception("DB Error"))
    from nodes.execute import execute_node
    
    graph = build_graph()
    state = make_initial_state("AC-003", "DEL-01")
    config = {"configurable": {"thread_id": state["case_id"]}}
    
    # 1. Manually craft a state ready for execution
    state["proposal"] = mock_agents["review"].return_value["proposal"]
    state["proposal_hash"] = mock_agents["review"].return_value["proposal_hash"]
    state["approval_decision"] = {"decision": "APPROVED"}
    state["approved_by"] = "TestUser"
    
    final_state = execute_node(state)
    
    assert final_state["outcome"] == "BLOCKED"
    assert final_state["error_code"] == "WRITE_FAILED"


def test_scenario_11_insufficient_sales_history(fresh_db, mock_agents):
    """S11: INSUFFICIENT_SALES_HISTORY - AC-005."""
    mock_agents["investigation"].return_value = {
        "investigation_result": InvestigationResult(
            status="NEEDS_INFORMATION",
            sku="AC-005",
            warehouse_id="DEL-01",
            error_code="INSUFFICIENT_DATA",
            reasoning="Not enough sales history.",
        ).model_dump(mode="json"),
        "outcome": "NEEDS_INFORMATION"
    }

    graph = build_graph()
    state = make_initial_state("AC-005", "DEL-01")
    
    config = {"configurable": {"thread_id": state["case_id"]}}
    
    final_state = graph.invoke(state, config=config)
    
    assert final_state["outcome"] == "NEEDS_INFORMATION"


def test_scenario_12_unreliable_vendor(fresh_db, mock_agents):
    """S12: UNRELIABLE_VENDOR - AC-006 blocked by no eligible vendors."""
    mock_agents["sourcing"].return_value = {
        "sourcing_result": SourcingResult(
            status="BLOCKED",
            reasoning="All vendors unreliable or expired.",
        ).model_dump(mode="json"),
        "outcome": "BLOCKED"
    }

    graph = build_graph()
    state = make_initial_state("AC-006", "DEL-01")
    
    config = {"configurable": {"thread_id": state["case_id"]}}
    
    final_state = graph.invoke(state, config=config)
    
    assert final_state["outcome"] == "BLOCKED"


def test_scenario_13_invalid_sku(fresh_db, mock_agents):
    """S13: INVALID_SKU - Non-existent SKU returns INVALID_INPUT."""
    mock_agents["investigation"].return_value = {
        "investigation_result": InvestigationResult(
            status="INVALID_INPUT",
            sku="FAKE-SKU-999",
            warehouse_id="DEL-01",
            reasoning="Invalid request: SKU 'FAKE-SKU-999' does not exist.",
            error_code="INVALID_INPUT",
            error_message="SKU 'FAKE-SKU-999' does not exist.",
        ).model_dump(mode="json"),
        "outcome": "INVALID_INPUT"
    }

    graph = build_graph()
    state = make_initial_state("FAKE-SKU-999", "DEL-01")
    
    config = {"configurable": {"thread_id": state["case_id"]}}
    
    final_state = graph.invoke(state, config=config)
    
    assert final_state["outcome"] == "INVALID_INPUT"
    mock_agents["sourcing"].assert_not_called()
    mock_agents["review"].assert_not_called()


def test_scenario_14_invalid_warehouse(fresh_db, mock_agents):
    """S14: INVALID_WAREHOUSE - Non-existent warehouse returns INVALID_INPUT."""
    mock_agents["investigation"].return_value = {
        "investigation_result": InvestigationResult(
            status="INVALID_INPUT",
            sku="AC-001",
            warehouse_id="FAKE-WH",
            reasoning="Invalid request: Warehouse 'FAKE-WH' does not exist.",
            error_code="INVALID_INPUT",
            error_message="Warehouse 'FAKE-WH' does not exist.",
        ).model_dump(mode="json"),
        "outcome": "INVALID_INPUT"
    }

    graph = build_graph()
    state = make_initial_state("AC-001", "FAKE-WH")
    
    config = {"configurable": {"thread_id": state["case_id"]}}
    
    final_state = graph.invoke(state, config=config)
    
    assert final_state["outcome"] == "INVALID_INPUT"
    mock_agents["sourcing"].assert_not_called()


def test_scenario_15_duplicate_po(fresh_db, mock_agents):
    """S15: DUPLICATE_PO - Existing pending PO covers the gap, returns NO_ACTION."""
    mock_agents["investigation"].return_value = {
        "investigation_result": InvestigationResult(
            status="NO_ACTION",
            sku="AC-007",
            warehouse_id="DEL-01",
            available_units=5,
            daily_velocity=2.0,
            cover_days=2.5,
            at_risk=False,
            reasoning="Pending purchase order PR-AC007-1 arriving in 2 days covers the gap.",
        ).model_dump(mode="json"),
        "outcome": "NO_ACTION"
    }

    graph = build_graph()
    state = make_initial_state("AC-007", "DEL-01")
    
    config = {"configurable": {"thread_id": state["case_id"]}}
    
    final_state = graph.invoke(state, config=config)
    
    assert final_state["outcome"] == "NO_ACTION"
    mock_agents["sourcing"].assert_not_called()
    mock_agents["review"].assert_not_called()

