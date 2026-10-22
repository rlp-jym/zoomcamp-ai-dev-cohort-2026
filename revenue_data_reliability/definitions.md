# Definitions — Revenue Data Reliability Platform

## Revenue
Recognized revenue recorded in the General Ledger (`gl_revenue.recognized_revenue_amt`)
at the `(period, account_id, item_category)` grain. Used as the actuals baseline
for FP&A assessment and target attainment.

## Billings
Invoice-line subtotals aggregated by period and item category from
`invoice_lines` joined to `invoices` and `items`. Billings represent the
amount invoiced to customers before revenue recognition adjustments.

## DSO (Days Sales Outstanding)
Average number of days to collect payment after a sale. Computed as
`(Accounts Receivable / Total Credit Sales) * Days in Period`. A lower DSO
indicates faster collection.

## Fill Rate
Percentage of customer demand met from available inventory. Computed as
`Shipped Quantity / Ordered Quantity`. Used to measure supply-chain
reliability.

## Materiality
The tolerance threshold (percentage) applied to reconciliation variances.
Variances above `recon_tolerance_pct` are flagged as failures; those below
are considered immaterial and pass. Default tolerance is 5%.

## Dashboard KPI Selection Rationale

The 6 KPIs previously shown on the dashboard (Revenue, Billings, GL Variance %,
Open Data Issues, DQ Pass Rate, Published Runs) were chosen to give a balanced
view across three concerns:

- **Financial Performance:** Revenue, Billings, and GL Variance % capture the
  top-line health and the reconciliation gap between billings and the general
  ledger.
- **Data Reliability:** DQ Pass Rate and Open Data Issues surface the quality of
  the underlying data and how many issues remain unresolved.
- **Process Control:** Published Runs indicates how many pipeline runs have been
  promoted to the published state, giving a sense of release cadence.

This is a representative subset intended to prove the platform's capability —
anchored discussion threads, agent posts, and persona-driven review — rather
than an exhaustive BI tool. A real-world FP&A dashboard would typically expose
15-30 KPIs tailored to the specific business, industry, and reporting cadence.

## Traceability: orders → revenue

Revenue flow through the schema:

- **Bookings:** `orders`, `order_lines` (`extended_price = qty_ordered × unit_price`)
- **Fulfillment:** `shipments`, `shipment_lines` (`qty_shipped`, `freight_cost`); `shipment_lines.order_line_id → order_lines`
- **Lost revenue:** `backorders` (`lost_sales_value`, `backorder_cost`)
- **Billings (revenue event):** `invoices`, `invoice_lines` (`line_subtotal = qty_shipped × unit_price`; `line_total = subtotal + freight + tax − discount`); `invoice_lines` has no `order_line_id`
- **Contra-revenue:** `returns` (`credit_amount`, `return_value`, `margin_loss`); `returns.order_line_id → order_lines`, `returns.shipment_id → shipments`
- **Cash / DSO:** `ar_ledger` (`outstanding_balance`, `aging_bucket`, `payment_date`); `ar_ledger.invoice_id → invoices` (1:1)
- **Segments:** `customers` (`segment`, `region`, `activity_tier`), `items` (`category`, `subcategory`, `abc_class`, `lifecycle_stage`, `product_mix`), `distribution_centers` (`region`, `revenue_tier`)
- **Baseline:** `kpi_budget`

**Revenue formula**

- Gross billings = Σ `invoice_lines.line_subtotal` + `freight_allocated` − `discount_allocated` (exclude `tax_allocated`)
- Less returns = Σ `returns.credit_amount`
- **Net revenue = Gross billings − returns**

**Traceability facts**

- Order line → shipment line: **traceable** (`shipment_lines.order_line_id`)
- Order line → invoice line: **not traceable** (`invoice_lines` has only `invoice_id`, `item_id`)
- Order line → return: **traceable** (`returns.order_line_id`)
- Invoice → AR: **1:1 traceable** (`ar_ledger.invoice_id`)

Reconciliation is possible at **header level** (order total vs. invoice total vs. AR) and at **return level** (return vs. order line), but not at invoice-line-to-order-line level. That is the schema's limit and the rule catalog should not chase a link that does not exist.
