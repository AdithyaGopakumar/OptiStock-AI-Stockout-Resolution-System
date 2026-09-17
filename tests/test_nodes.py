"""Deterministic Node Tests

Tests every deterministic (non-LLM) node in the workflow graph in isolation.
Covers happy paths, error handling, and edge cases.
"""

from datetime import datetime, timedelta

from state.state import make_initial_state
from nodes.validate_input import validate_input_node
from nodes.draft_proposal import draft_proposal_node
from nodes.prepare_approval import prepare_approval_node
from nodes.revalidate import revalidate_node
from nodes.execute import execute_node
from nodes.audit import audit_node, log_audit_event
from graph import revision_bump_node, terminal_node


# ============================================================================
# validate_input_node
# ============================================================================

class TestValidateInputNode:
    """Tests for the input validation node."""

    def test_valid_input(self, fresh_db):
        """Valid SKU, warehouse, and target_cover_days passes validation."""
        state = make_initial_state("AC-001", "DEL-01", 14)
        result = validate_input_node(state)
        assert "outcome" not in result
        assert result["sku"] == "AC-001"
        assert result["warehouse_id"] == "DEL-01"

    def test_missing_sku(self, fresh_db):
        """None SKU triggers NEEDS_INFORMATION."""
        state = make_initial_state(None, "DEL-01", 14)
        result = validate_input_node(state)
        assert result["outcome"] == "NEEDS_INFORMATION"
        assert "sku" in result["error_message"].lower()

    def test_empty_sku(self, fresh_db):
        """Empty string SKU triggers NEEDS_INFORMATION."""
        state = make_initial_state("", "DEL-01", 14)
        result = validate_input_node(state)
        assert result["outcome"] == "NEEDS_INFORMATION"

    def test_missing_warehouse(self, fresh_db):
        """None warehouse triggers NEEDS_INFORMATION."""
        state = make_initial_state("AC-001", None, 14)
        result = validate_input_node(state)
        assert result["outcome"] == "NEEDS_INFORMATION"
        assert "warehouse_id" in result["error_message"].lower()

    def test_empty_warehouse(self, fresh_db):
        """Empty string warehouse triggers NEEDS_INFORMATION."""
        state = make_initial_state("AC-001", "", 14)
        result = validate_input_node(state)
        assert result["outcome"] == "NEEDS_INFORMATION"

    def test_target_cover_days_too_low(self, fresh_db):
        """target_cover_days below 7 triggers NEEDS_INFORMATION."""
        state = make_initial_state("AC-001", "DEL-01", 3)
        result = validate_input_node(state)
        assert result["outcome"] == "NEEDS_INFORMATION"
        assert "target_cover_days" in result["error_message"]

    def test_target_cover_days_too_high(self, fresh_db):
        """target_cover_days above 45 triggers NEEDS_INFORMATION."""
        state = make_initial_state("AC-001", "DEL-01", 50)
        result = validate_input_node(state)
        assert result["outcome"] == "NEEDS_INFORMATION"
        assert "target_cover_days" in result["error_message"]

    def test_boundary_7_valid(self, fresh_db):
        """target_cover_days = 7 (minimum boundary) should be valid."""
        state = make_initial_state("AC-001", "DEL-01", 7)
        result = validate_input_node(state)
        assert "outcome" not in result

    def test_boundary_45_valid(self, fresh_db):
        """target_cover_days = 45 (maximum boundary) should be valid."""
        state = make_initial_state("AC-001", "DEL-01", 45)
        result = validate_input_node(state)
        assert "outcome" not in result

    def test_whitespace_normalization(self, fresh_db):
        """Leading/trailing whitespace in SKU and warehouse is stripped."""
        state = make_initial_state("  AC-001  ", "  DEL-01  ", 14)
        result = validate_input_node(state)
        assert result["sku"] == "AC-001"
        assert result["warehouse_id"] == "DEL-01"

    def test_whitespace_only_sku(self, fresh_db):
        """SKU that is only whitespace triggers NEEDS_INFORMATION."""
        state = make_initial_state("   ", "DEL-01", 14)
        result = validate_input_node(state)
        assert result["outcome"] == "NEEDS_INFORMATION"


# ============================================================================
# draft_proposal_node
# ============================================================================

