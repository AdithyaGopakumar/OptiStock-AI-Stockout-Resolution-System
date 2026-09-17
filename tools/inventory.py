"""
Inventory Tools
Read-only tools for product and stock data.
"""

import sqlite3
from config import DATABASE_PATH, DATA_FRESHNESS_THRESHOLD_HOURS
from datetime import datetime, timedelta
from typing import Optional
import uuid
from domain.tool_models import (
    ProductRecord,
    WarehouseRecord,
    StockPosition,
    StockRisk,
    StockRiskInput,
    ErrorCode,
)



def _get_db_connection(db_path: str = None):
    if db_path is None:
        db_path = DATABASE_PATH
    """Get database connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_product(sku: str) -> ProductRecord:
    """
    Look up a product by SKU.
    
    Returns NOT_FOUND if SKU doesn't exist.
    Returns INACTIVE if product is not active.
    """
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT sku, name, category, active FROM products WHERE sku = ?",
            (sku,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return ProductRecord(
                sku=sku,
                name="",
                category="",
                active=False,
                evidence_id="",
                retrieved_at=datetime.utcnow(),
                error=ErrorCode.NOT_FOUND,
            )
        
        if not row["active"]:
            return ProductRecord(
                sku=sku,
                name=row["name"],
                category=row["category"],
                active=False,
                evidence_id=f"product:{sku}",
                retrieved_at=datetime.utcnow(),
                error=ErrorCode.INACTIVE,
            )
        
        return ProductRecord(
            sku=row["sku"],
            name=row["name"],
            category=row["category"],
            active=row["active"],
            evidence_id=f"product:{sku}",
            retrieved_at=datetime.utcnow(),
        )
    except Exception as e:
        return ProductRecord(
            sku=sku,
            name="",
            category="",
            active=False,
            evidence_id="",
            retrieved_at=datetime.utcnow(),
            error=ErrorCode.UNKNOWN_ERROR,
        )


def get_warehouse(warehouse_id: str) -> WarehouseRecord:
    """
    Look up a warehouse by ID.
    
    Returns NOT_FOUND if warehouse doesn't exist.
    """
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        
        # Checking monthly_budgets table as there is no specific warehouses table
        cursor.execute(
            "SELECT warehouse_id FROM monthly_budgets WHERE warehouse_id = ? LIMIT 1",
            (warehouse_id,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return WarehouseRecord(
                warehouse_id=warehouse_id,
                exists=False,
                evidence_id="",
                retrieved_at=datetime.utcnow(),
                error=ErrorCode.NOT_FOUND,
            )
        
        return WarehouseRecord(
            warehouse_id=row["warehouse_id"],
            exists=True,
            evidence_id=f"warehouse:{warehouse_id}",
            retrieved_at=datetime.utcnow(),
        )
    except Exception as e:
        return WarehouseRecord(
            warehouse_id=warehouse_id,
            exists=False,
            evidence_id="",
            retrieved_at=datetime.utcnow(),
            error=ErrorCode.UNKNOWN_ERROR,
        )


def get_stock_position(sku: str, warehouse_id: str) -> StockPosition:
    """
    Get the latest stock position for a SKU at a warehouse.
    
    Returns the most recent inventory snapshot.
    Does NOT determine whether stock is risky (that's calculate_stock_risk).
    """
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT snapshot_id, sku, warehouse_id, on_hand, reserved, 
                   confirmed_inbound, captured_at 
            FROM inventory_snapshots 
            WHERE sku = ? AND warehouse_id = ?
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (sku, warehouse_id)
        )
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return StockPosition(
                snapshot_id="",
                sku=sku,
                warehouse_id=warehouse_id,
                on_hand=0,
                reserved=0,
                confirmed_inbound=0,
                captured_at=datetime.utcnow(),
                evidence_id="",
                retrieved_at=datetime.utcnow(),
                error=ErrorCode.NOT_FOUND,
            )
        
        return StockPosition(
            snapshot_id=row["snapshot_id"],
            sku=row["sku"],
            warehouse_id=row["warehouse_id"],
            on_hand=row["on_hand"],
            reserved=row["reserved"],
            confirmed_inbound=row["confirmed_inbound"],
            captured_at=row["captured_at"],
            evidence_id=f"stock:{row['snapshot_id']}",
            retrieved_at=datetime.utcnow(),
        )
    except Exception as e:
        return StockPosition(
            snapshot_id="",
            sku=sku,
            warehouse_id=warehouse_id,
            on_hand=0,
            reserved=0,
            confirmed_inbound=0,
            captured_at=datetime.utcnow(),
            evidence_id="",
            retrieved_at=datetime.utcnow(),
            error=ErrorCode.UNKNOWN_ERROR,
        )


def calculate_stock_risk(
    available_units: int,
    daily_velocity: float,
    target_cover_days: int,
    snapshot_captured_at: datetime
) -> StockRisk:
    """
    Authoritative deterministic calculation of stock risk.
    
    Does NOT read from database.
    Does NOT use LLM.
    Calculates:
    - available_units (should equal on_hand - reserved + confirmed_inbound)
    - cover_days = available_units / daily_velocity
    - at_risk = cover_days < target_cover_days
    - projected_stockout_date = now + (available_units / daily_velocity) days
    - freshness check against 2-day threshold
    """
    # Validate inputs
    if target_cover_days < 7 or target_cover_days > 45:
        # Return error condition via model
        return StockRisk(
            available_units=available_units,
            daily_velocity=daily_velocity,
            cover_days=0,
            projected_stockout_date=None,
            target_cover_days=target_cover_days,
            at_risk=False,
            freshness_hours=0,
            stale=True,  # Mark as invalid
        )
    
    if daily_velocity <= 0:
        daily_velocity = 0.1  # Minimum non-zero velocity
    
    # Calculate cover days
    cover_days = available_units / daily_velocity if daily_velocity > 0 else float('inf')
    
    # Calculate projected stockout date
    if cover_days < float('inf'):
        projected_stockout_date = datetime.utcnow() + timedelta(days=cover_days)
    else:
        projected_stockout_date = None
    
    # Freshness check
    now = datetime.utcnow()
    freshness_delta = now - snapshot_captured_at
    freshness_hours = freshness_delta.total_seconds() / 3600
    stale = freshness_hours > DATA_FRESHNESS_THRESHOLD_HOURS

    return StockRisk(
        available_units=available_units,
        daily_velocity=daily_velocity,
        cover_days=cover_days,
        projected_stockout_date=projected_stockout_date,
        target_cover_days=target_cover_days,
        at_risk=cover_days < target_cover_days and not stale,
        freshness_hours=freshness_hours,
        stale=stale,
    )
