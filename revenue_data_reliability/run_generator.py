"""Interactive orchestrator for the synthetic revenue dataset generator.

Double-click or run:  python run_generator.py
Prompts for a seed (blank = random), then runs the generator with everything
performed inside data/.
"""
from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CONFIG = DATA / "config.yaml"
TEMP_CONFIG = DATA / ".run_config.yaml"


def main() -> int:
    try:
        raw = input("Enter seed (blank for random): ").strip()
    except EOFError:
        raw = ""
    if raw == "":
        seed = random.randint(1, 2**31 - 1)
        print(f"No seed given; using random seed: {seed}")
    else:
        try:
            seed = int(raw)
        except ValueError:
            print(f"Invalid seed '{raw}'. Must be an integer.")
            return 1

    if not CONFIG.exists():
        print(f"Missing config: {CONFIG}")
        return 1

    with open(CONFIG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["seed"] = seed
    cfg["name"] = f"run_{seed}"

    with open(TEMP_CONFIG, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)

    print(f"Running generator with seed={seed} ...")
    try:
        result = subprocess.run(
            ["uv", "run", "--project", "data", "python", "data/generate.py",
             "--config", "data/.run_config.yaml"],
            cwd=ROOT,
        )
    finally:
        try:
            TEMP_CONFIG.unlink(missing_ok=True)
        except Exception:
            pass

    if result.returncode != 0:
        print(f"Generator failed with exit code {result.returncode}.")
        return result.returncode

    print(f"Done. Output: data/runs/run_{seed}/")
    return 0


if __name__ == "__main__":
    rc = main()
    try:
        input("Press Enter to exit...")
    except EOFError:
        pass
    sys.exit(rc)