class TestDraftProposalNode:
    """Tests for the deterministic proposal drafting node."""

    def _build_state_for_drafting(self, fresh_db):
        """Helper: build a realistic state with all required evidence."""
        now = datetime.utcnow()
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["stock_position"] = {
            "snapshot_id": "INV-AC003-1",
            "sku": "AC-003",
            "warehouse_id": "DEL-01",
            "on_hand": 20,
            "reserved": 5,
            "confirmed_inbound": 0,
            "captured_at": (now - timedelta(minutes=45)).isoformat(),
            "evidence_id": "stock:INV-AC003-1",
            "retrieved_at": now.isoformat(),
        }
        state["sales_velocity"] = {
            "sku": "AC-003",
            "warehouse_id": "DEL-01",
            "window_7_days": 2.0,
            "window_30_days": 2.0,
            "observation_count_7": 7,
            "observation_count_30": 30,
            "evidence_id": "sales:AC-003:DEL-01",
            "retrieved_at": now.isoformat(),
        }
        state["stock_risk"] = {
            "available_units": 15,
            "daily_velocity": 2.0,
            "cover_days": 7.5,
            "projected_stockout_date": (now + timedelta(days=7.5)).isoformat(),
            "target_cover_days": 14,
            "at_risk": True,
            "freshness_hours": 0.75,
            "stale": False,
        }
        state["budget_position"] = {
            "warehouse_id": "DEL-01",
            "month": now.strftime("%Y-%m"),
            "budget_amount": 50000.0,
            "spent_amount": 30000.0,
            "committed_amount": 5000.0,
            "remaining": 15000.0,
            "retrieved_at": now.isoformat(),
            "evidence_id": "budget:DEL-01:" + now.strftime("%Y-%m"),
        }
        state["vendor_recommendation"] = {
            "case_id": state["case_id"],
            "sku": "AC-003",
            "warehouse_id": "DEL-01",
            "strategy": "balanced",
            "recommended_option": {
                "offer_id": "OFFER-003-1",
                "vendor_id": "V-CHEAP",
                "vendor_name": "BudgetVendor Ltd.",
                "unit_price": 180.0,
                "quantity": 28,
                "total_cost": 5040.0,
                "lead_time_days": 7,
                "expected_arrival": (now + timedelta(days=7)).isoformat(),
                "meets_deadline": True,
                "reliable": True,
                "eligible": True,
                "flag_cheapest": True,
                "flag_fastest": False,
            },
            "rationale": "Test rationale",
            "blocked": False,
        }
        return state

    def test_happy_path(self, fresh_db):
        """Successfully drafts a proposal with all required fields."""
        state = self._build_state_for_drafting(fresh_db)
        result = draft_proposal_node(state)
        assert "proposal" in result
        assert "proposal_hash" in result
        assert result["proposal"]["sku"] == "AC-003"
        assert result["proposal"]["proposal_id"] != ""
        assert result["proposal_hash"] != ""

    def test_missing_evidence_blocks(self, fresh_db):
        """Missing required evidence triggers BLOCKED."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        # Don't set any evidence
        result = draft_proposal_node(state)
        assert result["outcome"] == "BLOCKED"
        assert result["error_code"] == "UNKNOWN_ERROR"


# ============================================================================
# revalidate_node
# ============================================================================

class TestRevalidateNode:
    """Tests for the post-approval revalidation node."""

    def _build_approved_state(self, fresh_db):
        """Helper: build a state that has passed through approval."""
        now = datetime.utcnow()
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["proposal"] = {
            "proposal_id": "PROP-TEST",
            "proposal_hash": "testhash123",
            "case_id": state["case_id"],
            "sku": "AC-003",
            "warehouse_id": "DEL-01",
            "stock_evidence_id": "stock:INV-AC003-1",
            "sales_evidence_id": "sales:AC-003:DEL-01",
            "vendor_evidence_ids": ["offer:OFFER-003-1"],
            "budget_evidence_id": "budget:DEL-01",
            "available_units": 15,
            "daily_velocity": 2.0,
            "target_cover_days": 14,
            "projected_stockout_date": (now + timedelta(days=7.5)).isoformat(),
            "recommended_vendor_id": "V-CHEAP",
            "recommended_vendor_name": "BudgetVendor Ltd.",
            "quantity": 28,
            "unit_price": 180.0,
            "total_cost": 5040.0,
            "budget_remaining": 15000.0,
            "expected_arrival": (now + timedelta(days=7)).isoformat(),
            "policy_passed": True,
            "policy_violations": [],
            "all_options_summary": "test",
            "trade_off_explanation": "test",
            "created_at": now.isoformat(),
        }
        state["proposal_hash"] = "testhash123"
        return state

    def test_happy_path(self, fresh_db):
        """Revalidation passes with fresh data."""
        state = self._build_approved_state(fresh_db)
        result = revalidate_node(state)
        assert "revalidation_result" in result
        assert result["revalidation_result"]["all_checks_pass"] is True
        assert "outcome" not in result  # Not blocked

    def test_missing_proposal_blocks(self, fresh_db):
        """Missing proposal in state triggers BLOCKED."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        result = revalidate_node(state)
        assert result["outcome"] == "BLOCKED"
        assert result["error_code"] == "UNKNOWN_ERROR"


