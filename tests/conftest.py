"""Pytest configuration and fixtures for OptiStock AI.

Provides a fresh seeded database for each test and mock LLM
utilities to keep tests deterministic and free.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add project root to path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from database.seed import init_db, seed_data

# Use a test-specific database path
TEST_DB_PATH = str(_project_root / "database" / "test_optistock.db")


@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch):
    """Set test environment variables before any tests run."""
    monkeypatch.setenv("DATABASE_PATH", "database/test_optistock.db")
    monkeypatch.setenv("DATA_FRESHNESS_THRESHOLD", "48")
    
    # Reload config to pick up the test DB path
    import config as config
    config.DATABASE_PATH = TEST_DB_PATH
    config.DATA_FRESHNESS_THRESHOLD_HOURS = 100000


@pytest.fixture
def fresh_db():
    """Initialise and seed the test database before each test.
    
    Tears down the database after the test completes.
    """
    init_db(TEST_DB_PATH)
    seed_data(TEST_DB_PATH)
    
    yield TEST_DB_PATH
    
    # Cleanup
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except OSError:
            pass


@pytest.fixture
def mock_llm_responses(mocker):
    """Fixture to mock ChatOpenAI structured outputs for tests.
    
    Returns a dictionary where tests can set the expected return values
    for the different agents.
    """
    responses = {
        "investigation": MagicMock(),
        "sourcing": MagicMock(),
        "review": MagicMock(),
    }
    
    # Create a mock for the structured LLM
    def _mock_with_structured_output(schema):
        mock_instance = MagicMock()
        
        # Decide which response to return based on the schema name
        def _invoke_side_effect(*args, **kwargs):
            schema_name = schema.__name__
            if schema_name == "InvestigationResult":
                return responses["investigation"]
            elif schema_name == "SourcingResult":
                return responses["sourcing"]
            elif schema_name == "ReviewResult":
                return responses["review"]
            return MagicMock()
            
        mock_instance.invoke.side_effect = _invoke_side_effect
        return mock_instance

    # Mock ChatOpenAI
    mock_chat = mocker.patch("langchain_openai.ChatOpenAI")
    
    # We need to mock both standard invoke (for tool calls) and structured output
    # For these tests, we'll bypass the ReAct loop tool calls by making invoke return no tool calls
    # This means the agent will go straight to structured output, but we need to ensure the deterministic
    # nodes still work.
    # Actually, a better approach for integration tests of the graph is to just mock the final structured output
    # and let the real tools run if they are deterministic. But the ReAct loop needs LLM to decide to call tools.
    # Since we want to test the *graph routing* and *deterministic tools*, we can mock the entire agent nodes!
    
    yield responses


@pytest.fixture
def mock_agents(mocker):
    """Mocks the LLM agent nodes entirely for fast graph testing.
    
    This allows us to test the deterministic nodes and the overall graph
    routing without dealing with the complexity of mocking ReAct loops.
    """
    from contracts.agent_outputs import (
        InvestigationResult,
        SourcingResult,
        ReviewResult,
    )
    
    mocks = {
        "investigation": mocker.patch("graph.investigation_agent_node"),
        "sourcing": mocker.patch("graph.sourcing_agent_node"),
        "review": mocker.patch("graph.review_agent_node"),
    }
    
    # Default happy path mocks
    mocks["investigation"].return_value = {
        "investigation_result": InvestigationResult(
            status="AT_RISK",
            sku="AC-003",
            warehouse_id="DEL-01",
            available_units=15,
            daily_velocity=2.0,
            cover_days=7.5,
            target_cover_days=14,
            at_risk=True,
            stale=False,
            reasoning="Mocked investigation",
        ).model_dump(mode="json")
    }
    
    mocks["sourcing"].return_value = {
        "sourcing_result": SourcingResult(
            status="PROPOSAL_READY",
            budget_remaining=15000.0,
            total_cost=1000.0,
            is_over_budget=False,
            recommended_vendor_id="V-BALANCED",
            reasoning="Mocked sourcing",
        ).model_dump(mode="json"),
        "vendor_recommendation": {
            "quantity": 10,
            "total_cost": 1000.0,
            "expected_arrival": "2026-09-10",
            "meets_deadline": True,
            "reliable": True,
            "eligible": True,
            "flag_cheapest": False,
            "flag_fastest": False,
        }
    }
    
    # We need a proper ReplenishmentProposal for prepare_approval
    from domain.tool_models import ReplenishmentProposal
    mock_proposal = ReplenishmentProposal(
        proposal_id="PROP-123",
        proposal_hash="testhash",
        case_id="CASE-123",
        sku="AC-003",
        warehouse_id="DEL-01",
        quantity=10,
        unit_price=100.0,
        total_cost=1000.0,
        budget_remaining=15000.0,
        recommended_vendor_id="V-BALANCED",
        recommended_vendor_name="Balanced Vendor",
        expected_arrival="2026-09-10T00:00:00Z",
        policy_passed=True,
        policy_violations=[],
        all_options_summary="Mock options",
        trade_off_explanation="Mock explanation",
        stock_evidence_id="EV-1",
        sales_evidence_id="EV-2",
        budget_evidence_id="EV-3",
        available_units=15,
        daily_velocity=2.0,
        target_cover_days=14,
        projected_stockout_date="2026-09-07T00:00:00Z",
        created_at="2026-09-01T00:00:00Z",
    )
    
    mocks["review"].return_value = {
        "review_result": ReviewResult(
            status="APPROVED_FOR_HUMAN",
            policy_passed=True,
            reasoning="Mocked review",
        ).model_dump(mode="json"),
        "proposal": mock_proposal.model_dump(mode="json"),
        "proposal_hash": "testhash",
    }
    
    yield mocks
