"""Tool-Level Tests

Tests every read-only and write tool against the seeded test database.
Covers happy paths, not-found, stale data, edge cases, and error handling.
"""

from datetime import datetime, timedelta

from domain.tool_models import ErrorCode
from tools.inventory import get_product, get_stock_position, calculate_stock_risk
from tools.sales import get_sales_velocity
from tools.vendors import list_vendor_offers, get_vendor_performance, build_vendor_options
from tools.policy import get_budget_position, get_policy_guidance
from tools.execution import get_pending_purchase_orders


# ============================================================================
# get_product
# ============================================================================

class TestGetProduct:
    """Tests for the get_product tool."""

    def test_valid_sku(self, fresh_db):
        """Returns product record with evidence ID for a valid SKU."""
        result = get_product("AC-001")
        assert result.sku == "AC-001"
        assert result.active is True
        assert result.error is None
        assert result.evidence_id.startswith("product:")
        assert result.name != ""

    def test_unknown_sku(self, fresh_db):
        """Returns NOT_FOUND error for a non-existent SKU."""
        result = get_product("FAKE-SKU-999")
        assert result.error == ErrorCode.NOT_FOUND
        assert result.active is False
        assert result.evidence_id == ""

    def test_empty_sku(self, fresh_db):
        """Returns NOT_FOUND for an empty string SKU."""
        result = get_product("")
        assert result.error == ErrorCode.NOT_FOUND

    def test_retrieved_at_is_recent(self, fresh_db):
        """The retrieved_at timestamp should be within the last few seconds."""
        result = get_product("AC-001")
        delta = datetime.utcnow() - result.retrieved_at
        assert delta.total_seconds() < 5


# ============================================================================
# get_stock_position
# ============================================================================

class TestGetStockPosition:
    """Tests for the get_stock_position tool."""

    def test_valid_position(self, fresh_db):
        """Returns stock snapshot for a valid SKU+warehouse combination."""
        result = get_stock_position("AC-001", "DEL-01")
        assert result.sku == "AC-001"
        assert result.warehouse_id == "DEL-01"
        assert result.on_hand > 0
        assert result.error is None
        assert result.evidence_id.startswith("stock:")

    def test_unknown_warehouse(self, fresh_db):
        """Returns NOT_FOUND for a non-existent warehouse."""
        result = get_stock_position("AC-001", "FAKE-WAREHOUSE")
        assert result.error == ErrorCode.NOT_FOUND

    def test_unknown_sku_at_valid_warehouse(self, fresh_db):
        """Returns NOT_FOUND for a valid warehouse but non-existent SKU."""
        result = get_stock_position("FAKE-SKU", "DEL-01")
        assert result.error == ErrorCode.NOT_FOUND

    def test_snapshot_fields_populated(self, fresh_db):
        """Verifies all snapshot fields are populated for a valid position."""
        result = get_stock_position("AC-003", "DEL-01")
        assert result.snapshot_id != ""
        assert result.captured_at is not None
        assert isinstance(result.on_hand, int)
        assert isinstance(result.reserved, int)
        assert isinstance(result.confirmed_inbound, int)


# ============================================================================
# calculate_stock_risk
# ============================================================================

