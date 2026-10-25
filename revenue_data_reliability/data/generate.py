"""Synthetic Revenue Dataset Generator.

Single entry point:
    python data/generate.py --config data/config.yaml

Module layout:
    config.py       - config loading/validation
    timeline.py     - month/phase/seasonality + volume formulas
    dimensions.py   - dimension tables
    transactions.py - transactional tables (clean months)
    gl_fx.py        - gl_revenue + fx_rates
    defects.py      - defect injection + defect log
    manifest.py     - manifest assembly (Section 8)
    output.py       - run directory + Parquet/JSON writing (Section 9)
"""

from __future__ import annotations

import argparse
import os
from datetime import date

import numpy as np
from config import load_config
from dimensions import generate_dimensions
from timeline import month_list, month_span_ending_previous_month, monthly_order_counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--years-to-backtrack", "--years_to_backtrack", dest="years_to_backtrack", type=int, default=None)
    parser.add_argument("--budget-ratio", "--budget_ratio", dest="budget_ratio", type=float, default=None)
    parser.add_argument("--trend-per-month", "--trend_per_month", dest="trend_per_month", type=float, default=None)
    args = parser.parse_args()
    cfg = load_config(args.config)
    if args.seed is not None:
        cfg["seed"] = args.seed
    if args.budget_ratio is not None:
        cfg.setdefault("budget", {})["target_ratio"] = args.budget_ratio
    if args.trend_per_month is not None:
        cfg["timeline"]["trend_per_month"] = args.trend_per_month
    y = args.years_to_backtrack
    if y is None:
        env_y = os.getenv("YEARS_TO_BACKTRACK")
        if env_y not in (None, ""):
            y = int(env_y)
    n_months = int(y) * 12 if y is not None else int(cfg["timeline"]["n_months"])
    start_month, end_month = month_span_ending_previous_month(n_months, date.today())
    cfg["timeline"]["start_month"] = start_month
    cfg["timeline"]["n_months"] = n_months
    print(f"timeline start={start_month} end={end_month} months={n_months}")
    rng = np.random.default_rng(int(cfg["seed"]))

    counts = monthly_order_counts(cfg)
    print(f"months={len(counts)} total_orders={sum(counts)} first={counts[0]} last={counts[-1]}")

    dims = generate_dimensions(cfg, rng)
    for k, v in dims.items():
        print(k, len(v))

    from transactions import generate_transactions
    tx = generate_transactions(cfg, rng, dims)
    for k, v in tx.items():
        print(k, len(v))

    from gl_fx import generate_fx_rates, generate_gl_revenue
    gl = generate_gl_revenue(cfg, rng, tx, dims.get("items"))
    from budget import generate_budget
    months = month_list(cfg["timeline"]["start_month"], int(cfg["timeline"]["n_months"]))
    bud = generate_budget(cfg, rng, tx, dims, gl, months)
    fx = generate_fx_rates(cfg, rng)
    print("gl_revenue", len(gl))
    print("budget", len(bud))
    print("fx_rates", len(fx))

    data = {
        "customers": dims["customers"],
        "items": dims["items"],
        "distribution_centers": dims["distribution_centers"],
        "manufacturers": dims["manufacturers"],
        **tx,
        "gl_revenue": gl,
        "budget": bud,
        "fx_rates": fx,
    }

    from defects import inject_defects
    months = month_list(cfg["timeline"]["start_month"], int(cfg["timeline"]["n_months"]))
    defects = inject_defects(cfg, rng, data, months)
    print("defects", len(defects))

    from output import write_run
    out_dir = write_run(cfg, data, defects, months)
    print("output", out_dir)


if __name__ == "__main__":
    main()
