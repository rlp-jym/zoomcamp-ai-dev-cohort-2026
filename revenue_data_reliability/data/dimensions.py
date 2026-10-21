"""Dimension table generation for the synthetic revenue dataset."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from timeline import _parse_ym

CURRENCY_POOL = ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "SEK"]


def make_manufacturers(n: int, rng: np.random.Generator) -> pd.DataFrame:
    ids = np.arange(1, n + 1)
    codes = [f"M{i:03d}"[:3] for i in ids]
    cats = rng.choice(["Electronics", "Industrial", "Office", "Safety"], size=n)
    vendor_ids = rng.integers(1, 401, size=n)
    primary = rng.random(n) > 0.3
    return pd.DataFrame({
        "manufacturer_id": ids,
        "manufacturer_code": codes,
        "manufacturer_name": [f"Manufacturer {i}" for i in ids],
        "manufacturer_category": cats,
        "vendor_id": vendor_ids,
        "primary_vendor": primary,
    })


def make_distribution_centers(n: int, rng: np.random.Generator) -> pd.DataFrame:
    ids = np.arange(1, n + 1)
    regions = rng.choice(["North", "South", "East", "West"], size=n)
    ownership = rng.choice(["owned", "leased"], size=n)
    if n > 0:
        ownership = ownership.copy()
        ownership[0] = "leased" if ownership[0] == "owned" else "owned"
    return pd.DataFrame({
        "dc_id": ids,
        "dc_name": [f"DC {i}" for i in ids],
        "address_line1": [f"Addr {i}" for i in ids],
        "city": [f"City {i}" for i in ids],
        "state": rng.choice(["CA", "TX", "NY", "FL", "IL"], size=n),
        "zip": [f"{10000 + i}" for i in ids],
        "region": regions,
        "time_zone": rng.choice(["PT", "CT", "ET"], size=n),
        "capacity_units": rng.integers(10000, 100000, size=n),
        "target_utilization": np.round(rng.random(n) * 0.3 + 0.6, 2),
        "health_profile": rng.choice(["good", "fair"], size=n),
        "otd_tier": rng.choice(["A", "B", "C"], size=n),
        "revenue_tier": rng.choice(["high", "mid", "low"], size=n),
        "ownership_type": ownership,
        "square_footage": rng.integers(50000, 500000, size=n),
        "year_acquired": rng.integers(2000, 2024, size=n),
        "lease_rate_sqft_yr": np.round(rng.random(n) * 20 + 5, 2),
        "lease_escalator_pct": np.round(rng.random(n) * 0.05, 2),
        "property_value": np.round(rng.random(n) * 1e7 + 1e6, 2),
    })


def make_items(n: int, rng: np.random.Generator, manufacturers: pd.DataFrame) -> pd.DataFrame:
    ids = np.arange(1, n + 1)
    cats = rng.choice(["Electronics", "Industrial", "Office", "Safety", "Misc"], size=n)
    subcats = rng.choice(["A", "B", "C"], size=n)
    rng.choice(manufacturers["manufacturer_id"].to_numpy(), size=n)
    abc = rng.choice(["A", "B", "C"], size=n)
    xyz = rng.choice(["X", "Y", "Z"], size=n)
    lifecycle = rng.choice(["active", "active", "active", "retired"], size=n)
    sku = [f"SKU-{i:06d}" for i in ids]
    if n >= 2:
        sku[0] = "SKU-RENAMED-1"
        sku[1] = "SKU-RENAMED-2"
    cats = np.array(cats)
    if n >= 2:
        cats[0] = "RemappedCat"
        cats[1] = "RemappedCat"
    return pd.DataFrame({
        "item_id": ids,
        "item_sku": sku,
        "item_description": [f"Item {i}" for i in ids],
        "category": cats,
        "subcategory": subcats,
        "vendor_id": rng.integers(1, 401, size=n),
        "lead_time_days": rng.integers(1, 30, size=n),
        "length_in": np.round(rng.random(n) * 20 + 1, 2),
        "width_in": np.round(rng.random(n) * 20 + 1, 2),
        "height_in": np.round(rng.random(n) * 20 + 1, 2),
        "weight_lb": np.round(rng.random(n) * 50 + 0.1, 3),
        "cube_ft": np.round(rng.random(n) * 10 + 0.1, 4),
        "density_lb_per_cuft": np.round(rng.random(n) * 20 + 0.1, 4),
        "dimensional_weight_lb": np.round(rng.random(n) * 30 + 0.1, 4),
        "nmfc_class": rng.choice(["50", "55", "60"], size=n),
        "stackability_flag": rng.random(n) > 0.5,
        "hazmat_flag": rng.random(n) > 0.9,
        "abc_class": abc,
        "xyz_class": xyz,
        "lifecycle_stage": lifecycle,
        "complexity_class": rng.choice(["low", "med", "high"], size=n),
        "seasonality_class": rng.choice(["none", "spring", "summer"], size=n),
        "promo_eligible_flag": rng.random(n) > 0.5,
        "catalog_unit_price": np.round(rng.random(n) * 100 + 1, 4),
        "catalog_unit_cost": np.round(rng.random(n) * 50 + 0.5, 4),
        "catalog_shipping_cost_per_unit": np.round(rng.random(n) * 5, 4),
        "product_code": [f"P{i:05d}" for i in ids],
        "manufacturer_code": rng.choice(manufacturers["manufacturer_code"].to_numpy(), size=n),
        "category_code": rng.choice(["ELEC", "IND", "OFF", "SAF"], size=n),
        "master_category_code": rng.choice(["E", "I", "O", "S"], size=n),
        "harmonized_code": [f"H{i:06d}" for i in ids],
        "product_mix": rng.choice(["single", "bundle"], size=n),
        "perishable": rng.random(n) > 0.95,
        "domestic_vendor": rng.random(n) > 0.2,
        "country_of_origin": rng.choice(["US", "CN", "MX"], size=n),
        "selling_uom": rng.choice(["EA", "CS"], size=n),
        "ship_parcel": rng.choice(["yes", "no"], size=n),
        "single_use_plastic": rng.random(n) > 0.7,
        "recycled_product": rng.random(n) > 0.8,
        "hazmat_item": rng.random(n) > 0.9,
        "hazmat_class": rng.choice(["none", "3", "9"], size=n),
        "hazmat_class_description": rng.choice(["none", "flammable", "misc"], size=n),
        "msds_required": rng.random(n) > 0.9,
        "state_restricted": rng.random(n) > 0.95,
        "states_restricted": rng.choice(["", "CA"], size=n),
        "vendor_lead_time": rng.integers(1, 30, size=n),
        "vend_min_ord_qty": rng.integers(1, 50, size=n),
    })


def make_customers(cfg: dict, rng: np.random.Generator, dcs: pd.DataFrame) -> pd.DataFrame:
    scale = cfg["scale"]
    tl = cfg["timeline"]
    base = int(scale["base_customers"])
    adds = int(scale["growth_adds_per_month"])
    phases = tl["phases"]

    growth_months = []
    cur = 0
    for p in phases:
        for i in range(cur, cur + int(p["months"])):
            if p["name"] == "growth":
                growth_months.append(i + 1)
        cur += int(p["months"])

    decline_months = []
    cur = 0
    for p in phases:
        for i in range(cur, cur + int(p["months"])):
            if p["name"] == "decline":
                decline_months.append(i + 1)
        cur += int(p["months"])

    n_customers = base + len(growth_months) * adds
    ids = np.arange(1, n_customers + 1)
    open_months = np.ones(base, dtype=int)
    for gm in growth_months:
        open_months = np.concatenate([open_months, np.full(adds, gm, dtype=int)])

    churn_months = np.array([None] * n_customers, dtype=object)
    if decline_months:
        n_churn = int(n_customers * 0.20)
        churn_idx = rng.choice(n_customers, size=n_churn, replace=False)
        churn_months[churn_idx] = rng.choice(decline_months, size=n_churn)

    n_curr = int(scale["currencies"])
    curr_pool = CURRENCY_POOL[:n_curr]
    currencies = rng.choice(curr_pool, size=n_customers)

    # dtype=object keeps numpy from silently truncating the remapped label
    # to the width of the longest known segment ("remapped_segment" ->
    # "remapped_s" when the array is a fixed-width <U10 string).
    segment_names = cfg["scale"]["customer_segment_names"]
    segment_weights = np.array(cfg["scale"]["customer_segment_weights"], dtype=float)
    if len(segment_names) != len(segment_weights):
        raise ValueError(
            "customer_segment_names and customer_segment_weights must have the same length"
        )
    if segment_weights.sum() <= 0:
        raise ValueError("customer_segment_weights must sum to > 0")
    segment_weights = segment_weights / segment_weights.sum()
    segments = rng.choice(
        np.array(segment_names, dtype=object),
        size=n_customers,
        p=segment_weights,
    )
    n_remaps = int(cfg["dimension_drift"]["segment_remaps"])
    for i in range(min(n_remaps, n_customers)):
        segments[i] = "remapped_segment"
    regions = rng.choice(["North", "South", "East", "West"], size=n_customers)
    dc_ids = rng.choice(dcs["dc_id"].to_numpy(), size=n_customers)
    statuses = np.where(churn_months == None, "active", "churned")  # noqa: E711

    start_ym = tl["start_month"]

    def month_to_date(mi):
        y, m = _parse_ym(start_ym)
        mm = m + (mi - 1)
        yy = y + (mm - 1) // 12
        mm = (mm - 1) % 12 + 1
        return date(yy, mm, 1)

    open_dates = [month_to_date(int(x)) for x in open_months]
    churn_dates = [month_to_date(int(x)) if x is not None else None for x in churn_months]
    return pd.DataFrame({
        "customer_id": ids,
        "master_account_number": [f"MA{i:06d}" for i in ids],
        "sub_account_number": [f"SA{i:06d}" for i in ids],
        "customer_name": [f"Customer {i}" for i in ids],
        "segment": segments,
        "payment_behavior": rng.choice(["net30", "net60", "prepay"], size=n_customers),
        "activity_tier": rng.choice(["high", "med", "low"], size=n_customers),
        "address_line1": [f"Addr {i}" for i in ids],
        "city": [f"City {i}" for i in ids],
        "state": rng.choice(["CA", "TX", "NY", "FL", "IL"], size=n_customers),
        "zip": [f"{20000 + i}" for i in ids],
        "region": regions,
        "credit_limit": np.round(rng.random(n_customers) * 100000 + 1000, 2),
        "discount_percentage": np.round(rng.random(n_customers) * 0.2, 2),
        "account_open_date": open_dates,
        "home_dc_1": dc_ids,
        "home_dc_2": dc_ids,
        "home_dc_3": dc_ids,
        "account_open_day": [d.day for d in open_dates],
        "account_open_month": [d.month for d in open_dates],
        "account_open_year": [d.year for d in open_dates],
        "customer_status": statuses,
        "churn_date": churn_dates,
        "churn_day": [(d.day if d else None) for d in churn_dates],
        "churn_month": [(d.month if d else None) for d in churn_dates],
        "churn_year": [(d.year if d else None) for d in churn_dates],
        "currency": currencies,
    })


def generate_dimensions(cfg: dict, rng: np.random.Generator) -> dict:
    scale = cfg["scale"]
    manufacturers = make_manufacturers(int(scale["manufacturers"]), rng)
    dcs = make_distribution_centers(int(scale["distribution_centers"]), rng)
    items = make_items(int(scale["items"]), rng, manufacturers)
    customers = make_customers(cfg, rng, dcs)
    return {
        "manufacturers": manufacturers,
        "distribution_centers": dcs,
        "items": items,
        "customers": customers,
    }
