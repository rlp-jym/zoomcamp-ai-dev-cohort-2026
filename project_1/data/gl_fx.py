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


def generate_gl_revenue(cfg: dict, rng: np.random.Generator, tx: dict,
                        items: pd.DataFrame | None = None) -> pd.DataFrame:
    tl = cfg["timeline"]
    scale = cfg["scale"]
    periods = month_list(tl["start_month"], int(tl["n_months"]))
    n_accounts = int(scale["gl_accounts"])
    n_cats = int(scale["item_categories"])
    accounts = list(range(1, n_accounts + 1))
    categories = scale["item_category_names"]
    if len(categories) != n_cats:
        raise ValueError("item_category_names length must equal item_categories")
    spread = float(scale.get("gl_category_bias_spread", 0.0))
    cat_bias = rng.uniform(1.0 - spread, 1.0 + spread, n_cats)
    # Any item category outside the GL category list (e.g. a remapped
    # category from dimension drift) rolls up into the catch-all bucket.
    catch_all = categories[-1] if categories else "Misc"

    # Per-category billings baseline: invoice lines joined to the item master.
    # Billings and GL are reconciled per category, so GL must be allocated from
    # the same per-category billings rather than the period total.
    invoices = tx.get("invoices", pd.DataFrame())
    lines = tx.get("invoice_lines", pd.DataFrame())
    cat_billings: dict[str, dict[str, float]] = {
        p: {c: 0.0 for c in categories} for p in periods
    }
    if not invoices.empty and not lines.empty and items is not None and not items.empty:
        inv = invoices[["invoice_id", "invoice_date"]].copy()
        inv["period"] = pd.to_datetime(inv["invoice_date"]).dt.to_period("M").astype(str)
        merged = lines.merge(inv[["invoice_id", "period"]], on="invoice_id", how="inner")
        merged = merged.merge(items[["item_id", "category"]], on="item_id", how="inner")
        merged["gl_category"] = merged["category"].where(
            merged["category"].isin(categories), catch_all
        )
        grp = merged.groupby(["period", "gl_category"])["line_subtotal"].sum()
        for (p, c), v in grp.items():
            if p in cat_billings and c in cat_billings[p]:
                cat_billings[p][c] = float(v)

    rows = []
    for period in periods:
        for ci, cat in enumerate(categories):
            # GL per category = its billings share scaled by a small per-category
            # bias, then split across accounts with random weights.
            target = cat_billings[period][cat] * float(cat_bias[ci])
            w = rng.random(n_accounts)
            w = w / w.sum()
            for ai, acc in enumerate(accounts):
                rows.append({
                    "period": period,
                    "account_id": acc,
                    "item_category": cat,
                    "customer_id": None,
                    "recognized_revenue_amt": round(float(target * w[ai]), 2),
                    "load_date": pd.Timestamp(period_start_date(period)),
                    "version": 1,
                })
    out = pd.DataFrame(rows)
    out["customer_id"] = out["customer_id"].astype("Int64")
    return out
