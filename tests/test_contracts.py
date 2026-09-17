"""Pydantic Contract Tests

Tests every agent output contract to ensure structural correctness,
validation logic, default values, and serialization/deserialization.
"""

import pytest
from datetime import datetime

from contracts.agent_outputs import (
    InvestigationResult,
    SourcingResult,
    ReviewResult,
    PolicyQuestionAnswer,
)


# ============================================================================
# InvestigationResult
# ============================================================================

class TestInvestigationResult:
    """Tests for the InvestigationResult Pydantic model."""

    def test_valid_at_risk(self):
        """AT_RISK status with all fields populated."""
        result = InvestigationResult(
            status="AT_RISK",
            sku="AC-003",
            warehouse_id="DEL-01",
            available_units=15,
            daily_velocity=2.0,
            cover_days=7.5,
            target_cover_days=14,
            at_risk=True,
            stale=False,
            projected_stockout_date="2026-09-18T00:00:00Z",
            product_evidence_id="product:AC-003",
            stock_evidence_id="stock:INV-AC003-1",
            sales_evidence_id="sales:AC-003:DEL-01",
            reasoning="Stock covers 7.5 days, below 14-day target.",
        )
        assert result.status == "AT_RISK"
        assert result.at_risk is True

    def test_valid_no_action(self):
        """NO_ACTION status with healthy stock."""
        result = InvestigationResult(
            status="NO_ACTION",
            sku="AC-001",
            warehouse_id="DEL-01",
            available_units=40,
            daily_velocity=3.0,
            cover_days=13.3,
            at_risk=False,
            reasoning="Stock is healthy.",
        )
        assert result.status == "NO_ACTION"
        assert result.at_risk is False

    def test_valid_invalid_input(self):
        """INVALID_INPUT status for non-existent SKU."""
        result = InvestigationResult(
            status="INVALID_INPUT",
            sku="FAKE",
            warehouse_id="DEL-01",
            reasoning="SKU not found.",
            error_code="INVALID_INPUT",
            error_message="SKU FAKE does not exist.",
        )
        assert result.status == "INVALID_INPUT"

    def test_invalid_status_rejected(self):
        """Invalid status value raises ValidationError."""
        with pytest.raises(Exception):
            InvestigationResult(
                status="INVALID_STATUS",
                sku="AC-001",
                warehouse_id="DEL-01",
                reasoning="test",
            )

    def test_defaults(self):
        """Default values are populated correctly."""
        result = InvestigationResult(
            status="NO_ACTION",
            sku="AC-001",
            warehouse_id="DEL-01",
            reasoning="Test.",
        )
        assert result.available_units == 0
        assert result.daily_velocity == 0.0
        assert result.cover_days == 0.0
        assert result.target_cover_days == 14
        assert result.at_risk is False
        assert result.stale is False
        assert result.error_code is None
        assert result.error_message is None
        assert result.projected_stockout_date is None

    def test_json_serialization(self):
        """Model can be serialized to JSON and back."""
        result = InvestigationResult(
            status="AT_RISK",
            sku="AC-003",
            warehouse_id="DEL-01",
            reasoning="Test.",
        )
        json_dict = result.model_dump(mode="json")
        restored = InvestigationResult.model_validate(json_dict)
        assert restored.status == "AT_RISK"
        assert restored.sku == "AC-003"


# ============================================================================
# SourcingResult
# ============================================================================