class TestCalculateStockRisk:
    """Tests for the deterministic calculate_stock_risk function."""

    def test_healthy_stock(self, fresh_db):
        """Stock well above target is not at risk."""
        result = calculate_stock_risk(
            available_units=100,
            daily_velocity=3.0,
            target_cover_days=14,
            snapshot_captured_at=datetime.utcnow() - timedelta(minutes=30)
        )
        assert result.at_risk is False
        assert result.cover_days > 14
        assert result.stale is False

    def test_at_risk_stock(self, fresh_db):
        """Stock below target coverage is at risk."""
        result = calculate_stock_risk(
            available_units=5,
            daily_velocity=3.0,
            target_cover_days=14,
            snapshot_captured_at=datetime.utcnow() - timedelta(minutes=30)
        )
        assert result.at_risk is True
        assert result.cover_days < 14

    def test_stale_snapshot(self, fresh_db):
        """Snapshot older than 48h is marked as stale."""
        import config as config
        original_threshold = config.DATA_FRESHNESS_THRESHOLD_HOURS
        config.DATA_FRESHNESS_THRESHOLD_HOURS = 48  # Use real threshold for this test
        try:
            result = calculate_stock_risk(
                available_units=5,
                daily_velocity=3.0,
                target_cover_days=14,
                snapshot_captured_at=datetime.utcnow() - timedelta(hours=72)
            )
            assert result.stale is True
            # Stale data should NOT be marked at_risk (safety measure)
            assert result.at_risk is False
        finally:
            config.DATA_FRESHNESS_THRESHOLD_HOURS = original_threshold

    def test_zero_velocity(self, fresh_db):
        """Zero velocity defaults to minimum non-zero velocity (0.1)."""
        result = calculate_stock_risk(
            available_units=10,
            daily_velocity=0,
            target_cover_days=14,
            snapshot_captured_at=datetime.utcnow()
        )
        assert result.daily_velocity == 0.1
        assert result.cover_days == 100.0  # 10 / 0.1

    def test_invalid_target_cover_days(self, fresh_db):
        """Target cover days outside [7, 45] returns invalid result."""
        result = calculate_stock_risk(
            available_units=10,
            daily_velocity=3.0,
            target_cover_days=3,  # Below minimum 7
            snapshot_captured_at=datetime.utcnow()
        )
        assert result.stale is True  # Marked as invalid

    def test_projected_stockout_date(self, fresh_db):
        """Projected stockout date is correctly calculated."""
        result = calculate_stock_risk(
            available_units=21,
            daily_velocity=3.0,
            target_cover_days=14,
            snapshot_captured_at=datetime.utcnow()
        )
        assert result.projected_stockout_date is not None
        # 21 units / 3 per day = 7 days from now
        expected = datetime.utcnow() + timedelta(days=7)
        delta = abs((result.projected_stockout_date - expected).total_seconds())
        assert delta < 60  # Within 1 minute


# ============================================================================
# get_sales_velocity
# ============================================================================

class TestGetSalesVelocity:
    """Tests for the get_sales_velocity tool."""

    def test_sufficient_history(self, fresh_db):
        """Returns velocity for a SKU with 30 days of history."""
        result = get_sales_velocity("AC-001", "DEL-01")
        assert result.error is None
        assert result.window_7_days > 0
        assert result.window_30_days > 0
        assert result.evidence_id.startswith("sales:")

    def test_unknown_sku_sales(self, fresh_db):
        """Returns INSUFFICIENT_DATA for a non-existent SKU."""
        result = get_sales_velocity("FAKE-SKU", "DEL-01")
        assert result.error == ErrorCode.INSUFFICIENT_DATA
        assert result.observation_count_7 == 0

    def test_observation_counts(self, fresh_db):
        """Observation counts are populated correctly."""
        result = get_sales_velocity("AC-001", "DEL-01")
        assert result.observation_count_7 >= 3
        assert result.observation_count_30 >= 3


# ============================================================================
# list_vendor_offers
# ============================================================================