# ============================================================================
# execute_node
# ============================================================================

class TestExecuteNode:
    """Tests for the purchase request execution node."""

    def _build_execution_state(self, fresh_db):
        """Helper: build a state ready for execution."""
        now = datetime.utcnow()
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["proposal"] = {
            "proposal_id": "PROP-EXEC",
            "proposal_hash": "exechash",
            "case_id": state["case_id"],
            "sku": "AC-003",
            "warehouse_id": "DEL-01",
            "recommended_vendor_id": "V-CHEAP",
            "recommended_vendor_name": "BudgetVendor Ltd.",
            "quantity": 10,
            "unit_price": 180.0,
            "total_cost": 1800.0,
            "budget_remaining": 15000.0,
            "target_cover_days": 14,
            "projected_stockout_date": (now + timedelta(days=7)).isoformat(),
            "expected_arrival": (now + timedelta(days=5)).isoformat(),
            "stock_evidence_id": "stock:test",
            "sales_evidence_id": "sales:test",
            "vendor_evidence_ids": [],
            "budget_evidence_id": "budget:test",
            "available_units": 15,
            "daily_velocity": 2.0,
            "policy_passed": True,
            "policy_violations": [],
            "all_options_summary": "test",
            "trade_off_explanation": "test",
            "created_at": now.isoformat(),
        }
        state["proposal_hash"] = "exechash"
        state["approved_by"] = "TestApprover"
        return state

    def test_happy_path(self, fresh_db):
        """Successfully creates a purchase request."""
        state = self._build_execution_state(fresh_db)
        result = execute_node(state)
        assert result["outcome"] == "PURCHASE_REQUEST_CREATED"
        assert result["purchase_request"]["created"] is True
        assert result["idempotency_key"] != ""

    def test_idempotency(self, fresh_db):
        """Second execution with same state returns existing request."""
        state = self._build_execution_state(fresh_db)
        res1 = execute_node(state)
        assert res1["purchase_request"]["created"] is True
        res2 = execute_node(state)
        assert res2["purchase_request"]["created"] is False
        assert res2["outcome"] == "PURCHASE_REQUEST_CREATED"

    def test_missing_proposal_blocks(self, fresh_db):
        """Missing proposal triggers BLOCKED."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["approved_by"] = "Test"
        result = execute_node(state)
        assert result["outcome"] == "BLOCKED"
        assert result["error_code"] == "WRITE_FAILED"


# ============================================================================
# revision_bump_node
# ============================================================================

class TestRevisionBumpNode:
    """Tests for the revision counter increment node."""

    def test_increments_from_zero(self, fresh_db):
        """Increments revision_count from 0 to 1."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        result = revision_bump_node(state)
        assert result["revision_count"] == 1

    def test_increments_from_one(self, fresh_db):
        """Increments revision_count from 1 to 2."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["revision_count"] = 1
        result = revision_bump_node(state)
        assert result["revision_count"] == 2


# ============================================================================
# terminal_node
# ============================================================================

class TestTerminalNode:
    """Tests for the terminal node."""

    def test_preserves_existing_outcome(self, fresh_db):
        """If outcome is already set, terminal_node preserves it."""
        state = make_initial_state("AC-001", "DEL-01", 14)
        state["outcome"] = "NO_ACTION"
        result = terminal_node(state)
        assert result["outcome"] == "NO_ACTION"

    def test_infers_no_action(self, fresh_db):
        """Infers NO_ACTION from investigation_result if no outcome set."""
        state = make_initial_state("AC-001", "DEL-01", 14)
        state["investigation_result"] = {"status": "NO_ACTION"}
        result = terminal_node(state)
        assert result["outcome"] == "NO_ACTION"

    def test_infers_blocked_default(self, fresh_db):
        """Defaults to BLOCKED if no outcome and no investigation_result."""
        state = make_initial_state("AC-001", "DEL-01", 14)
        result = terminal_node(state)
        assert result["outcome"] == "BLOCKED"


# ============================================================================
# audit_node
# ============================================================================

class TestAuditNode:
    """Tests for the audit logging helper."""

    def test_logs_event(self, fresh_db):
        """Successfully appends an audit event to the database."""
        state = make_initial_state("AC-001", "DEL-01", 14)
        result = audit_node(state, "test:actor", "test_event", {"key": "value"})
        assert "audit_events" in result
        assert len(result["audit_events"]) == 1
        assert result["audit_events"][0] != ""

    def test_accumulates_events(self, fresh_db):
        """Multiple calls accumulate event IDs."""
        state = make_initial_state("AC-001", "DEL-01", 14)
        r1 = audit_node(state, "test:actor", "event_1", {})
        state["audit_events"] = r1["audit_events"]
        r2 = audit_node(state, "test:actor", "event_2", {})
        assert len(r2["audit_events"]) == 2

    def test_special_characters_in_payload(self, fresh_db):
        """Payload with special characters is stored without error."""
        state = make_initial_state("AC-001", "DEL-01", 14)
        payload = {
            "message": "Cost is $1,500.00 — \"quoted\" & <tag>",
            "unicode": "日本語テスト",
        }
        result = audit_node(state, "test:actor", "special_event", payload)
        assert len(result["audit_events"]) == 1
        assert result["audit_events"][0] != ""


# ============================================================================
# prepare_approval_node
# ============================================================================

class TestPrepareApprovalNode:
    """Tests for the prepare_approval deterministic node."""

    def _build_proposal_state(self, fresh_db):
        """Helper: build a state with a valid proposal from review."""
        from domain.tool_models import ReplenishmentProposal
        now = datetime.utcnow()
        state = make_initial_state("AC-003", "DEL-01", 14)
        proposal = ReplenishmentProposal(
            proposal_id="PROP-PREP",
            proposal_hash="prephash",
            case_id=state["case_id"],
            sku="AC-003",
            warehouse_id="DEL-01",
            stock_evidence_id="stock:INV-AC003-1",
            sales_evidence_id="sales:AC-003:DEL-01",
            vendor_evidence_ids=["offer:OFFER-003-1"],
            budget_evidence_id="budget:DEL-01",
            available_units=15,
            daily_velocity=2.0,
            target_cover_days=14,
            projected_stockout_date=now + timedelta(days=7.5),
            recommended_vendor_id="V-CHEAP",
            recommended_vendor_name="BudgetVendor Ltd.",
            quantity=28,
            unit_price=180.0,
            total_cost=5040.0,
            expected_arrival=now + timedelta(days=7),
            budget_remaining=15000.0,
            policy_passed=True,
            policy_violations=[],
            created_at=now,
        )
        state["proposal"] = proposal.model_dump(mode="json")
        state["proposal_hash"] = "prephash"
        return state

    def test_happy_path(self, fresh_db):
        """Successfully prepares an approval request."""
        state = self._build_proposal_state(fresh_db)
        result = prepare_approval_node(state)
        assert "approval_request" in result
        assert result["outcome"] == "AWAITING_APPROVAL"
        assert result["approval_request"]["approval_required"] is True
        assert result["approval_request"]["case_id"] == state["case_id"]

    def test_missing_proposal_blocks(self, fresh_db):
        """Missing proposal triggers BLOCKED."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        result = prepare_approval_node(state)
        assert result["outcome"] == "BLOCKED"
        assert result["error_code"] == "UNKNOWN_ERROR"