class TestSourcingResult:
    """Tests for the SourcingResult Pydantic model."""

    def test_valid_proposal_ready(self):
        """PROPOSAL_READY status with a vendor recommendation."""
        result = SourcingResult(
            status="PROPOSAL_READY",
            budget_remaining=15000.0,
            total_cost=5040.0,
            is_over_budget=False,
            recommended_vendor_id="V-CHEAP",
            recommended_vendor_name="BudgetVendor Ltd.",
            quantity=28,
            unit_price=180.0,
            lead_time_days=7,
            strategy_used="balanced",
            trade_off_explanation="Best balance of cost and speed.",
            all_options_summary="- Option 1\n- Option 2",
            reasoning="Selected BudgetVendor for balanced trade-off.",
        )
        assert result.status == "PROPOSAL_READY"
        assert result.is_over_budget is False

    def test_valid_blocked(self):
        """BLOCKED status for over-budget."""
        result = SourcingResult(
            status="BLOCKED",
            budget_remaining=5000.0,
            total_cost=20000.0,
            is_over_budget=True,
            reasoning="Total cost exceeds budget.",
        )
        assert result.status == "BLOCKED"
        assert result.is_over_budget is True

    def test_invalid_status_rejected(self):
        """Invalid status value raises ValidationError."""
        with pytest.raises(Exception):
            SourcingResult(
                status="READY",
                reasoning="test",
            )

    def test_defaults(self):
        """Default values are populated correctly."""
        result = SourcingResult(
            status="BLOCKED",
            reasoning="Test.",
        )
        assert result.budget_remaining == 0.0
        assert result.total_cost == 0.0
        assert result.is_over_budget is False
        assert result.recommended_vendor_id is None
        assert result.recommended_vendor_name is None
        assert result.quantity == 0
        assert result.unit_price == 0.0
        assert result.lead_time_days == 0
        assert result.strategy_used == "balanced"

    def test_json_round_trip(self):
        """Model survives JSON serialization round-trip."""
        result = SourcingResult(
            status="PROPOSAL_READY",
            reasoning="Test.",
            recommended_vendor_id="V-FAST",
            total_cost=1250.0,
        )
        json_dict = result.model_dump(mode="json")
        restored = SourcingResult.model_validate(json_dict)
        assert restored.recommended_vendor_id == "V-FAST"
        assert restored.total_cost == 1250.0


# ============================================================================
# ReviewResult
# ============================================================================

class TestReviewResult:
    """Tests for the ReviewResult Pydantic model."""

    def test_valid_approved(self):
        """APPROVED_FOR_HUMAN with all policy questions answered."""
        result = ReviewResult(
            status="APPROVED_FOR_HUMAN",
            policy_passed=True,
            policy_questions_answered=[
                PolicyQuestionAnswer(
                    question="Q1: Is snapshot fresh?",
                    answer="Yes, 0.75h old.",
                    passed=True,
                )
            ],
            reasoning="All checks pass.",
            recommendation_for_approver="Recommend approval.",
        )
        assert result.status == "APPROVED_FOR_HUMAN"
        assert result.policy_passed is True

    def test_valid_needs_revision(self):
        """NEEDS_REVISION with policy violations."""
        result = ReviewResult(
            status="NEEDS_REVISION",
            policy_passed=False,
            policy_violations=["Q7: Over budget"],
            reasoning="Budget exceeded, try a cheaper vendor.",
        )
        assert result.status == "NEEDS_REVISION"
        assert len(result.policy_violations) == 1

    def test_valid_blocked(self):
        """BLOCKED with severe violations."""
        result = ReviewResult(
            status="BLOCKED",
            policy_passed=False,
            reasoning="Stale data, cannot proceed.",
        )
        assert result.status == "BLOCKED"

    def test_invalid_status_rejected(self):
        """Invalid status value raises ValidationError."""
        with pytest.raises(Exception):
            ReviewResult(
                status="APPROVED",
                policy_passed=True,
                reasoning="test",
            )

    def test_defaults(self):
        """Default values are populated correctly."""
        result = ReviewResult(
            status="BLOCKED",
            policy_passed=False,
            reasoning="Test.",
        )
        assert result.policy_violations == []
        assert result.policy_questions_answered == []
        assert result.evidence_complete is True
        assert result.timing_acceptable is True
        assert result.budget_acceptable is True
        assert result.recommendation_for_approver == ""

    def test_policy_question_answer(self):
        """PolicyQuestionAnswer model validates correctly."""
        q = PolicyQuestionAnswer(
            question="Q1: Is the inventory snapshot fresh?",
            answer="Yes, captured 0.75h ago (threshold: 48h).",
            passed=True,
        )
        assert q.passed is True
        assert "48h" in q.answer


# ============================================================================
# Additional Contract Edge Cases
# ============================================================================

