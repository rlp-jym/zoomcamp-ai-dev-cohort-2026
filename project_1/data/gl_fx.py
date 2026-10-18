"""GL revenue and FX rate generation."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from timeline import month_list, period_start_date, _parse_ym


def generate_fx_rates(cfg: dict, rng: np.random.Generator) -> pd.DataFrame:
    tl = cfg["timeline"]
    scale = cfg["scale"]
    periods = month_list(tl["start_month"], int(tl["n_months"]))
    n_curr = int(scale["currencies"])
    currencies = ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "SEK"][:n_curr]
    rows = []
    for period in periods:
        for c in currencies:
            rows.append({
                "currency": c,
                "period": period,
                "rate_to_usd": round(float(rng.random() * 0.4 + 0.8), 6),
                "load_date": pd.Timestamp(period_start_date(period)),
                "version": 1,
            })
    return pd.DataFrame(rows)


def generate_gl_revenue(cfg: dict, rng: np.random.Generator, tx: dict) -> pd.DataFrame:
    tl = cfg["timeline"]
    scale = cfg["scale"]
    periods = month_list(tl["start_month"], int(tl["n_months"]))
    n_accounts = int(scale["gl_accounts"])
    n_cats = int(scale["item_categories"])
    accounts = list(range(1, n_accounts + 1))
    categories = list(range(1, n_cats + 1))

    # monthly billings baseline from invoices/invoice_lines
    invoices = tx.get("invoices", pd.DataFrame())
    lines = tx.get("invoice_lines", pd.DataFrame())
    monthly_billings: dict[str, float] = {p: 0.0 for p in periods}
    if not invoices.empty and not lines.empty:
        inv = invoices[["invoice_id", "invoice_date"]].copy()
        inv["period"] = pd.to_datetime(inv["invoice_date"]).dt.to_period("M").astype(str)
        merged = lines.merge(inv[["invoice_id", "period"]], on="invoice_id", how="left")
        grp = merged.groupby("period")["line_subtotal"].sum()
        for p, v in grp.items():
            if p in monthly_billings:
                monthly_billings[p] = float(v)

    rows = []
    for period in periods:
        total = monthly_billings[period]
        # allocate across account x category
        weights = rng.random(n_accounts * n_cats)
        weights = weights / weights.sum()
        alloc = total * weights
        idx = 0
        for acc in accounts:
            for cat in categories:
                rows.append({
                    "period": period,
                    "account_id": acc,
                    "item_category": cat,
                    "customer_id": None,
                    "recognized_revenue_amt": round(float(alloc[idx]), 2),
                    "load_date": pd.Timestamp(period_start_date(period)),
                    "version": 1,
                })
                idx += 1
    out = pd.DataFrame(rows)
    out["customer_id"] = out["customer_id"].astype("Int64")
    return out
