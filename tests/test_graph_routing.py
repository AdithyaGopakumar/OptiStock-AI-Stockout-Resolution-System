"""Graph Routing Tests

Tests the routing functions and conditional edges in isolation.
Also includes integration tests that combine routing with deterministic nodes.
"""

from graph import (
    route_after_validation,
    route_after_investigation,
    route_after_sourcing,
    route_after_review,
    route_after_approval,
    route_after_revalidation,
    route_after_execution,
    build_graph,
)
from state.state import make_initial_state
from contracts.agent_outputs import (
    InvestigationResult,
    SourcingResult,
    ReviewResult,
)


# ============================================================================
# route_after_validation
# ============================================================================

class TestRouteAfterValidation:
    """Tests for the validation routing function."""

    def test_valid_routes_to_investigation(self):
        """Valid input routes to investigation_agent."""
        state = make_initial_state("AC-001", "DEL-01", 14)
        assert route_after_validation(state) == "investigation_agent"

    def test_invalid_routes_to_terminal(self):
        """NEEDS_INFORMATION outcome routes to terminal."""
        state = make_initial_state("AC-001", "DEL-01", 14)
        state["outcome"] = "NEEDS_INFORMATION"
        assert route_after_validation(state) == "terminal"


# ============================================================================
# route_after_investigation
# ============================================================================

class TestRouteAfterInvestigation:
    """Tests for the investigation routing function."""

    def test_at_risk_routes_to_sourcing(self):
        """AT_RISK routes to sourcing_agent."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["investigation_result"] = {"status": "AT_RISK"}
        assert route_after_investigation(state) == "sourcing_agent"

    def test_no_action_routes_to_terminal(self):
        """NO_ACTION routes to terminal."""
        state = make_initial_state("AC-001", "DEL-01", 14)
        state["investigation_result"] = {"status": "NO_ACTION"}
        assert route_after_investigation(state) == "terminal"

    def test_blocked_routes_to_terminal(self):
        """BLOCKED routes to terminal."""
        state = make_initial_state("AC-002", "DEL-01", 14)
        state["investigation_result"] = {"status": "BLOCKED"}
        assert route_after_investigation(state) == "terminal"

    def test_needs_info_routes_to_terminal(self):
        """NEEDS_INFORMATION routes to terminal."""
        state = make_initial_state("AC-005", "DEL-01", 14)
        state["investigation_result"] = {"status": "NEEDS_INFORMATION"}
        assert route_after_investigation(state) == "terminal"

    def test_invalid_input_routes_to_terminal(self):
        """INVALID_INPUT routes to terminal."""
        state = make_initial_state("FAKE", "DEL-01", 14)
        state["investigation_result"] = {"status": "INVALID_INPUT"}
        assert route_after_investigation(state) == "terminal"

    def test_missing_result_defaults_to_terminal(self):
        """Missing investigation_result defaults to BLOCKED → terminal."""
        state = make_initial_state("AC-001", "DEL-01", 14)
        assert route_after_investigation(state) == "terminal"


# ============================================================================
# route_after_sourcing
# ============================================================================

class TestRouteAfterSourcing:
    """Tests for the sourcing routing function."""

    def test_proposal_ready_routes_to_draft(self):
        """PROPOSAL_READY routes to draft_proposal."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["sourcing_result"] = {"status": "PROPOSAL_READY"}
        assert route_after_sourcing(state) == "draft_proposal"

    def test_blocked_routes_to_terminal(self):
        """BLOCKED routes to terminal."""
        state = make_initial_state("AC-004", "DEL-01", 14)
        state["sourcing_result"] = {"status": "BLOCKED"}
        assert route_after_sourcing(state) == "terminal"

    def test_needs_info_routes_to_terminal(self):
        """NEEDS_INFORMATION routes to terminal."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["sourcing_result"] = {"status": "NEEDS_INFORMATION"}
        assert route_after_sourcing(state) == "terminal"


# ============================================================================
# route_after_review
# ============================================================================

class TestRouteAfterReview:
    """Tests for the review routing function."""

    def test_approved_routes_to_prepare_approval(self):
        """APPROVED_FOR_HUMAN routes to prepare_approval."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["review_result"] = {"status": "APPROVED_FOR_HUMAN"}
        assert route_after_review(state) == "prepare_approval"

    def test_needs_revision_first_time(self):
        """NEEDS_REVISION with revision_count=0 routes to revision_bump."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["review_result"] = {"status": "NEEDS_REVISION"}
        state["revision_count"] = 0
        assert route_after_review(state) == "revision_bump"

    def test_needs_revision_at_max(self):
        """NEEDS_REVISION at max revision_count routes to terminal."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["review_result"] = {"status": "NEEDS_REVISION"}
        state["revision_count"] = 1  # MAX_REVISION_COUNT = 1
        assert route_after_review(state) == "terminal"

    def test_blocked_routes_to_terminal(self):
        """BLOCKED routes to terminal."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["review_result"] = {"status": "BLOCKED"}
        assert route_after_review(state) == "terminal"


# ============================================================================
# route_after_approval
# ============================================================================

class TestRouteAfterApproval:
    """Tests for the approval routing function."""

    def test_approved_routes_to_revalidate(self):
        """APPROVED routes to revalidate."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["approval_decision"] = {"decision": "APPROVED"}
        assert route_after_approval(state) == "revalidate"

    def test_rejected_routes_to_terminal(self):
        """REJECTED routes to terminal."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["approval_decision"] = {"decision": "REJECTED"}
        assert route_after_approval(state) == "terminal"

    def test_missing_decision_routes_to_terminal(self):
        """Missing approval_decision routes to terminal."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        assert route_after_approval(state) == "terminal"


