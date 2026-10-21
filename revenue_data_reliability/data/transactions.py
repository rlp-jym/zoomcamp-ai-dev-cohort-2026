"""Transactional generation for the synthetic revenue dataset."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from timeline import _parse_ym, month_list, monthly_order_counts, period_start_date


def _active_customers(customers: pd.DataFrame, ps: pd.Timestamp) -> np.ndarray:
    c = customers.copy()
    c["account_open_date"] = pd.to_datetime(c["account_open_date"])
    c["churn_date"] = pd.to_datetime(c["churn_date"], errors="coerce")
    mask = c["account_open_date"] <= ps
    mask &= c["churn_date"].isna() | (c["churn_date"] > ps)
    return c.loc[mask, "customer_id"].to_numpy()


def generate_transactions(cfg: dict, rng: np.random.Generator, dims: dict) -> dict[str, pd.DataFrame]:
    customers = dims["customers"]
    items = dims["items"]
    dcs = dims["distribution_centers"]

    tl = cfg["timeline"]
    months = month_list(tl["start_month"], int(tl["n_months"]))
    counts = monthly_order_counts(cfg)

    item_ids = items["item_id"].to_numpy()
    price_map = dict(zip(items["item_id"], items["catalog_unit_price"], strict=False))

    counters = {
        "order": 0, "order_line": 0, "shipment": 0, "shipment_line": 0,
        "invoice": 0, "invoice_line": 0, "ar": 0, "backorder": 0, "return": 0,
    }

    orders_list, ol_list, ship_list, sl_list = [], [], [], []
    inv_list, il_list, ar_list, bo_list, ret_list = [], [], [], [], []

    for mi, period in enumerate(months):
        n = counts[mi]
        y, m = _parse_ym(period)
        ps = pd.Timestamp(period_start_date(period))

        active_ids = _active_customers(customers, ps)
        if len(active_ids) == 0:
            active_ids = customers["customer_id"].to_numpy()

        cust_choice = rng.choice(active_ids, size=n)
        dc_choice = rng.choice(dcs["dc_id"].to_numpy(), size=n)
        days = rng.integers(1, 29, size=n)
        order_dates = [date(y, m, int(d)) for d in days]
        n_lines = rng.integers(1, 5, size=n)

        order_ids = np.arange(counters["order"] + 1, counters["order"] + n + 1)
        counters["order"] += n

        orders_df = pd.DataFrame({
            "order_id": order_ids,
            "customer_id": cust_choice,
            "dc_id": dc_choice,
            "order_date": order_dates,
        })
        orders_list.append(orders_df)

        # order lines
        line_counts = n_lines
        order_id_rep = np.repeat(order_ids, line_counts)
        n_total_lines = int(line_counts.sum())
        item_choice = rng.choice(item_ids, size=n_total_lines)
        qty_ordered = rng.integers(1, 10, size=n_total_lines)

        ol_ids = np.arange(counters["order_line"] + 1, counters["order_line"] + n_total_lines + 1)
        counters["order_line"] += n_total_lines

        ol_df = pd.DataFrame({
            "order_line_id": ol_ids,
            "order_id": order_id_rep,
            "item_id": item_choice,
            "qty_ordered": qty_ordered,
        })

        # enforce (order_id, item_id) uniqueness
        seen: set[tuple[int, Any]] = set()
        dup_mask = np.zeros(n_total_lines, dtype=bool)
        for idx, (oid, iid) in enumerate(zip(ol_df["order_id"], ol_df["item_id"], strict=False)):
            key = (int(oid), int(iid))
            if key in seen:
                dup_mask[idx] = True
            else:
                seen.add(key)
        if dup_mask.any():
            ol_df.loc[dup_mask, "item_id"] = rng.choice(item_ids, size=int(dup_mask.sum()))
        ol_df["unit_price"] = ol_df["item_id"].map(price_map)
        ol_df["extended_price"] = ol_df["qty_ordered"] * ol_df["unit_price"]
        ol_list.append(ol_df)

        # shipments
        ship_date_offsets = rng.integers(0, 6, size=n)
        ship_dates = [date(y, m, int(d)) + timedelta(days=int(off)) for d, off in zip(days, ship_date_offsets, strict=False)]
        shipment_ids = np.arange(counters["shipment"] + 1, counters["shipment"] + n + 1)
        counters["shipment"] += n
        shipments_df = pd.DataFrame({
            "shipment_id": shipment_ids,
            "order_id": order_ids,
            "ship_date": ship_dates,
        })
        ship_list.append(shipments_df)

        order_to_shipment = dict(zip(order_ids, shipment_ids, strict=False))
        shp_id_rep = np.array([order_to_shipment[int(oid)] for oid in ol_df["order_id"]])

        qty_shipped = np.minimum(
            ol_df["qty_ordered"].to_numpy(),
            rng.integers(0, ol_df["qty_ordered"].to_numpy() + 1),
        )

        sl_ids = np.arange(counters["shipment_line"] + 1, counters["shipment_line"] + n_total_lines + 1)
        counters["shipment_line"] += n_total_lines
        sl_df = pd.DataFrame({
            "shipment_line_id": sl_ids,
            "shipment_id": shp_id_rep,
            "order_line_id": ol_df["order_line_id"].to_numpy(),
            "qty_shipped": qty_shipped,
        })
        sl_list.append(sl_df)

        # backorders
        under = qty_shipped < ol_df["qty_ordered"].to_numpy()
        if under.any():
            bo_n = int(under.sum())
            bo_ids = np.arange(counters["backorder"] + 1, counters["backorder"] + bo_n + 1)
            counters["backorder"] += bo_n
            bo_df = pd.DataFrame({
                "backorder_id": bo_ids,
                "order_line_id": ol_df.loc[under, "order_line_id"].to_numpy(),
                "lost_qty": (ol_df.loc[under, "qty_ordered"].to_numpy() - qty_shipped[under]),
            })
            bo_list.append(bo_df)

        # invoices
        inv_ids = np.arange(counters["invoice"] + 1, counters["invoice"] + n + 1)
        counters["invoice"] += n
        inv_dates = ship_dates
        invoices_df = pd.DataFrame({
            "invoice_id": inv_ids,
            "order_id": order_ids,
            "customer_id": cust_choice,
            "invoice_date": inv_dates,
        })
        inv_list.append(invoices_df)

        order_to_invoice = dict(zip(order_ids, inv_ids, strict=False))
        inv_id_rep = np.array([order_to_invoice[int(oid)] for oid in ol_df["order_id"]])

        line_subtotal = qty_shipped * ol_df["unit_price"].to_numpy()
        il_ids = np.arange(counters["invoice_line"] + 1, counters["invoice_line"] + n_total_lines + 1)
        counters["invoice_line"] += n_total_lines
        freight = np.round(rng.random(n_total_lines) * 5, 2)
        tax = np.round(line_subtotal * 0.08, 2)
        discount = np.round(line_subtotal * 0.05, 2)
        line_total = line_subtotal + freight + tax - discount
        il_df = pd.DataFrame({
            "invoice_line_id": il_ids,
            "invoice_id": inv_id_rep,
            "item_id": ol_df["item_id"].to_numpy(),
            "qty_shipped": qty_shipped,
            "unit_price": ol_df["unit_price"].to_numpy(),
            "line_subtotal": line_subtotal,
            "freight_allocated": freight,
            "tax_allocated": tax,
            "discount_allocated": discount,
            "line_total": line_total,
        })
        il_list.append(il_df)

        # ar_ledger 1:1 with invoices
        ar_ids = np.arange(counters["ar"] + 1, counters["ar"] + n + 1)
        counters["ar"] += n
        # outstanding balance per invoice
        subtotals_by_inv = il_df.groupby("invoice_id")["line_subtotal"].sum()
        outstanding = subtotals_by_inv.reindex(inv_ids).fillna(0).to_numpy()
        ar_df = pd.DataFrame({
            "ar_id": ar_ids,
            "invoice_id": inv_ids,
            "outstanding_balance": outstanding,
        })
        ar_list.append(ar_df)

        # returns (small sample)
        ret_mask = rng.random(n_total_lines) < 0.05
        if ret_mask.any():
            ret_n = int(ret_mask.sum())
            ret_ids = np.arange(counters["return"] + 1, counters["return"] + ret_n + 1)
            counters["return"] += ret_n
            ret_df = pd.DataFrame({
                "return_id": ret_ids,
                "order_line_id": ol_df.loc[ret_mask, "order_line_id"].to_numpy(),
                "shipment_id": shp_id_rep[ret_mask],
                "credit_amount": line_subtotal[ret_mask] * 0.5,
            })
            ret_list.append(ret_df)

    def concat(lst: list[pd.DataFrame]) -> pd.DataFrame:
        return pd.concat(lst, ignore_index=True) if lst else pd.DataFrame()

    return {
        "orders": concat(orders_list),
        "order_lines": concat(ol_list),
        "shipments": concat(ship_list),
        "shipment_lines": concat(sl_list),
        "invoices": concat(inv_list),
        "invoice_lines": concat(il_list),
        "ar_ledger": concat(ar_list),
        "backorders": concat(bo_list),
        "returns": concat(ret_list),
    }
