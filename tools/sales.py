"""
Sales Tools
Read-only tools for sales velocity and historical demand.
"""

import sqlite3
from config import DATABASE_PATH
from datetime import datetime, timedelta
from typing import Tuple
from domain.tool_models import (
    SalesVelocity,
    ErrorCode,
)


def _get_db_connection(db_path: str = None):
    if db_path is None:
        db_path = DATABASE_PATH
    """Get database connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_sales_velocity(
    sku: str,
    warehouse_id: str,
    windows: Tuple[int, int] = (7, 30)
) -> SalesVelocity:
    """
    Calculate average daily sales for given time windows.
    
    Returns daily average for each window (e.g., 7-day and 30-day).
    Returns INSUFFICIENT_DATA if history is inadequate (< 3 observations).
    Returns evidence_id and timestamp for all reads.
    
    Args:
        sku: Product SKU
        warehouse_id: Warehouse identifier
        windows: Tuple of day windows to analyze (default: (7, 30))
    
    Returns:
        SalesVelocity with calculated averages or error
    """
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        
        # Calculate date thresholds
        today = datetime.utcnow().date()
        start_7_days = today - timedelta(days=windows[0])
        start_30_days = today - timedelta(days=windows[1])
        
        # Query 7-day window
        cursor.execute(
            """
            SELECT COUNT(*) as count, COALESCE(SUM(units_sold), 0) as total
            FROM sales_daily
            WHERE sku = ? AND warehouse_id = ? AND sale_date > ?
            """,
            (sku, warehouse_id, start_7_days)
        )
        row_7 = cursor.fetchone()
        count_7 = row_7["count"]
        total_7 = row_7["total"]
        avg_7 = total_7 / windows[0] if windows[0] > 0 else 0
        
        # Query 30-day window
        cursor.execute(
            """
            SELECT COUNT(*) as count, COALESCE(SUM(units_sold), 0) as total
            FROM sales_daily
            WHERE sku = ? AND warehouse_id = ? AND sale_date > ?
            """,
            (sku, warehouse_id, start_30_days)
        )
        row_30 = cursor.fetchone()
        count_30 = row_30["count"]
        total_30 = row_30["total"]
        avg_30 = total_30 / windows[1] if windows[1] > 0 else 0
        
        conn.close()
        
        # Check for insufficient data (require at least 3 observations per window)
        if count_7 < 3 or count_30 < 3:
            return SalesVelocity(
                sku=sku,
                warehouse_id=warehouse_id,
                window_7_days=0,
                window_30_days=0,
                observation_count_7=count_7,
                observation_count_30=count_30,
                evidence_id="",
                retrieved_at=datetime.utcnow(),
                error=ErrorCode.INSUFFICIENT_DATA,
            )
        
        return SalesVelocity(
            sku=sku,
            warehouse_id=warehouse_id,
            window_7_days=round(avg_7, 2),
            window_30_days=round(avg_30, 2),
            observation_count_7=count_7,
            observation_count_30=count_30,
            evidence_id=f"sales:{sku}:{warehouse_id}",
            retrieved_at=datetime.utcnow(),
        )
    except Exception as e:
        return SalesVelocity(
            sku=sku,
            warehouse_id=warehouse_id,
            window_7_days=0,
            window_30_days=0,
            observation_count_7=0,
            observation_count_30=0,
            evidence_id="",
            retrieved_at=datetime.utcnow(),
            error=ErrorCode.UNKNOWN_ERROR,
        )