# ============================================================================
# route_after_revalidation
# ============================================================================

class TestRouteAfterRevalidation:
    """Tests for the revalidation routing function."""

    def test_all_pass_routes_to_execute(self):
        """all_checks_pass=True routes to execute."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["revalidation_result"] = {"all_checks_pass": True}
        assert route_after_revalidation(state) == "execute"

    def test_failed_routes_to_terminal(self):
        """all_checks_pass=False routes to terminal."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["revalidation_result"] = {"all_checks_pass": False}
        assert route_after_revalidation(state) == "terminal"


# ============================================================================
# route_after_execution
# ============================================================================

class TestRouteAfterExecution:
    """Tests for the execution routing function."""

    def test_always_routes_to_terminal(self):
        """Execution always routes to terminal."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        assert route_after_execution(state) == "terminal"


# ============================================================================
# Graph-level integration tests (with mocked agents)
# ============================================================================

class TestGraphIntegration:
    """Integration tests verifying end-to-end graph execution with mocked agents."""

    def test_invalid_input_skips_all_agents(self, fresh_db, mock_agents):
        """INVALID_INPUT from investigation skips sourcing and review."""
        mock_agents["investigation"].return_value = {
            "investigation_result": InvestigationResult(
                status="INVALID_INPUT",
                sku="FAKE",
                warehouse_id="DEL-01",
                reasoning="SKU not found.",
                error_code="INVALID_INPUT",
            ).model_dump(mode="json"),
            "outcome": "INVALID_INPUT"
        }
        graph = build_graph()
        state = make_initial_state("FAKE", "DEL-01")
        config = {"configurable": {"thread_id": state["case_id"]}}
        final = graph.invoke(state, config=config)
        assert final["outcome"] == "INVALID_INPUT"
        mock_agents["sourcing"].assert_not_called()
        mock_agents["review"].assert_not_called()

    def test_duplicate_po_no_action(self, fresh_db, mock_agents):
        """Investigation returns NO_ACTION when pending PO covers the gap."""
        mock_agents["investigation"].return_value = {
            "investigation_result": InvestigationResult(
                status="NO_ACTION",
                sku="AC-007",
                warehouse_id="DEL-01",
                available_units=5,
                daily_velocity=2.0,
                cover_days=2.5,
                at_risk=False,
                reasoning="Pending PO PR-AC007-1 arrives in 2 days, before stockout.",
            ).model_dump(mode="json"),
            "outcome": "NO_ACTION"
        }
        graph = build_graph()
        state = make_initial_state("AC-007", "DEL-01")
        config = {"configurable": {"thread_id": state["case_id"]}}
        final = graph.invoke(state, config=config)
        assert final["outcome"] == "NO_ACTION"
        mock_agents["sourcing"].assert_not_called()

    def test_revision_loop_bounded(self, fresh_db, mock_agents):
        """Review requesting revision loops back to sourcing exactly once."""
        call_count = {"sourcing": 0}
        original_sourcing_return = mock_agents["sourcing"].return_value

        def sourcing_side_effect(state):
            call_count["sourcing"] += 1
            return original_sourcing_return

        mock_agents["sourcing"].side_effect = sourcing_side_effect
        mock_agents["review"].return_value = {
            "review_result": ReviewResult(
                status="NEEDS_REVISION",
                policy_passed=False,
                reasoning="Choose a faster vendor.",
            ).model_dump(mode="json"),
        }

        graph = build_graph()
        state = make_initial_state("AC-003", "DEL-01")
        config = {"configurable": {"thread_id": state["case_id"]}}
        final = graph.invoke(state, config=config)

        # Sourcing called twice (initial + 1 revision), then terminal
        assert call_count["sourcing"] == 2
        assert final["revision_count"] == 1

    def test_empty_sku_never_reaches_investigation(self, fresh_db, mock_agents):
        """Empty SKU is caught by validate_input before reaching any agent."""
        graph = build_graph()
        state = make_initial_state("", "DEL-01")
        config = {"configurable": {"thread_id": state["case_id"]}}
        final = graph.invoke(state, config=config)
        assert final["outcome"] == "NEEDS_INFORMATION"
        mock_agents["investigation"].assert_not_called()
        mock_agents["sourcing"].assert_not_called()
        mock_agents["review"].assert_not_called()

    def test_sourcing_blocked_skips_review(self, fresh_db, mock_agents):
        """BLOCKED from sourcing skips review and draft entirely."""
        mock_agents["sourcing"].return_value = {
            "sourcing_result": SourcingResult(
                status="BLOCKED",
                reasoning="No eligible vendors.",
            ).model_dump(mode="json"),
            "outcome": "BLOCKED"
        }
        graph = build_graph()
        state = make_initial_state("AC-006", "DEL-01")
        config = {"configurable": {"thread_id": state["case_id"]}}
        final = graph.invoke(state, config=config)
        assert final["outcome"] == "BLOCKED"
        mock_agents["review"].assert_not_called()

    def test_review_blocked_skips_approval(self, fresh_db, mock_agents):
        """BLOCKED from review skips approval entirely."""
        mock_agents["review"].return_value = {
            "review_result": ReviewResult(
                status="BLOCKED",
                policy_passed=False,
                reasoning="Impossible timing constraint.",
            ).model_dump(mode="json"),
            "outcome": "BLOCKED",
            "error_message": "Impossible timing constraint.",
        }
        graph = build_graph()
        state = make_initial_state("AC-003", "DEL-01")
        config = {"configurable": {"thread_id": state["case_id"]}}
        final = graph.invoke(state, config=config)
        assert final["outcome"] == "BLOCKED"

    def test_happy_path_pauses_at_approval(self, fresh_db, mock_agents):
        """Full happy path pauses at human_approval with AWAITING_APPROVAL."""
        # Uses default mocks from conftest (investigation AT_RISK, sourcing PROPOSAL_READY, review APPROVED_FOR_HUMAN)
        graph = build_graph()
        state = make_initial_state("AC-003", "DEL-01")
        config = {"configurable": {"thread_id": state["case_id"]}}

        final = graph.invoke(state, config=config)

        # Graph should pause at human_approval
        current_state = graph.get_state(config)
        assert "human_approval" in current_state.next
        assert final["outcome"] == "AWAITING_APPROVAL"

    def test_sourcing_needs_info_terminates(self, fresh_db, mock_agents):
        """NEEDS_INFORMATION from sourcing routes to terminal correctly."""
        mock_agents["sourcing"].return_value = {
            "sourcing_result": SourcingResult(
                status="NEEDS_INFORMATION",
                reasoning="Budget data missing.",
                error_code="NOT_FOUND",
            ).model_dump(mode="json"),
            "outcome": "NEEDS_INFORMATION",
            "error_code": "NOT_FOUND",
        }
        graph = build_graph()
        state = make_initial_state("AC-003", "DEL-01")
        config = {"configurable": {"thread_id": state["case_id"]}}
        final = graph.invoke(state, config=config)
        assert final["outcome"] == "NEEDS_INFORMATION"
        mock_agents["review"].assert_not_called()
