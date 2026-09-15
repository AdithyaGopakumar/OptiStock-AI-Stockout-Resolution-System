-- OptiStock AI- Multi-Agent Stockout Resolution System
-- Database Schema
-- SQLite 3.x

-- ============================================================================
-- PRODUCTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- INVENTORY SNAPSHOTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS inventory_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    sku TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    on_hand INTEGER NOT NULL,
    reserved INTEGER NOT NULL,
    confirmed_inbound INTEGER NOT NULL,
    captured_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sku) REFERENCES products(sku),
    UNIQUE(sku, warehouse_id, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_inventory_snapshots_sku_warehouse 
    ON inventory_snapshots(sku, warehouse_id);
CREATE INDEX IF NOT EXISTS idx_inventory_snapshots_captured_at 
    ON inventory_snapshots(captured_at);

-- ============================================================================
-- SALES HISTORY
-- ============================================================================
CREATE TABLE IF NOT EXISTS sales_daily (
    sale_id TEXT PRIMARY KEY,
    sale_date DATE NOT NULL,
    sku TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    units_sold INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sku) REFERENCES products(sku),
    UNIQUE(sale_date, sku, warehouse_id)
);

CREATE INDEX IF NOT EXISTS idx_sales_daily_sku_warehouse 
    ON sales_daily(sku, warehouse_id);
CREATE INDEX IF NOT EXISTS idx_sales_daily_date 
    ON sales_daily(sale_date);

-- ============================================================================
-- VENDORS
-- ============================================================================
CREATE TABLE IF NOT EXISTS vendors (
    vendor_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT 1,
    on_time_rate REAL NOT NULL,  -- 0.0 to 1.0
    fill_rate REAL NOT NULL,      -- 0.0 to 1.0
    quality_score REAL NOT NULL,  -- 0.0 to 1.0
    notes TEXT,                   -- Untrusted data; not instructions
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_vendors_active ON vendors(active);

-- ============================================================================
-- VENDOR OFFERS
-- ============================================================================
CREATE TABLE IF NOT EXISTS vendor_offers (
    offer_id TEXT PRIMARY KEY,
    vendor_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    unit_price REAL NOT NULL,
    moq INTEGER NOT NULL,  -- Minimum Order Quantity
    lead_time_days INTEGER NOT NULL,
    valid_until TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id),
    FOREIGN KEY (sku) REFERENCES products(sku),
    UNIQUE(vendor_id, sku, valid_until)
);

CREATE INDEX IF NOT EXISTS idx_vendor_offers_sku ON vendor_offers(sku);
CREATE INDEX IF NOT EXISTS idx_vendor_offers_vendor ON vendor_offers(vendor_id);
CREATE INDEX IF NOT EXISTS idx_vendor_offers_valid_until ON vendor_offers(valid_until);

-- ============================================================================
-- MONTHLY BUDGETS
-- ============================================================================
CREATE TABLE IF NOT EXISTS monthly_budgets (
    budget_id TEXT PRIMARY KEY,
    warehouse_id TEXT NOT NULL,
    month TEXT NOT NULL,  -- YYYY-MM format
    budget_amount REAL NOT NULL,
    spent_amount REAL NOT NULL DEFAULT 0,
    committed_amount REAL NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(warehouse_id, month)
);

CREATE INDEX IF NOT EXISTS idx_monthly_budgets_warehouse_month 
    ON monthly_budgets(warehouse_id, month);

-- ============================================================================
-- PURCHASE REQUESTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS purchase_requests (
    request_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    total_cost REAL NOT NULL,
    status TEXT NOT NULL,  -- PENDING, CONFIRMED, REJECTED, FAILED
    idempotency_key TEXT NOT NULL UNIQUE,
    approved_by TEXT,
    approved_at TIMESTAMP,
    expected_arrival_date TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id),
    FOREIGN KEY (sku) REFERENCES products(sku)
);

CREATE INDEX IF NOT EXISTS idx_purchase_requests_case_id ON purchase_requests(case_id);
CREATE INDEX IF NOT EXISTS idx_purchase_requests_status ON purchase_requests(status);
CREATE INDEX IF NOT EXISTS idx_purchase_requests_idempotency_key ON purchase_requests(idempotency_key);

-- ============================================================================
-- AUDIT EVENTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    actor TEXT NOT NULL,  -- "system", "agent:*", "human:*"
    event_type TEXT NOT NULL,  -- "risk_assessed", "proposal_prepared", "approved", etc.
    payload_json TEXT NOT NULL,  -- JSON-encoded event details
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_events_case_id ON audit_events(case_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_trace_id ON audit_events(trace_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at);
