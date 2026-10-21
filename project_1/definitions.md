# Definitions — Revenue Data Reliability Platform

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
- **Allocation:** Billings are attributed to `(period, item_category)` by joining
  `invoice_lines` to the item master. GL is generated from the same per-category
  billings (scaled by a small per-category bias, then split across accounts), so
  the two sides reconcile at the category grain. Each category's billings are
  then expanded across its account rows in proportion to each row's GL share,
  so every row in a category carries the category-level variance.
- **Variance %:** `(billings − gl) / gl`.
- **Status:** `pass` when `|variance_pct| <= tolerance`, otherwise `fail`.
- **Materiality tolerance:** `RECON_TOLERANCE_PCT` (default `0.5%`, i.e. `0.005`),
  read from configuration.
- **Material gap:** a reconciliation row whose status is `fail`; each affected
  period opens exactly one `reconciliation` exception.

## Dashboard Visuals

The dashboard shows six KPIs, three charts and one assessment card. Each
visual carries a distinct quantity — the same series is never drawn twice:

- **Revenue, Billings & Plan:** General Ledger revenue (actuals) against
  billings and the targeted plan over the trailing six months, plus a
  dashed three-month run-rate projection. The projection carries the
  average month-over-month growth of the last three actual months forward
  at a constant rate, and is anchored on the last actual month.
- **Variances by Category:** average billing-vs-General-Ledger variance %
  per item category, from the reconciliation rows of the published run.
- **Month-over-Month Growth:** month-over-month change in General Ledger
  revenue for the trailing months.
- **Target Attainment:** General Ledger revenue as a percentage of the targeted
  plan for the same window, with billings by customer segment underneath (shown
  as bars, one per segment). Customer segments (who buys) are independent of
  item categories (what's sold) -- the variance chart groups by item category,
  this groups by customer segment. A segment the source system does not
  recognise is a customer-master mapping drift and is flagged rather than
  blended into the mix.