class TestInvestigationResultEdgeCases:
    """Additional edge cases for InvestigationResult."""

    def test_blocked_with_error_details(self):
        """BLOCKED status with error_code and error_message."""
        result = InvestigationResult(
            status="BLOCKED",
            sku="AC-002",
            warehouse_id="DEL-01",
            stale=True,
            error_code="DATA_STALE",
            error_message="Snapshot is 72h old, threshold is 48h.",
            reasoning="Data is stale, cannot proceed.",
        )
        assert result.status == "BLOCKED"
        assert result.error_code == "DATA_STALE"
        assert result.stale is True

    def test_needs_information_with_insufficient_data(self):
        """NEEDS_INFORMATION status for insufficient sales history."""
        result = InvestigationResult(
            status="NEEDS_INFORMATION",
            sku="AC-005",
            warehouse_id="DEL-01",
            error_code="INSUFFICIENT_DATA",
            reasoning="Only 2 sales observations in 30-day window.",
        )
        assert result.status == "NEEDS_INFORMATION"
        assert result.error_code == "INSUFFICIENT_DATA"

    def test_all_evidence_ids_populated(self):
        """AT_RISK with all three evidence IDs populated."""
        result = InvestigationResult(
            status="AT_RISK",
            sku="AC-003",
            warehouse_id="DEL-01",
            product_evidence_id="product:AC-003",
            stock_evidence_id="stock:INV-AC003-1",
            sales_evidence_id="sales:AC-003:DEL-01",
            at_risk=True,
            available_units=15,
            daily_velocity=2.0,
            cover_days=7.5,
            reasoning="Stock covers 7.5 days, below 14-day target.",
        )
        assert result.product_evidence_id == "product:AC-003"
        assert result.stock_evidence_id != ""
        assert result.sales_evidence_id != ""


class TestSourcingResultEdgeCases:
    """Additional edge cases for SourcingResult."""

    def test_needs_information_status(self):
        """NEEDS_INFORMATION status for missing budget data."""
        result = SourcingResult(
            status="NEEDS_INFORMATION",
            reasoning="Budget data not found.",
            error_code="NOT_FOUND",
            error_message="No budget row for this month.",
        )
        assert result.status == "NEEDS_INFORMATION"
        assert result.error_code == "NOT_FOUND"

    def test_fully_populated_proposal_ready(self):
        """PROPOSAL_READY with every optional field populated."""
        result = SourcingResult(
            status="PROPOSAL_READY",
            budget_remaining=15000.0,
            total_cost=5040.0,
            is_over_budget=False,
            recommended_vendor_id="V-CHEAP",
            recommended_vendor_name="BudgetVendor Ltd.",
            quantity=28,
            unit_price=180.0,
            lead_time_days=7,
            strategy_used="balanced",
            trade_off_explanation="Cheapest reliable option.",
            all_options_summary="- Option 1\n- Option 2\n- Option 3",
            budget_evidence_id="budget:DEL-01:2026-09",
            vendor_offer_evidence_id="offers:AC-003",
            reasoning="Selected BudgetVendor as balanced choice.",
        )
        assert result.recommended_vendor_id == "V-CHEAP"
        assert result.quantity == 28
        assert result.budget_evidence_id == "budget:DEL-01:2026-09"


class TestReviewResultEdgeCases:
    """Additional edge cases for ReviewResult."""

    def test_multiple_policy_violations(self):
        """NEEDS_REVISION with multiple violations."""
        result = ReviewResult(
            status="NEEDS_REVISION",
            policy_passed=False,
            policy_violations=[
                "Q6: Arrival date is after projected stockout",
                "Q7: Cost exceeds remaining budget",
            ],
            reasoning="Two policy violations detected.",
        )
        assert len(result.policy_violations) == 2

    def test_all_policy_questions_answered(self):
        """APPROVED_FOR_HUMAN with all 8 questions answered."""
        questions = [
            PolicyQuestionAnswer(question=f"Q{i}", answer=f"Answer {i}", passed=True)
            for i in range(1, 9)
        ]
        result = ReviewResult(
            status="APPROVED_FOR_HUMAN",
            policy_passed=True,
            policy_questions_answered=questions,
            reasoning="All 8 checks pass.",
            recommendation_for_approver="Recommend approval.",
        )
        assert len(result.policy_questions_answered) == 8
        assert all(q.passed for q in result.policy_questions_answered)

    def test_policy_question_failed(self):
        """PolicyQuestionAnswer with passed=False."""
        q = PolicyQuestionAnswer(
            question="Q7: Does the proposed cost fit the remaining monthly budget?",
            answer="No. Cost is $20,000 but remaining budget is $15,000.",
            passed=False,
        )
        assert q.passed is False
        assert "20,000" in q.answer

    def test_json_round_trip(self):
        """ReviewResult survives JSON round-trip."""
        result = ReviewResult(
            status="APPROVED_FOR_HUMAN",
            policy_passed=True,
            reasoning="Test.",
            policy_violations=["Q7: Budget concern"],
            recommendation_for_approver="Approve with caution.",
        )
        json_dict = result.model_dump(mode="json")
        restored = ReviewResult.model_validate(json_dict)
        assert restored.policy_violations == ["Q7: Budget concern"]
        assert restored.recommendation_for_approver == "Approve with caution."