# ============================================================================
# Additional revalidate_node edge cases
# ============================================================================

class TestRevalidateNodeEdgeCases:
    """Additional edge cases for the revalidation node."""

    def _build_approved_state(self, fresh_db):
        """Helper: build a state that has passed through approval."""
        now = datetime.utcnow()
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["proposal"] = {
            "proposal_id": "PROP-REVAL",
            "proposal_hash": "revalhash",
            "case_id": state["case_id"],
            "sku": "AC-003",
            "warehouse_id": "DEL-01",
            "stock_evidence_id": "stock:INV-AC003-1",
            "sales_evidence_id": "sales:AC-003:DEL-01",
            "vendor_evidence_ids": ["offer:OFFER-003-1"],
            "budget_evidence_id": "budget:DEL-01",
            "available_units": 15,
            "daily_velocity": 2.0,
            "target_cover_days": 14,
            "projected_stockout_date": (now + timedelta(days=7.5)).isoformat(),
            "recommended_vendor_id": "V-CHEAP",
            "recommended_vendor_name": "BudgetVendor Ltd.",
            "quantity": 28,
            "unit_price": 180.0,
            "total_cost": 5040.0,
            "expected_arrival": (now + timedelta(days=7)).isoformat(),
            "budget_remaining": 15000.0,
            "policy_passed": True,
            "policy_violations": [],
            "all_options_summary": "test",
            "trade_off_explanation": "test",
            "created_at": now.isoformat(),
        }
        state["proposal_hash"] = "revalhash"
        return state

    def test_revalidation_checks_offer_vendor(self, fresh_db):
        """Revalidation verifies the recommended vendor still has active offers."""
        state = self._build_approved_state(fresh_db)
        # Set a non-existent vendor to simulate expired offers
        state["proposal"]["recommended_vendor_id"] = "V-NONEXISTENT"
        result = revalidate_node(state)
        assert result["revalidation_result"]["offer_valid"] is False
        assert result["revalidation_result"]["all_checks_pass"] is False
        assert result["outcome"] == "BLOCKED"

    def test_revalidation_budget_insufficient(self, fresh_db):
        """Revalidation fails when proposal cost exceeds remaining budget."""
        state = self._build_approved_state(fresh_db)
        # Set extremely high total cost
        state["proposal"]["total_cost"] = 999999.0
        result = revalidate_node(state)
        assert result["revalidation_result"]["budget_valid"] is False
        assert result["outcome"] == "BLOCKED"


