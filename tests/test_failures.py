"""Failure Path Tests

Additional tests for failure handling: agent timeouts, missing records,
and bounded revision limits.
"""

from graph import build_graph
from state.state import make_initial_state
from contracts.agent_outputs import ReviewResult


def test_f1_agent_exception(fresh_db, mock_agents):
    """F1: Agent throws an unexpected exception."""
    mock_agents["investigation"].side_effect = Exception("API Timeout")
    
    graph = build_graph()
    state = make_initial_state("AC-003", "DEL-01")
    
    # LangGraph propagates exceptions; in production we'd wrap invocations
    # but for this test we just ensure it fails loudly.
    try:
        config = {"configurable": {"thread_id": state["case_id"]}}
        graph.invoke(state, config=config)
        assert False, "Should have raised exception"
    except Exception as e:
        assert str(e) == "API Timeout"


def test_f2_revision_loop_boundary(fresh_db, mock_agents):
    """F2: Review agent requests revision twice; graph blocks on second attempt."""
    # Make ReviewAgent always request revision
    mock_agents["review"].return_value = {
        "review_result": ReviewResult(
            status="NEEDS_REVISION",
            policy_passed=False,
            reasoning="Need a faster vendor.",
        ).model_dump(mode="json"),
        "outcome": "NEEDS_REVISION"
    }
    
    graph = build_graph()
    state = make_initial_state("AC-003", "DEL-01")
    
    config = {"configurable": {"thread_id": state["case_id"]}}
    final_state = graph.invoke(state, config=config)
    
    # Should be BLOCKED after max revisions (1)
    assert final_state["outcome"] == "BLOCKED"
    assert final_state["revision_count"] == 1


def test_f3_budget_missing(fresh_db, mock_agents):
    """F3: Sourcing fails if budget lookup fails."""
    mock_agents["sourcing"].return_value = {
        "outcome": "NEEDS_INFORMATION",
        "error_code": "NOT_FOUND",
        "error_message": "Budget row missing for this month."
    }
    
    graph = build_graph()
    state = make_initial_state("AC-003", "DEL-01")
    
    config = {"configurable": {"thread_id": state["case_id"]}}
    final_state = graph.invoke(state, config=config)
    
    assert final_state["outcome"] == "NEEDS_INFORMATION"
    assert final_state["error_code"] == "NOT_FOUND"


def test_f4_all_inputs_missing(fresh_db, mock_agents):
    """F4: All inputs missing — validate_input catches before any agent."""
    graph = build_graph()
    state = make_initial_state(None, None)

    config = {"configurable": {"thread_id": state["case_id"]}}
    final_state = graph.invoke(state, config=config)

    assert final_state["outcome"] == "NEEDS_INFORMATION"
    assert "sku" in final_state["error_message"].lower()
    assert "warehouse_id" in final_state["error_message"].lower()
    mock_agents["investigation"].assert_not_called()


def test_f5_investigation_blocked_propagates(fresh_db, mock_agents):
    """F5: Investigation returns BLOCKED — error_code propagates to final state."""
    from contracts.agent_outputs import InvestigationResult

    mock_agents["investigation"].return_value = {
        "investigation_result": InvestigationResult(
            status="BLOCKED",
            sku="AC-002",
            warehouse_id="DEL-01",
            stale=True,
            error_code="DATA_STALE",
            reasoning="Data too old.",
        ).model_dump(mode="json"),
        "outcome": "BLOCKED",
        "error_code": "DATA_STALE",
        "error_message": "Data too old.",
    }

    graph = build_graph()
    state = make_initial_state("AC-002", "DEL-01")

    config = {"configurable": {"thread_id": state["case_id"]}}
    final_state = graph.invoke(state, config=config)

    assert final_state["outcome"] == "BLOCKED"
    assert final_state["error_code"] == "DATA_STALE"
    mock_agents["sourcing"].assert_not_called()


def test_f6_sourcing_needs_information(fresh_db, mock_agents):
    """F6: Sourcing returns NEEDS_INFORMATION — workflow terminates correctly."""
    mock_agents["sourcing"].return_value = {
        "sourcing_result": {"status": "NEEDS_INFORMATION"},
        "outcome": "NEEDS_INFORMATION",
        "error_code": "INSUFFICIENT_DATA",
        "error_message": "Vendor data incomplete.",
    }

    graph = build_graph()
    state = make_initial_state("AC-003", "DEL-01")

    config = {"configurable": {"thread_id": state["case_id"]}}
    final_state = graph.invoke(state, config=config)

    assert final_state["outcome"] == "NEEDS_INFORMATION"
    mock_agents["review"].assert_not_called()


def test_f7_review_blocked(fresh_db, mock_agents):
    """F7: Review returns BLOCKED — proposal does not reach approval."""
    mock_agents["review"].return_value = {
        "review_result": ReviewResult(
            status="BLOCKED",
            policy_passed=False,
            reasoning="Stale data, cannot proceed.",
        ).model_dump(mode="json"),
        "outcome": "BLOCKED",
        "error_message": "Stale data, cannot proceed.",
    }

    graph = build_graph()
    state = make_initial_state("AC-003", "DEL-01")

    config = {"configurable": {"thread_id": state["case_id"]}}
    final_state = graph.invoke(state, config=config)

    assert final_state["outcome"] == "BLOCKED"