class TestListVendorOffers:
    """Tests for the list_vendor_offers tool."""

    def test_multiple_offers(self, fresh_db):
        """AC-001 has multiple valid offers from different vendors."""
        result = list_vendor_offers("AC-001")
        assert result.error is None
        assert len(result.offers) >= 2
        assert result.evidence_id.startswith("offers:")

    def test_offers_sorted_by_price(self, fresh_db):
        """Offers are sorted by unit_price ascending."""
        result = list_vendor_offers("AC-001")
        prices = [o.unit_price for o in result.offers]
        assert prices == sorted(prices)

    def test_expired_offers_excluded(self, fresh_db):
        """AC-006 has an expired offer that should be excluded."""
        result = list_vendor_offers("AC-006")
        assert result.expired_count >= 1
        # Expired offers should NOT appear in the active list
        for offer in result.offers:
            assert offer.valid_until > datetime.utcnow()

    def test_no_offers_for_unknown_sku(self, fresh_db):
        """Non-existent SKU returns empty offers list."""
        result = list_vendor_offers("FAKE-SKU")
        assert len(result.offers) == 0

    def test_offer_evidence_ids(self, fresh_db):
        """Each offer has a unique evidence_id."""
        result = list_vendor_offers("AC-001")
        evidence_ids = [o.evidence_id for o in result.offers]
        assert len(evidence_ids) == len(set(evidence_ids))


# ============================================================================
# get_vendor_performance
# ============================================================================

class TestGetVendorPerformance:
    """Tests for the get_vendor_performance tool."""

    def test_reliable_vendor(self, fresh_db):
        """V-FAST should have high reliability scores."""
        result = get_vendor_performance(["V-FAST"])
        assert result.error is None
        assert len(result.vendors) == 1
        vendor = result.vendors[0]
        assert vendor.on_time_rate >= 0.90
        assert vendor.quality_score >= 0.90

    def test_unreliable_vendor(self, fresh_db):
        """V-UNRELIABLE should have low reliability scores."""
        result = get_vendor_performance(["V-UNRELIABLE"])
        assert len(result.vendors) == 1
        vendor = result.vendors[0]
        assert vendor.on_time_rate < 0.80

    def test_multiple_vendors(self, fresh_db):
        """Can retrieve metrics for multiple vendors at once."""
        result = get_vendor_performance(["V-FAST", "V-CHEAP", "V-BALANCED"])
        assert len(result.vendors) == 3

    def test_unknown_vendor(self, fresh_db):
        """Non-existent vendor ID returns a default 'Unknown' vendor with zero reliability."""
        result = get_vendor_performance(["V-NONEXISTENT"])
        assert len(result.vendors) == 1
        assert result.vendors[0].vendor_name == "Unknown"
        assert result.vendors[0].eligible is False


# ============================================================================
# get_budget_position
# ============================================================================

class TestGetBudgetPosition:
    """Tests for the get_budget_position tool."""

    def test_valid_budget(self, fresh_db):
        """Returns budget with correct remaining calculation."""
        current_month = datetime.utcnow().strftime("%Y-%m")
        result = get_budget_position("DEL-01", current_month)
        assert result.error is None
        assert result.budget_amount == 50000
        assert result.remaining == result.budget_amount - result.spent_amount - result.committed_amount
        assert result.evidence_id.startswith("budget:")

    def test_unknown_warehouse_budget(self, fresh_db):
        """Returns NOT_FOUND for a non-existent warehouse."""
        current_month = datetime.utcnow().strftime("%Y-%m")
        result = get_budget_position("FAKE-WH", current_month)
        assert result.error == ErrorCode.NOT_FOUND

    def test_wrong_month(self, fresh_db):
        """Returns NOT_FOUND for a month with no budget record."""
        result = get_budget_position("DEL-01", "2020-01")
        assert result.error == ErrorCode.NOT_FOUND


# ============================================================================
# get_policy_guidance
# ============================================================================

class TestGetPolicyGuidance:
    """Tests for the get_policy_guidance tool."""

    def test_loads_policy(self, fresh_db):
        """Returns non-empty policy text."""
        result = get_policy_guidance("AC-001", "DEL-01", 14)
        assert result.policy_text != ""
        assert result.policy_version != ""
        assert result.summary != ""


# ============================================================================
# get_pending_purchase_orders
# ============================================================================

