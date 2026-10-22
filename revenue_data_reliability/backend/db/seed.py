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
    (
        "VAL_FK_ITEM_EXISTS",
        "Foreign key: every invoice line item exists in the item master",
        "high",
        """
        SELECT strftime(inv.invoice_date, '%Y-%m') AS period,
               il.invoice_line_id, il.item_id
        FROM read_parquet('s3://{bucket}/scenarios/{scenario}/invoice_lines.parquet') il
        JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/invoices.parquet') inv
             ON il.invoice_id = inv.invoice_id
        LEFT JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/items.parquet') i
             ON il.item_id = i.item_id
        WHERE i.item_id IS NULL
        """,
        "orphaned_item_id",
    ),
    (
        "VAL_DUPLICATE_INVOICE_LINE",
        "Duplicate invoice line: same item billed twice on one invoice",
        "medium",
        """
        SELECT period, invoice_id, item_id, COUNT(*) AS dup_count
        FROM (
            SELECT strftime(inv.invoice_date, '%Y-%m') AS period,
                   il.invoice_id, il.item_id
            FROM read_parquet('s3://{bucket}/scenarios/{scenario}/invoice_lines.parquet') il
            JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/invoices.parquet') inv
                 ON il.invoice_id = inv.invoice_id
        )
        GROUP BY period, invoice_id, item_id
        HAVING COUNT(*) > 1
        """,
        "duplicate_invoice_line",
    ),
    (
        "VAL_FK_CUSTOMER_EXISTS",
        "Foreign key: every invoice customer exists in the customer master",
        "high",
        """
        SELECT strftime(inv.invoice_date, '%Y-%m') AS period,
               inv.invoice_id, inv.customer_id
        FROM read_parquet('s3://{bucket}/scenarios/{scenario}/invoices.parquet') inv
        LEFT JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/customers.parquet') c
             ON inv.customer_id = c.customer_id
        WHERE c.customer_id IS NULL
        """,
        "missing_customer_mapping",
    ),
    (
        "VAL_FRESHNESS_GL",
        "General Ledger freshness: revenue rows with a missing or stale load date",
        "medium",
        """
        SELECT period, account_id, item_category
        FROM read_parquet('s3://{bucket}/scenarios/{scenario}/gl_revenue.parquet')
        WHERE load_date IS NULL
           OR load_date < CAST(period || '-01' AS DATE)
        """,
        "stale_load",
    ),
    (
        "VAL_RECON_BILLINGS_GL",
        "Billings vs General Ledger: per-category variance above materiality tolerance",
        "high",
        """
        WITH bill AS (
            SELECT strftime(inv.invoice_date, '%Y-%m') AS period,
                   CASE WHEN it.category IN ('Electronics', 'Industrial', 'Office', 'Safety', 'Misc')
                        THEN it.category ELSE 'Misc' END AS item_category,
                   SUM(il.line_subtotal) AS billings
            FROM read_parquet('s3://{bucket}/scenarios/{scenario}/invoice_lines.parquet') il
            JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/invoices.parquet') inv
                 ON il.invoice_id = inv.invoice_id
            JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/items.parquet') it
                 ON il.item_id = it.item_id
            GROUP BY 1, 2
        ), gl AS (
            SELECT period, account_id, item_category,
                   recognized_revenue_amt AS gl,
                   SUM(recognized_revenue_amt) OVER (PARTITION BY period, item_category) AS gl_cat
            FROM read_parquet('s3://{bucket}/scenarios/{scenario}/gl_revenue.parquet')
            WHERE version = 1
        )
        SELECT gl.period, gl.account_id, gl.item_category,
               bill.billings * gl.gl / gl.gl_cat AS billings,
               gl.gl AS gl,
               (bill.billings * gl.gl / gl.gl_cat - gl.gl) / gl.gl AS variance_pct
        FROM gl JOIN bill ON gl.period = bill.period AND gl.item_category = bill.item_category
        WHERE ABS((bill.billings * gl.gl / gl.gl_cat - gl.gl) / gl.gl) > {tolerance}
        """,
        "billings_gl_variance",
    ),
    (
        "VAL_RESTATEMENT_DETECTED",
        "Restatement: General Ledger revenue carries a version greater than 1",
        "medium",
        """
        SELECT period, account_id, item_category, version
        FROM read_parquet('s3://{bucket}/scenarios/{scenario}/gl_revenue.parquet')
        WHERE version > 1
        """,
        "restatement",
    ),
    (
        "VAL_FX_RATE_EXISTS",
        "FX rate exists for every invoice period and customer currency",
        "medium",
        """
        SELECT strftime(inv.invoice_date, '%Y-%m') AS period,
               inv.invoice_id, c.currency
        FROM read_parquet('s3://{bucket}/scenarios/{scenario}/invoices.parquet') inv
        JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/customers.parquet') c
             ON inv.customer_id = c.customer_id
        LEFT JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/fx_rates.parquet') f
             ON f.currency = c.currency
            AND f.period = strftime(inv.invoice_date, '%Y-%m')
        WHERE f.currency IS NULL
        """,
        "fx_gap",
    ),
    (
        "VAL_FK_BACKORDER_ORDER_LINE",
        "Foreign key: every backorder references an existing order line",
        "medium",
        """
        SELECT b.backorder_id, b.order_line_id
        FROM read_parquet('s3://{bucket}/scenarios/{scenario}/backorders.parquet') b
        LEFT JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/order_lines.parquet') ol
             ON b.order_line_id = ol.order_line_id
        WHERE ol.order_line_id IS NULL
        """,
        "orphaned_backorder",
    ),
    (
        "VAL_FK_RETURN_SHIPMENT",
        "Foreign key: every return references an existing shipment",
        "medium",
        """
        SELECT strftime(o.order_date, '%Y-%m') AS period,
               r.return_id, r.shipment_id
        FROM read_parquet('s3://{bucket}/scenarios/{scenario}/returns.parquet') r
        LEFT JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/shipments.parquet') s
             ON r.shipment_id = s.shipment_id
        LEFT JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/order_lines.parquet') ol
             ON r.order_line_id = ol.order_line_id
        LEFT JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/orders.parquet') o
             ON ol.order_id = o.order_id
        WHERE s.shipment_id IS NULL
        """,
        "phantom_return",
    ),
    (
        "VAL_AR_INVOICE_1TO1",
        "Invariant: each invoice has exactly one AR ledger row",
        "low",
        """
        SELECT invoice_id, COUNT(*) AS c
        FROM read_parquet('s3://{bucket}/scenarios/{scenario}/ar_ledger.parquet')
        GROUP BY invoice_id
        HAVING COUNT(*) <> 1
        """,
        "invariant",
    ),
    (
        "VAL_ORDER_LINE_UNIQUE",
        "Invariant: (order_id, item_id) is unique on order lines",
        "low",
        """
        SELECT strftime(o.order_date, '%Y-%m') AS period,
               ol.order_id, ol.item_id, COUNT(*) AS c
        FROM read_parquet('s3://{bucket}/scenarios/{scenario}/order_lines.parquet') ol
        JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/orders.parquet') o
             ON ol.order_id = o.order_id
        GROUP BY period, ol.order_id, ol.item_id
        HAVING COUNT(*) > 1
        """,
        "invariant",
    ),
    (
        "VAL_SEGMENT_DRIFT",
        "Unrecognised customer segment: customer master contains a segment not in the source mapping",
        "medium",
        """
        SELECT customer_id, segment
        FROM read_parquet('s3://{bucket}/scenarios/{scenario}/customers.parquet')
        WHERE segment = 'remapped_segment'
        """,
        "segment_drift",
    ),
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
                # Rules are versioned in code; keep the DB definition in sync.
                cur.execute(
                    """
                    INSERT INTO rules (rule_id, description, severity, sql, expected_detection_rule)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (rule_id) DO UPDATE SET
                        description = EXCLUDED.description,
                        severity = EXCLUDED.severity,
                        sql = EXCLUDED.sql,
                        expected_detection_rule = EXCLUDED.expected_detection_rule
                    """,
                    (rule_id, desc, severity, sql, expected),
                )
        conn.commit()


if __name__ == "__main__":
    from backend.db.connection import apply_schema, init_pool

    init_pool()
    apply_schema()
    seed()
    print("seeded")
