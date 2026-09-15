#!/usr/bin/env python
"""
Database Seeder for OptiStock AI
Creates and populates the SQLite database with test data.

Run: python database/seed.py
"""

import sqlite3
from datetime import datetime, timedelta
import os
import sys

# Add project root to sys.path so config can be imported
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DATABASE_PATH


def init_db(db_path=DATABASE_PATH):
    """Initialize database with schema."""
    
    # Remove existing database if it exists
    if os.path.exists(db_path):
        print(f"Removing existing database: {db_path}")
        os.remove(db_path)
    
    # Read and execute schema
    schema_path = os.path.dirname(db_path) + "/schema.sql"
    with open(schema_path, "r") as f:
        schema = f.read()
    
    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.commit()
    conn.close()
    
    print(f"Database initialized: {db_path}")


def seed_data(db_path=DATABASE_PATH):
    """Populate database with test data."""
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # =========================================================================
    # PRODUCTS
    # =========================================================================
    now = datetime.utcnow()

    products = [
        ("AC-001", "Air Conditioner Unit", "Appliances", 1, now - timedelta(days=1)),
        ("AC-002", "Air Conditioner Unit (Stale Data)", "Appliances", 1, now - timedelta(days=6)),
        ("AC-003", "Air Conditioner Unit (Speed Trade-off)", "Appliances", 1, now - timedelta(days=2)),
        ("AC-004", "Air Conditioner Unit (Over Budget)", "Appliances", 1, now - timedelta(days=4)),
        ("AC-005", "Air Conditioner Unit (New SKU)", "Appliances", 1, now - timedelta(days=10)),
        ("AC-006", "Air Conditioner Unit (Unreliable Vendor)", "Appliances", 1, now - timedelta(days=5)),
        ("AC-007", "Air Conditioner Unit (Duplicate PO)", "Appliances", 1, now - timedelta(days=2)),
        ("AC-008", "Air Conditioner Unit (Inactive)", "Appliances", 0, now - timedelta(days=10)),
        ("REF-001", "Refrigerator", "Appliances", 1, now - timedelta(days=30)),
        ("TV-001", "Television", "Electronics", 1, now - timedelta(days=45)),
    ]
    
    for sku, name, category, active, created_at in products:
        cursor.execute(
            "INSERT INTO products (sku, name, category, active, created_at) VALUES (?, ?, ?, ?, ?)",
            (sku, name, category, active, created_at)
        )
    
    # =========================================================================
    # VENDORS
    # =========================================================================
    vendors = [
        # Reliable vendors
        ("V-FAST", "FastShip Inc.", 1, 0.95, 0.98, 0.96, now - timedelta(days=14)),
        ("V-CHEAP", "BudgetVendor Ltd.", 1, 0.92, 0.90, 0.91, now - timedelta(days=9)),
        ("V-BALANCED", "Standard Supplier", 1, 0.93, 0.94, 0.93, now - timedelta(days=21)),
        
        # Unreliable vendors
        ("V-SLOW", "SlowShip Co.", 1, 0.80, 0.85, 0.82, now - timedelta(days=60)),
        ("V-UNRELIABLE", "Shady Vendor LLC", 1, 0.70, 0.75, 0.72, now - timedelta(days=120)),
    ]
    
    for vendor_id, name, active, on_time, fill_rate, quality, created_at in vendors:
        cursor.execute(
            """INSERT INTO vendors (vendor_id, name, active, on_time_rate, 
               fill_rate, quality_score, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (vendor_id, name, active, on_time, fill_rate, quality, created_at)
        )
    
    # =========================================================================
    # INVENTORY SNAPSHOTS
    # =========================================================================
    inventory_data = [
        # AC-001: Healthy stock (40 units available, 14-day velocity = 3 units/day)
        ("INV-AC001-1", "AC-001", "DEL-01", 50, 10, 0, now - timedelta(minutes=30)),
        
        # AC-002: Stale inventory (more than 2 days old)
        ("INV-AC002-1", "AC-002", "DEL-01", 40, 8, 0, now - timedelta(days=3, hours=6)),
        
        # AC-003: Speed trade-off (low stock)
        ("INV-AC003-1", "AC-003", "DEL-01", 20, 5, 0, now - timedelta(minutes=45)),
        
        # AC-004: Over budget
        ("INV-AC004-1", "AC-004", "DEL-01", 15, 3, 0, now - timedelta(minutes=50)),
        
        # AC-005: New SKU
        ("INV-AC005-1", "AC-005", "DEL-01", 100, 10, 0, now - timedelta(minutes=20)),
        
        # AC-006: Unreliable vendor
        ("INV-AC006-1", "AC-006", "DEL-01", 12, 2, 0, now - timedelta(minutes=40)),
        
        # AC-007: Duplicate PO test
        ("INV-AC007-1", "AC-007", "DEL-01", 10, 5, 0, now - timedelta(minutes=10)),
    ]
    
    for snapshot_id, sku, warehouse, on_hand, reserved, inbound, captured in inventory_data:
        cursor.execute(
            """INSERT INTO inventory_snapshots 
               (snapshot_id, sku, warehouse_id, on_hand, reserved, 
                confirmed_inbound, captured_at) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (snapshot_id, sku, warehouse, on_hand, reserved, inbound, captured)
        )
    
    # =========================================================================
    # SALES HISTORY (7+ days to have sufficient data)
    # =========================================================================
    # AC-001: Healthy stock, 3 units/day average
    for i in range(30):
        sale_date = (now - timedelta(days=30-i)).date()
        cursor.execute(
            """INSERT INTO sales_daily (sale_id, sale_date, sku, warehouse_id, units_sold)
               VALUES (?, ?, ?, ?, ?)""",
            (f"SALE-AC001-{i}", sale_date, "AC-001", "DEL-01", 3)
        )
    
    # AC-002: Similar to AC-001
    for i in range(30):
        sale_date = (now - timedelta(days=30-i)).date()
        cursor.execute(
            """INSERT INTO sales_daily (sale_id, sale_date, sku, warehouse_id, units_sold)
               VALUES (?, ?, ?, ?, ?)""",
            (f"SALE-AC002-{i}", sale_date, "AC-002", "DEL-01", 3)
        )
    
    # AC-003: Speed trade-off, 2 units/day
    for i in range(30):
        sale_date = (now - timedelta(days=30-i)).date()
        cursor.execute(
            """INSERT INTO sales_daily (sale_id, sale_date, sku, warehouse_id, units_sold)
               VALUES (?, ?, ?, ?, ?)""",
            (f"SALE-AC003-{i}", sale_date, "AC-003", "DEL-01", 2)
        )
    
    # AC-004: Over budget, 3 units/day
    for i in range(30):
        sale_date = (now - timedelta(days=30-i)).date()
        cursor.execute(
            """INSERT INTO sales_daily (sale_id, sale_date, sku, warehouse_id, units_sold)
               VALUES (?, ?, ?, ?, ?)""",
            (f"SALE-AC004-{i}", sale_date, "AC-004", "DEL-01", 3)
        )
    
    # AC-005: New SKU, only 2 weeks of data
    for i in range(14):
        sale_date = (now - timedelta(days=14-i)).date()
        cursor.execute(
            """INSERT INTO sales_daily (sale_id, sale_date, sku, warehouse_id, units_sold)
               VALUES (?, ?, ?, ?, ?)""",
            (f"SALE-AC005-{i}", sale_date, "AC-005", "DEL-01", 2)
        )
    
    # AC-006: Unreliable vendor
    for i in range(30):
        sale_date = (now - timedelta(days=30-i)).date()
        cursor.execute(
            """INSERT INTO sales_daily (sale_id, sale_date, sku, warehouse_id, units_sold)
               VALUES (?, ?, ?, ?, ?)""",
            (f"SALE-AC006-{i}", sale_date, "AC-006", "DEL-01", 2)
        )
    
    # AC-007: Duplicate PO test
    for i in range(30):
        sale_date = (now - timedelta(days=30-i)).date()
        cursor.execute(
            """INSERT INTO sales_daily (sale_id, sale_date, sku, warehouse_id, units_sold)
               VALUES (?, ?, ?, ?, ?)""",
            (f"SALE-AC007-{i}", sale_date, "AC-007", "DEL-01", 2)
        )
    
    # =========================================================================
    # VENDOR OFFERS
    # =========================================================================
    now_utc = now
    
    offers = [
        # AC-001: Multiple offers
        ("OFFER-001-1", "V-FAST", "AC-001", 250, 5, 2, now_utc + timedelta(days=30)),
        ("OFFER-001-2", "V-CHEAP", "AC-001", 200, 10, 5, now_utc + timedelta(days=30)),
        ("OFFER-001-3", "V-BALANCED", "AC-001", 220, 5, 3, now_utc + timedelta(days=30)),
        
        # AC-002: Valid offers (should work despite stale stock)
        ("OFFER-002-1", "V-FAST", "AC-002", 250, 5, 2, now_utc + timedelta(days=30)),
        ("OFFER-002-2", "V-CHEAP", "AC-002", 200, 10, 5, now_utc + timedelta(days=30)),
        
        # AC-003: Speed vs Cost trade-off
        ("OFFER-003-1", "V-CHEAP", "AC-003", 180, 5, 7, now_utc + timedelta(days=30)),  # Cheap, slow (7 days)
        ("OFFER-003-2", "V-FAST", "AC-003", 300, 3, 2, now_utc + timedelta(days=30)),   # Expensive, fast (2 days)
        
        # AC-004: Over budget (high-cost offers)
        ("OFFER-004-1", "V-FAST", "AC-004", 700, 3, 2, now_utc + timedelta(days=30)),
        ("OFFER-004-2", "V-BALANCED", "AC-004", 650, 5, 3, now_utc + timedelta(days=30)),
        
        # AC-005: Offers exist
        ("OFFER-005-1", "V-CHEAP", "AC-005", 200, 10, 5, now_utc + timedelta(days=30)),
        ("OFFER-005-2", "V-FAST", "AC-005", 250, 5, 2, now_utc + timedelta(days=30)),
        
        # AC-006: Only unreliable vendors or expired
        ("OFFER-006-1", "V-UNRELIABLE", "AC-006", 150, 5, 3, now_utc + timedelta(days=30)),  # Unreliable
        ("OFFER-006-2", "V-SLOW", "AC-006", 160, 5, 4, now_utc + timedelta(days=30)),       # Unreliable
        ("OFFER-006-3", "V-FAST", "AC-006", 250, 5, 2, now_utc - timedelta(days=1)),        # Expired
        
        # AC-007: Duplicate PO test
        ("OFFER-007-1", "V-FAST", "AC-007", 250, 5, 2, now_utc + timedelta(days=30)),
    ]
    
    offer_created_at = {
        "OFFER-001-1": now - timedelta(days=5),
        "OFFER-001-2": now - timedelta(days=5),
        "OFFER-001-3": now - timedelta(days=5),
        "OFFER-002-1": now - timedelta(days=7),
        "OFFER-002-2": now - timedelta(days=7),
        "OFFER-003-1": now - timedelta(days=3),
        "OFFER-003-2": now - timedelta(days=3),
        "OFFER-004-1": now - timedelta(days=2),
        "OFFER-004-2": now - timedelta(days=2),
        "OFFER-005-1": now - timedelta(days=1),
        "OFFER-005-2": now - timedelta(days=1),
        "OFFER-006-1": now - timedelta(days=8),
        "OFFER-006-2": now - timedelta(days=8),
        "OFFER-006-3": now - timedelta(days=10),
        "OFFER-007-1": now - timedelta(days=2),
    }

    for offer_id, vendor_id, sku, price, moq, lead_time, valid_until in offers:
        cursor.execute(
            """INSERT INTO vendor_offers 
               (offer_id, vendor_id, sku, unit_price, moq, lead_time_days, valid_until, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (offer_id, vendor_id, sku, price, moq, lead_time, valid_until, offer_created_at[offer_id])
        )
    
    # =========================================================================
    # MONTHLY BUDGETS
    # =========================================================================
    current_month = now.strftime("%Y-%m")
    
    # Insert only one budget per warehouse/month (unique constraint)
    cursor.execute(
        """INSERT INTO monthly_budgets 
           (budget_id, warehouse_id, month, budget_amount, spent_amount, committed_amount, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("BUDGET-DEL01-2026-08", "DEL-01", current_month, 50000, 30000, 5000, now - timedelta(days=1), now - timedelta(hours=4))
    )
    
    # =========================================================================
    # PURCHASE REQUESTS
    # =========================================================================
    cursor.execute(
        """INSERT INTO purchase_requests 
           (request_id, case_id, vendor_id, sku, warehouse_id, quantity, unit_price, total_cost, status, idempotency_key, expected_arrival_date, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("PR-AC007-1", "case-dummy", "V-FAST", "AC-007", "DEL-01", 50, 250.0, 12500.0, "PENDING", "idem-ac007-1", now + timedelta(days=2), now - timedelta(hours=2))
    )
    
    # =========================================================================
    # COMMIT AND CLOSE
    # =========================================================================
    conn.commit()
    conn.close()
    
    print(f"Database seeded with test data")


if __name__ == "__main__":
    print("OptiStock AI Database Seeder")
    print("=" * 50)
    
    db_path = DATABASE_PATH
    
    try:
        init_db(db_path)
        seed_data(db_path)
        print("\nDatabase ready for testing!")
        print(f"Location: {db_path}")
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