class TestGetPendingPurchaseOrders:
    """Tests for the get_pending_purchase_orders tool."""

    def test_finds_pending_order(self, fresh_db):
        """AC-007 has a seeded PENDING purchase order."""
        result = get_pending_purchase_orders("AC-007", "DEL-01")
        assert result["has_pending_orders"] is True
        assert len(result["pending_orders"]) >= 1
        order = result["pending_orders"][0]
        assert order["status"] == "PENDING"
        assert order["expected_arrival_date"] is not None

    def test_no_pending_orders(self, fresh_db):
        """AC-001 has no purchase orders."""
        result = get_pending_purchase_orders("AC-001", "DEL-01")
        assert result["has_pending_orders"] is False
        assert len(result["pending_orders"]) == 0

    def test_unknown_sku_no_orders(self, fresh_db):
        """Non-existent SKU returns no pending orders."""
        result = get_pending_purchase_orders("FAKE-SKU", "DEL-01")
        assert result["has_pending_orders"] is False
        assert result["error"] is None


# ============================================================================
# Additional edge-case & error-handling tests
# ============================================================================

class TestGetProductEdgeCases:
    """Additional edge cases for get_product."""

    def test_inactive_product(self, fresh_db):
        """AC-008 (inactive product) returns INACTIVE error with evidence_id."""
        result = get_product("AC-008")
        assert result.error == ErrorCode.INACTIVE
        assert result.active is False
        assert result.evidence_id.startswith("product:")

    def test_case_sensitive_sku(self, fresh_db):
        """SKU lookup is case-sensitive; lowercase fails."""
        result = get_product("ac-001")
        assert result.error == ErrorCode.NOT_FOUND

    def test_special_characters_sku(self, fresh_db):
        """SKU with SQL injection characters returns NOT_FOUND safely."""
        result = get_product("'; DROP TABLE products; --")
        assert result.error == ErrorCode.NOT_FOUND


class TestCalculateStockRiskEdgeCases:
    """Additional edge cases for calculate_stock_risk."""

    def test_exact_boundary_not_at_risk(self, fresh_db):
        """cover_days == target_cover_days is NOT at_risk."""
        result = calculate_stock_risk(
            available_units=42,
            daily_velocity=3.0,
            target_cover_days=14,
            snapshot_captured_at=datetime.utcnow()
        )
        assert result.cover_days == 14.0
        assert result.at_risk is False

    def test_one_unit_below_threshold(self, fresh_db):
        """cover_days just below target is at_risk."""
        result = calculate_stock_risk(
            available_units=41,
            daily_velocity=3.0,
            target_cover_days=14,
            snapshot_captured_at=datetime.utcnow()
        )
        assert result.cover_days < 14.0
        assert result.at_risk is True

    def test_negative_velocity_treated_as_zero(self, fresh_db):
        """Negative velocity is clamped to minimum 0.1."""
        result = calculate_stock_risk(
            available_units=10,
            daily_velocity=-5.0,
            target_cover_days=14,
            snapshot_captured_at=datetime.utcnow()
        )
        assert result.daily_velocity == 0.1
        assert result.cover_days == 100.0

    def test_very_large_available_units(self, fresh_db):
        """Very large stock produces very high cover_days without error."""
        result = calculate_stock_risk(
            available_units=1_000_000,
            daily_velocity=1.0,
            target_cover_days=14,
            snapshot_captured_at=datetime.utcnow()
        )
        assert result.cover_days == 1_000_000.0
        assert result.at_risk is False

    def test_target_cover_days_max_boundary(self, fresh_db):
        """target_cover_days=45 (max valid) does NOT mark as invalid."""
        result = calculate_stock_risk(
            available_units=50,
            daily_velocity=1.0,
            target_cover_days=45,
            snapshot_captured_at=datetime.utcnow()
        )
        assert result.stale is False
        assert result.cover_days == 50.0

    def test_target_cover_days_above_max(self, fresh_db):
        """target_cover_days=46 (above max) marks as invalid/stale."""
        result = calculate_stock_risk(
            available_units=50,
            daily_velocity=1.0,
            target_cover_days=46,
            snapshot_captured_at=datetime.utcnow()
        )
        assert result.stale is True

    def test_zero_available_units(self, fresh_db):
        """Zero available units should give 0 cover_days and be at_risk."""
        result = calculate_stock_risk(
            available_units=0,
            daily_velocity=3.0,
            target_cover_days=14,
            snapshot_captured_at=datetime.utcnow()
        )
        assert result.cover_days == 0.0
        assert result.at_risk is True


