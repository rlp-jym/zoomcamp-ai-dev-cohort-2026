"""Defect injection for the synthetic revenue dataset."""

from __future__ import annotations

import numpy as np
import pandas as pd
from timeline import period_start_date

SEVERITY = {
    "orphaned_item_id": "high",
    "duplicate_invoice_line": "medium",
    "missing_customer_mapping": "critical",
    "stale_load": "high",
    "billings_gl_variance": "high",
    "restatement": "medium",
    "fx_gap": "high",
    "orphaned_backorder": "high",
    "phantom_return": "high",
}

RULE = {
    "orphaned_item_id": "VAL_FK_ITEM_EXISTS",
    "duplicate_invoice_line": "VAL_DUPLICATE_INVOICE_LINE",
    "missing_customer_mapping": "VAL_FK_CUSTOMER_EXISTS",
    "stale_load": "VAL_FRESHNESS_GL",
    "billings_gl_variance": "VAL_RECON_BILLINGS_GL",
    "restatement": "VAL_RESTATEMENT_DETECTED",
    "fx_gap": "VAL_FX_RATE_EXISTS",
    "orphaned_backorder": "VAL_FK_BACKORDER_ORDER_LINE",
    "phantom_return": "VAL_FK_RETURN_SHIPMENT",
}


def _period_of(values) -> np.ndarray:
    return pd.to_datetime(pd.Series(values)).dt.to_period("M").astype(str).to_numpy()


