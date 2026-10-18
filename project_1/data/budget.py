"""Budget reference table generation."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from timeline import _seasonal_multiplier, month_list


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
    categories = list(range(1, int(scale["item_categories"]) + 1))
    targets = scale["budget_growth_target_by_year"]
    # validate years
    years = sorted({int(p.split("-")[0]) for p in months})
    for y in years:
        if str(y) not in {str(k) for k in targets} and y not in targets:
            raise ValueError(f"missing budget_growth_target_by_year for year {y}")
    # trailing-12M billings per month (overall)
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

    year_billings = {}
    for y in years:
        ys = [p for p in months if int(p.split("-")[0]) == y]
        year_billings[y] = sum(monthly_billings[p] for p in ys)

    # trailing 12M for a year
    def trailing_billings(y: int) -> float:
        if (y - 1) in year_billings:
            return year_billings[y - 1]
        # first year: month-1 actuals * 12
        first_period = months[0]
        return monthly_billings.get(first_period, 0.0) * 12

    # prior-year gl revenue by (account, category)
    gl = gl.copy() if gl is not None else pd.DataFrame()
    if not gl.empty:
        gl["year"] = gl["period"].str[:4].astype(int)

    def pair_trailing(y: int) -> pd.Series:
        if (y - 1) in years and not gl.empty:
            sub = gl[gl["year"] == (y - 1)]
        elif not gl.empty:
            sub = gl[gl["period"] == months[0]]
        else:
            sub = pd.DataFrame()
        if sub.empty:
            # uniform
            idx = pd.MultiIndex.from_product([accounts, categories], names=["account_id", "item_category"])
            return pd.Series(1.0, index=idx)
        s = sub.groupby(["account_id", "item_category"])["recognized_revenue_amt"].sum()
        if (y - 1) not in years:
            s = s * 12
        # ensure all pairs
        full_idx = pd.MultiIndex.from_product([accounts, categories], names=["account_id", "item_category"])
        s = s.reindex(full_idx, fill_value=0.0)
        if s.sum() == 0:
            s = pd.Series(1.0, index=full_idx)
        return s

    top_custs = _top_customers(tx, 10)
    # customer billings shares
    cust_billings = {}
    if not invoices.empty and not lines.empty:
        merged = lines.merge(invoices[["invoice_id", "customer_id"]], on="invoice_id", how="left")
        merged["bill"] = merged["line_total"] - merged["tax_allocated"]
        cb = merged.groupby("customer_id")["bill"].sum()
        total_bill = cb.sum() if cb.sum() else 1.0
        cust_billings = {int(c): float(v) / float(total_bill) for c, v in cb.items()}
    top_shares = [cust_billings.get(c, 0.0) for c in top_custs]
    top_share_sum = sum(top_shares)

    # monthly pair totals
    # annual base per year
    annual_base = {}
    for y in years:
        tb = trailing_billings(y)
        target = targets[y] if y in targets else targets[str(y)]
        annual_base[y] = tb * float(target)

    # pair annual budget
    pair_annual = {}  # (y, a, c) -> amount
    for y in years:
        pt = pair_trailing(y)
        pt_total = float(pt.sum()) if float(pt.sum()) != 0 else 1.0
        for a in accounts:
            for c in categories:
                share = float(pt.get((a, c), 0.0)) / pt_total
                pair_annual[(y, a, c)] = annual_base[y] * share

    # monthly weights per year
    month_weight = {}
    for y in years:
        ys = [p for p in months if int(p.split("-")[0]) == y]
        ws = [_seasonal_multiplier(p, seasonality) for p in ys]
        wsum = sum(ws) if sum(ws) else 1.0
        for p, w in zip(ys, ws):
            month_weight[p] = w / wsum

    rows = []
    bid = 1
    for period in months:
        y = int(period.split("-")[0])
        ym = _parse_ym_local(period)
        for a in accounts:
            for c in categories:
                monthly_pair_total = pair_annual[(y, a, c)] * month_weight[period]
                # top customers
                top_amounts = []
                for cust, sh in zip(top_custs, top_shares):
                    amt = monthly_pair_total * sh
                    top_amounts.append((cust, amt))
                # round top amounts
                rounded_top = [(cust, round(amt, 2)) for cust, amt in top_amounts]
                top_sum_rounded = sum(a for _, a in rounded_top)
                remainder = round(monthly_pair_total - top_sum_rounded, 2)
                load_date = date(y, 1, 1)
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


def _parse_ym_local(s: str):
    y, m = s.split("-")
    return int(y), int(m)


def _period_date(s: str) -> date:
    y, m = s.split("-")
    return date(int(y), int(m), 1)
