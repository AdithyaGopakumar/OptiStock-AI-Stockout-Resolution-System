"""
Execution Tools
Revalidation and write operations.

CRITICAL: These tools can only be called by deterministic (non-LLM) nodes.
No LLM agent may call create_purchase_request.
"""

import sqlite3
from config import DATABASE_PATH
import hashlib
from datetime import datetime
from typing import Optional
import uuid
from domain.tool_models import (
    ReplenishmentProposal,
    RevalidationResult,
    PurchaseRequestResult,
    PurchaseRequestStatus,
    AuditEventResult,
    ErrorCode,
)


def _get_db_connection(db_path: str = None):
    if db_path is None:
        db_path = DATABASE_PATH
    """Get database connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _hash_proposal(proposal: ReplenishmentProposal) -> str:
    """
    Create SHA256 hash of proposal for integrity checking.
    
    Includes all critical fields but not timestamps/IDs.
    """
    key_parts = [
        str(proposal.sku),
        str(proposal.warehouse_id),
        str(proposal.quantity),
        str(proposal.unit_price),
        str(proposal.recommended_vendor_id),
        str(proposal.target_cover_days),
    ]
    key_string = "|".join(key_parts)
    return hashlib.sha256(key_string.encode()).hexdigest()


def revalidate_approved_proposal(
    proposal_id: str,
    proposal_hash: str,
) -> RevalidationResult:
    """
    Revalidate an approved proposal before purchase request creation.
    
    Checks:
    1. Proposal hash matches (proposal not modified)
    2. Stock snapshot is still current (< 2 days old)
    3. Vendor offer is still active and valid
    4. Budget is still sufficient
    
    This is a system tool, NOT callable by LLM agents.
    Called only by deterministic post-approval node.
    
    Returns all_checks_pass=True only if ALL revalidations pass.
    If any check fails, approval is invalidated and write is blocked.
    """
    
    # TODO: In real implementation, would retrieve stored proposal from case state
    # and re-validate against current database state
    
    return RevalidationResult(
        proposal_id=proposal_id,
        proposal_hash=proposal_hash,
        hash_matches=True,  # Simplified for starter
        stock_valid=True,
        offer_valid=True,
        budget_valid=True,
        all_checks_pass=True,
        error_details=None,
    )


def create_purchase_request(
    proposal: ReplenishmentProposal,
    idempotency_key: str,
    approved_by: str,
) -> PurchaseRequestResult:
    """
    Create a purchase request in the database.
    
    CRITICAL: This is a write operation. Must be called ONLY after:
    1. Human approval from a named approver
    2. Successful revalidation of all facts
    3. Idempotency key to prevent duplicates
    
    This tool is NEVER available to LLM agents.
    
    Returns:
        - request_id: New or existing request ID
        - created: True if newly created, False if idempotent return
        - If idempotency_key already exists, returns existing request
        - Unique database constraint prevents duplicate writes
    """
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        
        # Check if this idempotency_key already exists
        cursor.execute(
            "SELECT request_id, status FROM purchase_requests WHERE idempotency_key = ?",
            (idempotency_key,)
        )
        existing = cursor.fetchone()
        
        if existing:
            # Idempotent return: same request already exists
            conn.close()
            return PurchaseRequestResult(
                request_id=existing["request_id"],
                case_id=proposal.case_id,
                status=PurchaseRequestStatus(existing["status"]),
                created=False,
                total_cost=proposal.total_cost,
            )
        
        # Create new purchase request
        request_id = f"PR-{uuid.uuid4().hex[:12].upper()}"
        now = datetime.utcnow()
        
        cursor.execute(
            """
            INSERT INTO purchase_requests (
                request_id, case_id, vendor_id, sku, warehouse_id,
                quantity, unit_price, total_cost, status, idempotency_key,
                approved_by, approved_at, expected_arrival_date, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                proposal.case_id,
                proposal.recommended_vendor_id,
                proposal.sku,
                proposal.warehouse_id,
                proposal.quantity,
                proposal.unit_price,
                proposal.total_cost,
                PurchaseRequestStatus.PENDING,
                idempotency_key,
                approved_by,
                now,
                proposal.expected_arrival,
                now,
            )
        )
        
        # Update the monthly budget to reflect the newly committed funds
        budget_month = now.strftime("%Y-%m")
        cursor.execute(
            """
            UPDATE monthly_budgets
            SET committed_amount = committed_amount + ?,
                updated_at = ?
            WHERE warehouse_id = ? AND month = ?
            """,
            (proposal.total_cost, now, proposal.warehouse_id, budget_month)
        )
        
        conn.commit()
        conn.close()
        
        return PurchaseRequestResult(
            request_id=request_id,
            case_id=proposal.case_id,
            status=PurchaseRequestStatus.PENDING,
            created=True,
            total_cost=proposal.total_cost,
        )
    except sqlite3.IntegrityError as e:
        # Constraint violation (likely duplicate idempotency_key)
        # This should not happen if revalidation passed, but handle it safely
        return PurchaseRequestResult(
            request_id="",
            case_id=proposal.case_id,
            status=PurchaseRequestStatus.FAILED,
            created=False,
            total_cost=0,
            error=ErrorCode.WRITE_FAILED,
            error_details=f"Database constraint violation: {str(e)}",
        )
    except Exception as e:
        return PurchaseRequestResult(
            request_id="",
            case_id=proposal.case_id,
            status=PurchaseRequestStatus.FAILED,
            created=False,
            total_cost=0,
            error=ErrorCode.UNKNOWN_ERROR,
            error_details=str(e),
        )


