**Source tables — 13**

## budget (reference only)

Grain `(period, account_id, item_category, customer_id)`. Reference table for
budget-vs-actual variance. Not validated, not defect-injected.

| # | Table | Role | Why it's a source |
|---|---|---|---|
| 1 | `orders` | Transactional — origin | Revenue cycle starts here. `order_date` sets the period; `order_type`, `ship_via`, `order_status` are segment/filter fields. Header-level anchor for invoice and shipment joins. |
| 2 | `order_lines` | Transactional — origin (line grain) | Bookings grain. `qty_ordered`, `qty_shipped`, `unit_price`, `extended_price`, `substitution_flag`. Root of traceability — `shipment_lines`, `returns`, and `backorders` carry `order_line_id`. |
| 3 | `shipments` | Transactional — fulfillment | Ship/promised/delivery dates for OTIF and fill-rate. Carrier and DC attribution. Parallel branch to invoices, not a parent. |
| 4 | `shipment_lines` | Transactional — fulfillment (line grain) | The only line-level bridge back to `order_lines` (`order_line_id`). Required for order-to-fulfillment traceability. |
| 5 | `invoices` | Transactional — billings header | The revenue event. Ties to `orders` via `order_id`. `invoice_date` is the period used for recognized revenue. `total_amount`, `discount_amount`, `payment_terms`. |
| 6 | `invoice_lines` | Transactional — billings grain | Where revenue amounts live: `line_subtotal`, `line_total`, `discount_allocated`, `freight_allocated`. No `order_line_id`; line-level trace depends on the `(order_id, item_id)` join through the invoice header. |
| 7 | `ar_ledger` | Transactional — cash | 1:1 with invoices. `outstanding_balance`, `aging_bucket`, `payment_date`, `writeoff_flag`, `credit_hold_flag`. Source for DSO, aging, and revenue-quality cuts. |
| 8 | `returns` | Transactional — contra-revenue | Reduces net revenue via `credit_amount` and `return_value`. Carries both `order_line_id` and `shipment_id`, so returns are fully traceable to origin. |
| 9 | `backorders` | Transactional — lost revenue | `lost_sales_value`, `backorder_cost`, `reason_code`. Quantifies revenue that didn't happen. Joins to `order_lines` via `order_line_id`. |
| 10 | `customers` | Dimension — segment | `segment`, `region`, `activity_tier`, `customer_status`, `churn_date`, `account_open_date`. Primary segment dimension and vintage/cohort source. |
| 11 | `items` | Dimension — segment | `category`, `subcategory`, `abc_class`, `xyz_class`, `lifecycle_stage`, `product_mix`, `seasonality_class`. Primary product dimension. |
| 12 | `distribution_centers` | Dimension — segment | `region`, `revenue_tier`, `ownership_type`. Facility-level segment cut for revenue and fill-rate. |
| 13 | `manufacturers` | Dimension — segment | Resolves `items.manufacturer_code` to name and category. Enables revenue-by-brand cuts. 1,799 rows, clean join. |

**Traceability summary**

- Order line → shipment line: traceable (`shipment_lines.order_line_id`)
- Order line → return: traceable (`returns.order_line_id`)
- Order line → backorder: traceable (`backorders.order_line_id`)
- Order line → invoice line: **not directly traceable**; relies on `(order_id, item_id)` uniqueness in `order_lines`
- Invoice → AR: traceable 1:1 (`ar_ledger.invoice_id`)