class TestGetSalesVelocityEdgeCases:
    """Additional edge cases for get_sales_velocity."""

    def test_empty_warehouse_returns_insufficient(self, fresh_db):
        """Empty warehouse string returns INSUFFICIENT_DATA."""
        result = get_sales_velocity("AC-001", "")
        assert result.error == ErrorCode.INSUFFICIENT_DATA


class TestListVendorOffersEdgeCases:
    """Additional edge cases for list_vendor_offers."""

    def test_inactive_vendor_excluded(self, fresh_db):
        """Offers from inactive vendors are excluded and counted."""
        result = list_vendor_offers("AC-008")
        # AC-008 has offers from an inactive vendor
        for offer in result.offers:
            assert offer.active is True


class TestGetVendorPerformanceEdgeCases:
    """Additional edge cases for get_vendor_performance."""

    def test_empty_list(self, fresh_db):
        """Empty vendor list returns empty results."""
        result = get_vendor_performance([])
        assert len(result.vendors) == 0
        assert result.error is None

    def test_mixed_known_unknown(self, fresh_db):
        """Mix of known and unknown vendors returns correct counts."""
        result = get_vendor_performance(["V-FAST", "V-NONEXISTENT"])
        assert len(result.vendors) == 2
        known = [v for v in result.vendors if v.vendor_name != "Unknown"]
        unknown = [v for v in result.vendors if v.vendor_name == "Unknown"]
        assert len(known) == 1
        assert len(unknown) == 1