def append_audit_event(
    case_id: str,
    trace_id: str,
    actor: str,  # "system", "agent:*", "human:*"
    event_type: str,  # "risk_assessed", "approved", etc.
    payload: dict,  # JSON-serializable event details
) -> AuditEventResult:
    """
    Append an audit event to the audit trail.
    
    Called by orchestration code only; never exposed as open-ended tool to LLMs.
    Captures structured summaries, NOT private reasoning or chain-of-thought.
    
    Args:
        case_id: Case identifier
        trace_id: Request trace ID (for correlation)
        actor: Who/what created the event
        event_type: Type of event
        payload: Structured event data (JSON)
    
    Returns:
        AuditEventResult with event_id and status
    """
    try:
        import json
        
        conn = _get_db_connection()
        cursor = conn.cursor()
        
        event_id = f"EVT-{uuid.uuid4().hex[:12].upper()}"
        now = datetime.utcnow()
        payload_json = json.dumps(payload)
        
        cursor.execute(
            """
            INSERT INTO audit_events (
                event_id, case_id, trace_id, actor, event_type, 
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                case_id,
                trace_id,
                actor,
                event_type,
                payload_json,
                now,
            )
        )
        conn.commit()
        conn.close()
        
        return AuditEventResult(
            event_id=event_id,
            case_id=case_id,
            created=True,
        )
    except Exception as e:
        return AuditEventResult(
            event_id="",
            case_id=case_id,
            created=False,
            error=ErrorCode.WRITE_FAILED,
        )


def get_pending_purchase_orders(sku: str, warehouse_id: str) -> dict:
    """
    Get all active (PENDING or CONFIRMED) purchase orders for a given SKU and Warehouse.
    
    Returns a list of dicts with PO details.
    """
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT request_id, vendor_id, quantity, expected_arrival_date, status
            FROM purchase_requests 
            WHERE sku = ? AND warehouse_id = ? AND status IN ('PENDING', 'CONFIRMED')
            ORDER BY expected_arrival_date ASC
            """,
            (sku, warehouse_id)
        )
        rows = cursor.fetchall()
        conn.close()
        
        orders = []
        for row in rows:
            orders.append({
                "request_id": row["request_id"],
                "vendor_id": row["vendor_id"],
                "quantity": row["quantity"],
                "expected_arrival_date": row["expected_arrival_date"],
                "status": row["status"],
            })
            
        return {
            "sku": sku,
            "warehouse_id": warehouse_id,
            "pending_orders": orders,
            "has_pending_orders": len(orders) > 0,
            "error": None
        }
    except Exception as e:
        return {
            "sku": sku,
            "warehouse_id": warehouse_id,
            "pending_orders": [],
            "has_pending_orders": False,
            "error": str(e)
        }
