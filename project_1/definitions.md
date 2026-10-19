# Definitions — Revenue Data Reliability Platform

## Dashboard KPI Selection Rationale

The 6 KPIs currently shown on the dashboard (Revenue, Billings, GL Variance %,
Open Exceptions, DQ Pass Rate, Published Runs) were chosen to give a balanced
view across three concerns:

- **Financial Performance:** Revenue, Billings, and GL Variance % capture the
  top-line health and the reconciliation gap between billings and the general
  ledger.
- **Data Reliability:** DQ Pass Rate and Open Exceptions surface the quality of
  the underlying data and how many issues remain unresolved.
- **Process Control:** Published Runs indicates how many pipeline runs have been
  promoted to the published state, giving a sense of release cadence.

This is a representative subset intended to prove the platform's capability —
anchored discussion threads, agent posts, and persona-driven review — rather
than an exhaustive BI tool. A real-world FP&A dashboard would typically expose
15-30 KPIs tailored to the specific business, industry, and reporting cadence.
The demo deliberately keeps the set small so the layout, threads, and
interactions stay reviewable on a single screen.

## Reconciliation Definitions

- **Grain:** `(run_id, period, account_id, item_category)` per GL row, plus a
  top-N-customer slice where `gl_revenue.customer_id` is populated.
- **Billings:** sum of `invoice_lines.line_subtotal` attributed to the invoice
  period (`invoices.invoice_date`, formatted `YYYY-MM`).
- **GL:** `gl_revenue.recognized_revenue_amt` for the matching grain. Version 1
  is the baseline; restatements (`version > 1`) are handled by
  `VAL_RESTATEMENT_DETECTED`, not by reconciliation.
- **Allocation:** GL distributes the period's billings across the 15
  `(account_id, item_category)` grains with a random weight per period. Since no
  natural item/customer dimension joins billings onto those grains, period
  billings are allocated to each grain in proportion to that grain's GL share.
- **Variance %:** `(billings − gl) / gl`.
- **Status:** `pass` when `|variance_pct| <= tolerance`, otherwise `fail`.
- **Materiality tolerance:** `RECON_TOLERANCE_PCT` (default `0.5%`, i.e. `0.005`),
  read from configuration.
- **Material gap:** a reconciliation row whose status is `fail`; each such row
  opens exactly one `reconciliation` exception grouped by
  `(period, account_id, item_category)`.