class TestBuildVendorOptions:
    """Tests for the deterministic build_vendor_options function."""

    def test_no_offers_empty_options(self, fresh_db):
        """No offers produce empty options list."""
        from tools.vendors import build_vendor_options
        from domain.tool_models import StockRisk, VendorOfferList, VendorPerformanceList

        risk = StockRisk(
            available_units=10, daily_velocity=2.0, cover_days=5.0,
            projected_stockout_date=datetime.utcnow() + timedelta(days=5),
            target_cover_days=14, at_risk=True, freshness_hours=1.0, stale=False,
        )
        offers = VendorOfferList(
            sku="AC-001", offers=[], retrieved_at=datetime.utcnow(),
            evidence_id="offers:AC-001",
        )
        perf = VendorPerformanceList(vendors=[], retrieved_at=datetime.utcnow())

        result = build_vendor_options(risk, offers, perf)
        assert len(result.options) == 0
        assert len(result.eligible_options) == 0

    def test_options_sorted_by_cost(self, fresh_db):
        """build_vendor_options returns options sorted by total_cost ascending."""
        from tools.vendors import build_vendor_options
        from domain.tool_models import (
            StockRisk, VendorOffer, VendorOfferList,
            VendorPerformance, VendorPerformanceList,
        )
        now = datetime.utcnow()
        risk = StockRisk(
            available_units=10, daily_velocity=2.0, cover_days=5.0,
            projected_stockout_date=now + timedelta(days=5),
            target_cover_days=14, at_risk=True, freshness_hours=1.0, stale=False,
        )
        offer_cheap = VendorOffer(
            offer_id="O1", vendor_id="V-CHEAP", vendor_name="Cheap",
            unit_price=100.0, moq=5, lead_time_days=3,
            valid_until=now + timedelta(days=30), active=True,
            evidence_id="offer:O1",
        )
        offer_expensive = VendorOffer(
            offer_id="O2", vendor_id="V-FAST", vendor_name="Fast",
            unit_price=500.0, moq=5, lead_time_days=1,
            valid_until=now + timedelta(days=30), active=True,
            evidence_id="offer:O2",
        )
        offers = VendorOfferList(
            sku="AC-001", offers=[offer_expensive, offer_cheap],
            retrieved_at=now, evidence_id="offers:AC-001",
        )
        perf = VendorPerformanceList(
            vendors=[
                VendorPerformance(
                    vendor_id="V-CHEAP", vendor_name="Cheap",
                    on_time_rate=0.95, fill_rate=0.95, quality_score=0.95,
                    reliability=0.95, eligible=True, evidence_id="vendor:V-CHEAP",
                ),
                VendorPerformance(
                    vendor_id="V-FAST", vendor_name="Fast",
                    on_time_rate=0.98, fill_rate=0.98, quality_score=0.98,
                    reliability=0.98, eligible=True, evidence_id="vendor:V-FAST",
                ),
            ],
            retrieved_at=now,
        )
        result = build_vendor_options(risk, offers, perf)
        costs = [o.total_cost for o in result.options]
        assert costs == sorted(costs)

    def test_cheapest_and_fastest_flags(self, fresh_db):
        """Cheapest and fastest options are correctly flagged."""
        from tools.vendors import build_vendor_options
        from domain.tool_models import (
            StockRisk, VendorOffer, VendorOfferList,
            VendorPerformance, VendorPerformanceList,
        )
        now = datetime.utcnow()
        risk = StockRisk(
            available_units=10, daily_velocity=2.0, cover_days=5.0,
            projected_stockout_date=now + timedelta(days=5),
            target_cover_days=14, at_risk=True, freshness_hours=1.0, stale=False,
        )
        offer1 = VendorOffer(
            offer_id="O1", vendor_id="V-CHEAP", vendor_name="Cheap",
            unit_price=100.0, moq=5, lead_time_days=7,
            valid_until=now + timedelta(days=30), active=True,
            evidence_id="offer:O1",
        )
        offer2 = VendorOffer(
            offer_id="O2", vendor_id="V-FAST", vendor_name="Fast",
            unit_price=300.0, moq=5, lead_time_days=1,
            valid_until=now + timedelta(days=30), active=True,
            evidence_id="offer:O2",
        )
        offers = VendorOfferList(
            sku="AC-001", offers=[offer1, offer2],
            retrieved_at=now, evidence_id="offers:AC-001",
        )
        perf = VendorPerformanceList(
            vendors=[
                VendorPerformance(
                    vendor_id="V-CHEAP", vendor_name="Cheap",
                    on_time_rate=0.95, fill_rate=0.95, quality_score=0.95,
                    reliability=0.95, eligible=True, evidence_id="vendor:V-CHEAP",
                ),
                VendorPerformance(
                    vendor_id="V-FAST", vendor_name="Fast",
                    on_time_rate=0.98, fill_rate=0.98, quality_score=0.98,
                    reliability=0.98, eligible=True, evidence_id="vendor:V-FAST",
                ),
            ],
            retrieved_at=now,
        )
        result = build_vendor_options(risk, offers, perf)
        cheapest = [o for o in result.options if o.flag_cheapest]
        fastest = [o for o in result.options if o.flag_fastest]
        assert len(cheapest) == 1
        assert len(fastest) == 1
        assert cheapest[0].vendor_id == "V-CHEAP"
        assert fastest[0].vendor_id == "V-FAST"


class TestGetBudgetPositionEdgeCases:
    """Additional edge cases for get_budget_position."""

    def test_remaining_calculation(self, fresh_db):
        """Remaining = budget - spent - committed."""
        from tools.policy import get_budget_position
        current_month = datetime.utcnow().strftime("%Y-%m")
        result = get_budget_position("DEL-01", current_month)
        expected_remaining = result.budget_amount - result.spent_amount - result.committed_amount
        assert result.remaining == expected_remaining