def inject_defects(cfg: dict, rng: np.random.Generator, data: dict, months: list[str]) -> list[dict]:
    defects_cfg = cfg["defects"]
    enabled_from = int(defects_cfg["enabled_from_month"])
    counts_per = int(defects_cfg["counts_per_type_per_month"])
    toggles = defects_cfg["toggles"]

    defects: list[dict] = []
    did = 0

    def log(dtype, table, row_key, month):
        nonlocal did
        did += 1
        defects.append({
            "defect_id": f"D-{did:04d}",
            "type": dtype,
            "table": table,
            "row_key": row_key,
            "severity": SEVERITY[dtype],
            "injected_month": month,
            "expected_detection_rule": RULE[dtype],
        })

    invoices = data["invoices"]
    invoice_lines = data["invoice_lines"]
    gl = data["gl_revenue"]

    # precompute period membership once
    inv_period = _period_of(invoices["invoice_date"])
    inv_id_to_period = dict(zip(invoices["invoice_id"].to_numpy(), inv_period, strict=False))
    il_invoice_ids = invoice_lines["invoice_id"].to_numpy()
    il_period = np.array([inv_id_to_period.get(x) for x in il_invoice_ids], dtype=object)

    month_to_il = {p: np.where(il_period == p)[0] for p in months}
    month_to_inv = {p: np.where(inv_period == p)[0] for p in months}
    month_to_gl = {p: np.where(gl["period"].to_numpy() == p)[0] for p in months}

    new_il_rows: list[pd.Series] = []
    new_gl_rows: list[pd.Series] = []
    new_backorder_rows: list[dict] = []
    new_return_rows: list[dict] = []

    next_il_id = int(invoice_lines["invoice_line_id"].max()) if not invoice_lines.empty else 0
    next_bo_id = int(data["backorders"]["backorder_id"].max()) if not data["backorders"].empty else 0
    next_ret_id = int(data["returns"]["return_id"].max()) if not data["returns"].empty else 0

    # fx_gap customer
    fx_gap_customer_id = None
    if toggles.get("fx_gap", False):
        cust = data["customers"]
        new_id = int(cust["customer_id"].max()) + 1
        new_row = cust.iloc[[0]].copy()
        new_row["customer_id"] = new_id
        new_row["currency"] = "ZZZ"
        data["customers"] = pd.concat([cust, new_row], ignore_index=True)
        fx_gap_customer_id = new_id

    for mi, period in enumerate(months):
        month_no = mi + 1
        if month_no < enabled_from:
            continue

        il_idx = month_to_il.get(period, np.array([], dtype=int))
        inv_idx = month_to_inv.get(period, np.array([], dtype=int))
        gl_idx = month_to_gl.get(period, np.array([], dtype=int))

        if toggles.get("orphaned_item_id", False) and il_idx.size:
            chosen = rng.choice(il_idx, size=min(counts_per, il_idx.size), replace=False)
            for i in chosen:
                data["invoice_lines"].loc[i, "item_id"] = 999999
                log("orphaned_item_id", "invoice_lines",
                    {"invoice_line_id": int(data["invoice_lines"].loc[i, "invoice_line_id"])}, month_no)

        if toggles.get("duplicate_invoice_line", False) and il_idx.size:
            chosen = rng.choice(il_idx, size=min(counts_per, il_idx.size), replace=False)
            for i in chosen:
                r = data["invoice_lines"].iloc[[i]].copy().reset_index(drop=True)
                next_il_id += 1
                r.loc[0, "invoice_line_id"] = next_il_id
                r.loc[0, "line_total"] = float(r.loc[0, "line_total"]) * 1.1
                new_il_rows.append(r)
                log("duplicate_invoice_line", "invoice_lines",
                    {"invoice_line_id": int(next_il_id)}, month_no)

        if toggles.get("missing_customer_mapping", False) and inv_idx.size:
            chosen = rng.choice(inv_idx, size=min(counts_per, inv_idx.size), replace=False)
            for i in chosen:
                data["invoices"].loc[i, "customer_id"] = 999999
                log("missing_customer_mapping", "invoices",
                    {"invoice_id": int(data["invoices"].loc[i, "invoice_id"])}, month_no)

        if toggles.get("stale_load", False) and gl_idx.size:
            chosen = rng.choice(gl_idx, size=min(counts_per, gl_idx.size), replace=False)
            for i in chosen:
                data["gl_revenue"].loc[i, "load_date"] = None
                log("stale_load", "gl_revenue",
                    {"period": str(data["gl_revenue"].loc[i, "period"]),
                     "account_id": int(data["gl_revenue"].loc[i, "account_id"]),
                     "item_category": str(data["gl_revenue"].loc[i, "item_category"])}, month_no)

        if toggles.get("billings_gl_variance", False) and gl_idx.size:
            cats = sorted(set(data["gl_revenue"].loc[gl_idx, "item_category"].tolist()))
            weights = defects_cfg.get("billings_gl_variance_category_weights")
            if weights is None or len(weights) != len(cats):
                weights = [1.0] * len(cats)
            weights = np.array(weights, dtype=float)
            weights = weights / weights.sum()
            target_cat = rng.choice(cats, p=weights)
            cat_rows = gl_idx[data["gl_revenue"].loc[gl_idx, "item_category"].to_numpy() == target_cat]
            for i in cat_rows:
                factor = 1.0 + float(rng.uniform(0.03, 0.08))
                data["gl_revenue"].loc[i, "recognized_revenue_amt"] = round(
                    float(data["gl_revenue"].loc[i, "recognized_revenue_amt"]) * factor, 2)
                log("billings_gl_variance", "gl_revenue",
                    {"period": str(data["gl_revenue"].loc[i, "period"]),
                     "account_id": int(data["gl_revenue"].loc[i, "account_id"]),
                     "item_category": str(data["gl_revenue"].loc[i, "item_category"])}, month_no)

        if toggles.get("restatement", False):
            prev_period = months[mi - 1] if mi > 0 else period
            prev_idx = month_to_gl.get(prev_period, np.array([], dtype=int))
            if prev_idx.size:
                chosen = rng.choice(prev_idx, size=min(counts_per, prev_idx.size), replace=False)
                for i in chosen:
                    r = data["gl_revenue"].iloc[[i]].copy().reset_index(drop=True)
                    r.loc[0, "version"] = int(r.loc[0, "version"]) + 1
                    r.loc[0, "load_date"] = pd.Timestamp(period_start_date(period))
                    factor = 1.0 + float(rng.uniform(-0.05, 0.05))
                    r.loc[0, "recognized_revenue_amt"] = round(float(r.loc[0, "recognized_revenue_amt"]) * factor, 2)
                    new_gl_rows.append(r)
                    log("restatement", "gl_revenue",
                        {"period": str(r.loc[0, "period"]), "account_id": int(r.loc[0, "account_id"]),
                         "item_category": str(r.loc[0, "item_category"])}, month_no)

        if toggles.get("fx_gap", False) and inv_idx.size and fx_gap_customer_id is not None:
            chosen = rng.choice(inv_idx, size=min(counts_per, inv_idx.size), replace=False)
            for i in chosen:
                data["invoices"].loc[i, "customer_id"] = fx_gap_customer_id
                log("fx_gap", "invoices",
                    {"invoice_id": int(data["invoices"].loc[i, "invoice_id"])}, month_no)

        if toggles.get("orphaned_backorder", False):
            for _ in range(counts_per):
                next_bo_id += 1
                if not data["backorders"].empty:
                    r = data["backorders"].iloc[[0]].copy().reset_index(drop=True)
                    r.loc[0, "backorder_id"] = next_bo_id
                    r.loc[0, "order_line_id"] = 999999
                    r.loc[0, "lost_qty"] = 1
                    new_backorder_rows.append(r)
                log("orphaned_backorder", "backorders", {"backorder_id": next_bo_id}, month_no)

        if toggles.get("phantom_return", False):
            for _ in range(counts_per):
                next_ret_id += 1
                if not data["returns"].empty:
                    r = data["returns"].iloc[[0]].copy().reset_index(drop=True)
                    r.loc[0, "return_id"] = next_ret_id
                    r.loc[0, "shipment_id"] = 999999
                    r.loc[0, "credit_amount"] = 1.0
                    new_return_rows.append(r)
                log("phantom_return", "returns", {"return_id": next_ret_id}, month_no)

    if new_il_rows:
        data["invoice_lines"] = pd.concat([data["invoice_lines"]] + new_il_rows, ignore_index=True)
    if new_gl_rows:
        data["gl_revenue"] = pd.concat([data["gl_revenue"]] + new_gl_rows, ignore_index=True)
    if new_backorder_rows:
        data["backorders"] = pd.concat([data["backorders"]] + new_backorder_rows, ignore_index=True)
    if new_return_rows:
        data["returns"] = pd.concat([data["returns"]] + new_return_rows, ignore_index=True)

    return defects
