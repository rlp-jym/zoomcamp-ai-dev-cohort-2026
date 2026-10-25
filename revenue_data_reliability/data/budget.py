"""Budget reference table generation."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from timeline import _seasonal_multiplier


def _top_customers(tx: dict, n: int = 10) -> list[int]:
    invoices = tx.get("invoices", pd.DataFrame())
    lines = tx.get("invoice_lines", pd.DataFrame())
    if invoices.empty or lines.empty:
        return []
    merged = lines.merge(invoices[["invoice_id", "customer_id"]], on="invoice_id", how="left")
    merged["bill"] = merged["line_total"] - merged["tax_allocated"]
    cust = merged.groupby("customer_id")["bill"].sum()
    return [int(x) for x in cust.sort_values(ascending=False).head(n).index.tolist()]


def generate_budget(cfg: dict, rng: np.random.Generator, tx: dict, dims: dict, gl: pd.DataFrame, months: list[str]) -> pd.DataFrame:
    tl = cfg["timeline"]
    scale = cfg["scale"]
    seasonality = tl["seasonality"]
    accounts = list(range(1, int(scale["gl_accounts"]) + 1))
    categories = scale["item_category_names"]
    if len(categories) != int(scale["item_categories"]):
        raise ValueError("item_category_names length must equal item_categories")

    invoices = tx.get("invoices", pd.DataFrame())
    lines = tx.get("invoice_lines", pd.DataFrame())
    returns = tx.get("returns", pd.DataFrame())
    orders = tx.get("orders", pd.DataFrame())
    order_lines = tx.get("order_lines", pd.DataFrame())

    monthly_billings = {p: 0.0 for p in months}
    if not invoices.empty and not lines.empty:
        inv = invoices[["invoice_id", "invoice_date"]].copy()
        inv["period"] = pd.to_datetime(inv["invoice_date"]).dt.to_period("M").astype(str)
        merged = lines.merge(inv[["invoice_id", "period"]], on="invoice_id", how="left")
        merged["bill"] = merged["line_total"] - merged["tax_allocated"]
        grp = merged.groupby("period")["bill"].sum()
        for p, v in grp.items():
            if p in monthly_billings:
                monthly_billings[p] = float(v)

    # subtract returns credit allocated by originating period
    if not returns.empty and not order_lines.empty and not orders.empty:
        r = returns.merge(order_lines[["order_line_id", "order_id"]], on="order_line_id", how="left")
        r = r.merge(orders[["order_id", "order_date"]], on="order_id", how="left")
        r["period"] = pd.to_datetime(r["order_date"]).dt.to_period("M").astype(str)
        rg = r.groupby("period")["credit_amount"].sum()
        for p, v in rg.items():
            if p in monthly_billings:
                monthly_billings[p] -= float(v)

    # ---- one trailing-window target ---------------------------------------
    # The plan is a single trailing figure for the whole window, spread across
    # the months by seasonality. Splitting it by calendar year produced a
    # cliff: the first year's target was annualised from a partial year, and
    # the next year inherited that partial sum as its "trailing" base.
    target_ratio = float((cfg.get("budget") or {}).get("target_ratio", 1.0))
    if target_ratio <= 0:
        raise ValueError("budget.target_ratio must be positive")
    variance = cfg.get("variance") or {}
    category_shift = {
        str(k): float(v) for k, v in (variance.get("category_plan_shift") or {}).items()
    }

    # ---- allocation shares -------------------------------------------------
    top_custs = _top_customers(tx, 10)
    cust_billings = {}
    if not invoices.empty and not lines.empty:
        merged = lines.merge(invoices[["invoice_id", "customer_id"]], on="invoice_id", how="left")
        merged["bill"] = merged["line_total"] - merged["tax_allocated"]
        cb = merged.groupby("customer_id")["bill"].sum()
        total_bill = cb.sum() if cb.sum() else 1.0
        cust_billings = {int(c): float(v) / float(total_bill) for c, v in cb.items()}
    top_shares = [cust_billings.get(c, 0.0) for c in top_custs]

    gl_frame = gl.copy() if gl is not None else pd.DataFrame()
    full_idx = pd.MultiIndex.from_product(
        [accounts, categories], names=["account_id", "item_category"]
    )
    if not gl_frame.empty:
        pair_totals = gl_frame.groupby(["account_id", "item_category"])[
            "recognized_revenue_amt"
        ].sum()
    else:
        pair_totals = pd.Series(dtype=float)
    pair_totals = pair_totals.reindex(full_idx, fill_value=0.0)
    # The dashboard compares the plan against recognised GL revenue, so the
    # plan total is derived from the same measure. Fall back to billings only
    # when the GL frame is empty.
    gl_total = float(pair_totals.sum())
    if gl_total <= 0:
        pair_totals = pd.Series(1.0, index=full_idx)
        gl_total = float(sum(monthly_billings.values()))
    target_total = gl_total * target_ratio
    # The plan mix differs from actual by the configured shift, so the category
    # bridge produces both positive and negative contributions.
    if category_shift:
        multipliers = pd.Series(
            [category_shift.get(cat, 1.0) for (_, cat) in pair_totals.index],
            index=pair_totals.index,
        )
        shifted = pair_totals * multipliers
        if float(shifted.sum()) > 0:
            pair_totals = shifted
    pair_share = pair_totals / float(pair_totals.sum())

    weights = {p: _seasonal_multiplier(p, seasonality) for p in months}
    weight_sum = sum(weights.values()) or 1.0

    rows = []
    bid = 1
    for period in months:
        y = int(period.split("-")[0])
        month_target = target_total * (weights[period] / weight_sum)
        load_date = date(y, 1, 1)
        for a in accounts:
            for c in categories:
                monthly_pair_total = month_target * float(pair_share.get((a, c), 0.0))
                top_amounts = []
                for cust, sh in zip(top_custs, top_shares, strict=False):
                    amt = monthly_pair_total * sh
                    top_amounts.append((cust, amt))
                rounded_top = [(cust, round(amt, 2)) for cust, amt in top_amounts]
                top_sum_rounded = sum(a for _, a in rounded_top)
                remainder = round(monthly_pair_total - top_sum_rounded, 2)
                for cust, amt in rounded_top:
                    rows.append({
                        "budget_id": bid,
                        "period": _period_date(period),
                        "account_id": a,
                        "item_category": c,
                        "customer_id": cust,
                        "budget_revenue_amt": float(amt),
                        "load_date": load_date,
                        "version": 1,
                    })
                    bid += 1
                rows.append({
                    "budget_id": bid,
                    "period": _period_date(period),
                    "account_id": a,
                    "item_category": c,
                    "customer_id": None,
                    "budget_revenue_amt": float(remainder),
                    "load_date": load_date,
                    "version": 1,
                })
                bid += 1

    df = pd.DataFrame(rows)
    df["customer_id"] = df["customer_id"].astype("Int64")
    return df


def _period_date(s: str) -> date:
    y, m = s.split("-")
    return date(int(y), int(m), 1)