# ============================================================================
# Additional execute_node edge cases
# ============================================================================

class TestExecuteNodeEdgeCases:
    """Additional edge cases for the execute node."""

    def test_missing_approved_by_defaults_to_unknown(self, fresh_db):
        """If approved_by is not set, it defaults to 'unknown'."""
        now = datetime.utcnow()
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["proposal"] = {
            "proposal_id": "PROP-NOUSER",
            "proposal_hash": "nouserhash",
            "case_id": state["case_id"],
            "sku": "AC-003",
            "warehouse_id": "DEL-01",
            "stock_evidence_id": "stock:test",
            "sales_evidence_id": "sales:test",
            "vendor_evidence_ids": [],
            "budget_evidence_id": "budget:test",
            "available_units": 15,
            "daily_velocity": 2.0,
            "target_cover_days": 14,
            "projected_stockout_date": (now + timedelta(days=7)).isoformat(),
            "recommended_vendor_id": "V-CHEAP",
            "recommended_vendor_name": "BudgetVendor Ltd.",
            "quantity": 10,
            "unit_price": 100.0,
            "total_cost": 1000.0,
            "expected_arrival": (now + timedelta(days=5)).isoformat(),
            "budget_remaining": 15000.0,
            "policy_passed": True,
            "policy_violations": [],
            "all_options_summary": "test",
            "trade_off_explanation": "test",
            "created_at": now.isoformat(),
        }
        state["proposal_hash"] = "nouserhash"
        # Don't set approved_by
        result = execute_node(state)
        assert result["outcome"] == "PURCHASE_REQUEST_CREATED"


# ============================================================================
# Additional terminal_node edge cases
# ============================================================================

class TestTerminalNodeEdgeCases:
    """Additional edge cases for the terminal node."""

    def test_infers_purchase_request_created(self, fresh_db):
        """Terminal infers PURCHASE_REQUEST_CREATED from purchase_request in state."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["purchase_request"] = {"created": True, "request_id": "PR-123"}
        result = terminal_node(state)
        assert result["outcome"] == "PURCHASE_REQUEST_CREATED"

    def test_needs_revision_falls_to_blocked(self, fresh_db):
        """NEEDS_REVISION outcome is overridden to BLOCKED by terminal node."""
        state = make_initial_state("AC-003", "DEL-01", 14)
        state["outcome"] = "NEEDS_REVISION"
        result = terminal_node(state)
        assert result["outcome"] == "BLOCKED"

    def test_preserves_no_action(self, fresh_db):
        """Terminal preserves NO_ACTION outcome."""
        state = make_initial_state("AC-001", "DEL-01", 14)
        state["outcome"] = "NO_ACTION"
        result = terminal_node(state)
        assert result["outcome"] == "NO_ACTION"

    def test_preserves_needs_information(self, fresh_db):
        """Terminal preserves NEEDS_INFORMATION outcome."""
        state = make_initial_state("AC-001", "DEL-01", 14)
        state["outcome"] = "NEEDS_INFORMATION"
        result = terminal_node(state)
        assert result["outcome"] == "NEEDS_INFORMATION"
