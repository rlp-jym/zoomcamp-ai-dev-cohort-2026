"""Seed personas and validation rules (idempotent)."""

from backend.db.connection import get_connection

PERSONAS = [
    ("analyst", "human", "FP&A Analyst", "Owns runs; triggers pipeline; participates in threads"),
    ("manager", "human", "FP&A Manager", "Approves go-live; approves remediation"),
    ("director", "human", "Director of FP&A", "Critical escalation target"),
    ("orchestrator", "agent", "Pipeline Orchestrator", "Runs pipeline; posts start/finish; requests go-live"),
    ("de", "agent", "Data Engineer", "Proposes remediation (re-run, quarantine, reload)"),
    ("dq", "agent", "Data Quality", "Executes rules; posts validation results"),
    ("fa", "agent", "Financial Analyst", "Translates every defect into financial impact; may open analysis threads"),
    ("controller", "agent", "Controller", "Runtime first responder; verifies published state"),
]

RULES = [
    ("VAL_FK_ITEM_EXISTS", "Foreign key: item exists in invoice_lines", "high", "SELECT * FROM read_parquet('s3://{bucket}/scenarios/{scenario}/invoice_lines.parquet') il LEFT JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/items.parquet') i ON il.item_id = i.item_id WHERE i.item_id IS NULL", "orphaned_item_id"),
    ("VAL_DUPLICATE_INVOICE_LINE", "Duplicate invoice line detection", "medium", "SELECT invoice_id, line_no, COUNT(*) c FROM read_parquet('s3://{bucket}/scenarios/{scenario}/invoice_lines.parquet') GROUP BY invoice_id, line_no HAVING COUNT(*) > 1", "duplicate_invoice_line"),
    ("VAL_FK_CUSTOMER_EXISTS", "Foreign key: customer exists", "high", "SELECT * FROM read_parquet('s3://{bucket}/scenarios/{scenario}/invoices.parquet') inv LEFT JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/customers.parquet') c ON inv.customer_id = c.customer_id WHERE c.customer_id IS NULL", "missing_customer_mapping"),
    ("VAL_FRESHNESS_GL", "GL freshness / stale load", "medium", "SELECT * FROM read_parquet('s3://{bucket}/scenarios/{scenario}/gl_revenue.parquet') WHERE load_date < (SELECT MAX(invoice_date) FROM read_parquet('s3://{bucket}/scenarios/{scenario}/invoices.parquet'))", "stale_load"),
    ("VAL_RECON_BILLINGS_GL", "Billings vs GL reconciliation", "high", "SELECT period, account_id, item_category, SUM(billings) billings, SUM(gl) gl FROM ...", "billings_gl_variance"),
    ("VAL_RESTATEMENT_DETECTED", "Restatement detected", "medium", "SELECT * FROM read_parquet('s3://{bucket}/scenarios/{scenario}/gl_revenue.parquet') WHERE is_restatement = TRUE", "restatement"),
    ("VAL_FX_RATE_EXISTS", "FX rate exists", "medium", "SELECT * FROM read_parquet('s3://{bucket}/scenarios/{scenario}/invoices.parquet') i LEFT JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/fx_rates.parquet') f ON i.currency = f.currency WHERE f.currency IS NULL", "fx_gap"),
    ("VAL_FK_BACKORDER_ORDER_LINE", "Foreign key: backorder order line", "medium", "SELECT * FROM read_parquet('s3://{bucket}/scenarios/{scenario}/backorders.parquet') b LEFT JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/order_lines.parquet') ol ON b.order_line_id = ol.order_line_id WHERE ol.order_line_id IS NULL", "orphaned_backorder"),
    ("VAL_FK_RETURN_SHIPMENT", "Foreign key: return shipment", "medium", "SELECT * FROM read_parquet('s3://{bucket}/scenarios/{scenario}/returns.parquet') r LEFT JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/shipments.parquet') s ON r.shipment_id = s.shipment_id WHERE s.shipment_id IS NULL", "phantom_return"),
    ("VAL_AR_INVOICE_1TO1", "AR invoice 1-to-1 invariant", "low", "SELECT invoice_id, COUNT(*) c FROM read_parquet('s3://{bucket}/scenarios/{scenario}/ar_ledger.parquet') GROUP BY invoice_id HAVING COUNT(*) <> 1", "invariant"),
    ("VAL_ORDER_LINE_UNIQUE", "Order line uniqueness invariant", "low", "SELECT order_id, line_no, COUNT(*) c FROM read_parquet('s3://{bucket}/scenarios/{scenario}/order_lines.parquet') GROUP BY order_id, line_no HAVING COUNT(*) > 1", "invariant"),
]


def seed() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            for persona_id, ptype, title, role in PERSONAS:
                cur.execute(
                    """
                    INSERT INTO personas (persona_id, type, title, role)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (persona_id) DO NOTHING
                    """,
                    (persona_id, ptype, title, role),
                )
            for rule_id, desc, severity, sql, expected in RULES:
                cur.execute(
                    """
                    INSERT INTO rules (rule_id, description, severity, sql, expected_detection_rule)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (rule_id) DO NOTHING
                    """,
                    (rule_id, desc, severity, sql, expected),
                )
        conn.commit()


if __name__ == "__main__":
    from backend.db.connection import init_pool, apply_schema

    init_pool()
    apply_schema()
    seed()
    print("seeded")
