"""
Vendor Tools
Read-only tools for vendor offers and performance metrics.
"""

import sqlite3
from config import DATABASE_PATH
import math
from datetime import datetime
from typing import List, Optional
from domain.tool_models import (
    VendorOffer,
    VendorOfferList,
    VendorPerformance,
    VendorPerformanceList,
    VendorOption,
    VendorOptionList,
    StockRisk,
    ErrorCode,
)


def _get_db_connection(db_path: str = None):
    if db_path is None:
        db_path = DATABASE_PATH
    """Get database connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def list_vendor_offers(sku: str) -> VendorOfferList:
    """
    List all active, valid vendor offers for a SKU.
    
    Expired offers are excluded but counted.
    Offers from inactive vendors are excluded but counted.
    Returns sorted by unit_price (ascending).
    """
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        
        now = datetime.utcnow()
        
        # Get all offers, regardless of status (for counting)
        cursor.execute(
            """
            SELECT vo.offer_id, vo.vendor_id, v.name, vo.unit_price,
                   vo.moq, vo.lead_time_days, vo.valid_until, v.active
            FROM vendor_offers vo
            JOIN vendors v ON vo.vendor_id = v.vendor_id
            WHERE vo.sku = ?
            ORDER BY vo.unit_price ASC
            """,
            (sku,)
        )
        all_rows = cursor.fetchall()
        conn.close()
        
        offers = []
        expired_count = 0
        inactive_count = 0
        
        for row in all_rows:
            # Check if expired
            valid_until = datetime.fromisoformat(row["valid_until"])
            if valid_until < now:
                expired_count += 1
                continue
            
            # Check if vendor is inactive
            if not row["active"]:
                inactive_count += 1
                continue
            
            # Add active, valid offer
            offers.append(VendorOffer(
                offer_id=row["offer_id"],
                vendor_id=row["vendor_id"],
                vendor_name=row["name"],
                unit_price=row["unit_price"],
                moq=row["moq"],
                lead_time_days=row["lead_time_days"],
                valid_until=valid_until,
                active=True,
                evidence_id=f"offer:{row['offer_id']}",
            ))
        
        return VendorOfferList(
            sku=sku,
            offers=offers,
            expired_count=expired_count,
            inactive_count=inactive_count,
            retrieved_at=datetime.utcnow(),
            evidence_id=f"offers:{sku}",
        )
    except Exception as e:
        return VendorOfferList(
            sku=sku,
            offers=[],
            expired_count=0,
            inactive_count=0,
            retrieved_at=datetime.utcnow(),
            evidence_id="",
            error=ErrorCode.UNKNOWN_ERROR,
        )


def get_vendor_performance(vendor_ids: List[str]) -> VendorPerformanceList:
    """
    Get performance metrics for multiple vendors.
    
    Calculates reliability as average of (on_time_rate, fill_rate, quality_score).
    Vendor is eligible if reliability >= 0.90.
    """
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        
        vendors = []
        
        for vendor_id in vendor_ids:
            cursor.execute(
                """
                SELECT vendor_id, name, on_time_rate, fill_rate, quality_score
                FROM vendors
                WHERE vendor_id = ?
                """,
                (vendor_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                vendors.append(VendorPerformance(
                    vendor_id=vendor_id,
                    vendor_name="Unknown",
                    on_time_rate=0,
                    fill_rate=0,
                    quality_score=0,
                    reliability=0,
                    eligible=False,
                    evidence_id=f"vendor:{vendor_id}",
                ))
                continue
            
            # Calculate reliability as average of metrics
            reliability = (
                row["on_time_rate"] + row["fill_rate"] + row["quality_score"]
            ) / 3.0
            
            vendors.append(VendorPerformance(
                vendor_id=row["vendor_id"],
                vendor_name=row["name"],
                on_time_rate=row["on_time_rate"],
                fill_rate=row["fill_rate"],
                quality_score=row["quality_score"],
                reliability=round(reliability, 3),
                eligible=reliability >= 0.90,
                evidence_id=f"vendor:{row['vendor_id']}",
            ))
        
        conn.close()
        
        return VendorPerformanceList(
            vendors=vendors,
            retrieved_at=datetime.utcnow(),
        )
    except Exception as e:
        return VendorPerformanceList(
            vendors=[],
            retrieved_at=datetime.utcnow(),
            error=ErrorCode.UNKNOWN_ERROR,
        )


def build_vendor_options(
    stock_risk: StockRisk,
    vendor_offers: VendorOfferList,
    vendor_performance: VendorPerformanceList,
) -> VendorOptionList:
    """
    Build comparable vendor options with deadline and reliability checks.
    
    Pure deterministic calculation.
    - Respects MOQ (order quantity = max(MOQ, needed for coverage))
    - Calculates expected_arrival = now + lead_time_days
    - Checks meets_deadline (arrival before projected_stockout_date)
    - Checks reliable (vendor reliability >= 0.90)
    - eligible = meets_deadline AND reliable
    - Flags cheapest and fastest options
    - Returns sorted by cost
    """
    
    now = datetime.utcnow()
    options = []
    
    # Build lookup for vendor performance
    perf_by_vendor = {v.vendor_id: v for v in vendor_performance.vendors}
    
    for offer in vendor_offers.offers:
        # Get vendor performance
        perf = perf_by_vendor.get(offer.vendor_id)
        if not perf:
            continue
        
        # Calculate order quantity (at least MOQ)
        target_units = math.ceil(stock_risk.target_cover_days * stock_risk.daily_velocity)
        deficit = max(0, target_units - stock_risk.available_units)
        quantity = max(offer.moq, deficit)
        
        # Calculate costs
        total_cost = quantity * offer.unit_price
        expected_arrival = now + timedelta(days=offer.lead_time_days)
        
        # Check deadline
        meets_deadline = False
        if stock_risk.projected_stockout_date:
            meets_deadline = expected_arrival <= stock_risk.projected_stockout_date
        
        # Check reliability based on the vendor's computed eligibility score
        reliable = perf.eligible

        options.append(VendorOption(
            offer_id=offer.offer_id,
            vendor_id=offer.vendor_id,
            vendor_name=offer.vendor_name,
            quantity=quantity,
            unit_price=offer.unit_price,
            total_cost=total_cost,
            lead_time_days=offer.lead_time_days,
            expected_arrival=expected_arrival,
            meets_deadline=meets_deadline,
            reliable=reliable,
            eligible=meets_deadline and reliable,
        ))
    
    # Sort by cost
    options.sort(key=lambda x: x.total_cost)
    
    # Flag cheapest and fastest
    if options:
        options[0].flag_cheapest = True
    
    fastest = min(options, key=lambda x: x.lead_time_days, default=None)
    if fastest:
        fastest.flag_fastest = True
    
    # Extract eligible options
    eligible_options = [o for o in options if o.eligible]
    
    # Identify cheapest and fastest overall (not just eligible)
    cheapest_option = options[0] if options else None
    fastest_option = min(options, key=lambda x: x.lead_time_days, default=None)
    
    return VendorOptionList(
        options=options,
        eligible_options=eligible_options,
        cheapest_option=cheapest_option,
        fastest_option=fastest_option,
    )


from datetime import timedelta
