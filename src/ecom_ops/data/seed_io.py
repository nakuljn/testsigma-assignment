"""Load, validate, and persist seed JSON files under data/seed/."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ecom_ops.config.settings import DATA_DIR, ROOT_DIR

SEED_FILES = ("catalog.json", "inventory.json", "sales_history.json", "reviews.json")
DEMO_SEED_DIR = ROOT_DIR / "data" / "seed" / "demo"
FULL_SEED_DIR = ROOT_DIR / "data" / "seed" / "full"
SeedProfile = str  # "demo" | "full"


def copy_seed_profile(profile: SeedProfile) -> None:
    """Replace active data/seed/*.json from demo (6 SKUs) or full (15 SKUs) profile."""
    src = DEMO_SEED_DIR if profile == "demo" else FULL_SEED_DIR
    if not src.is_dir():
        raise FileNotFoundError(f"Seed profile directory missing: {src}")
    for name in SEED_FILES:
        shutil.copy2(src / name, DATA_DIR / name)


def active_sku_count() -> int:
    catalog = load_seed_file("catalog.json")
    return len(catalog) if isinstance(catalog, list) else 0


def load_seed_file(name: str) -> Any:
    path = DATA_DIR / name
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_all_seed() -> dict[str, Any]:
    return {name: load_seed_file(name) for name in SEED_FILES}


def validate_catalog(data: list) -> list[str]:
    errors = []
    if not isinstance(data, list):
        return ["catalog must be a JSON array"]
    required = {"id", "name", "category", "cost", "current_price"}
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            errors.append(f"catalog[{i}]: must be an object")
            continue
        missing = required - set(row.keys())
        if missing:
            errors.append(f"catalog[{i}]: missing fields {missing}")
    return errors


def validate_inventory(data: list) -> list[str]:
    errors = []
    if not isinstance(data, list):
        return ["inventory must be a JSON array"]
    required = {"sku", "stock_level", "reorder_point", "lead_time_days"}
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            errors.append(f"inventory[{i}]: must be an object")
            continue
        missing = required - set(row.keys())
        if missing:
            errors.append(f"inventory[{i}]: missing fields {missing}")
    return errors


def validate_sales_history(data: dict) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return ["sales_history must be a JSON object {sku: [daily units...]}"]
    for sku, series in data.items():
        if not isinstance(series, list):
            errors.append(f"sales_history[{sku}]: must be an array of numbers")
    return errors


def validate_reviews(data: list) -> list[str]:
    errors = []
    if not isinstance(data, list):
        return ["reviews must be a JSON array"]
    for i, row in enumerate(data):
        if not isinstance(row, dict) or "sku" not in row:
            errors.append(f"reviews[{i}]: must include sku")
    return errors


_VALIDATORS = {
    "catalog.json": validate_catalog,
    "inventory.json": validate_inventory,
    "sales_history.json": validate_sales_history,
    "reviews.json": validate_reviews,
}


def validate_seed_file(name: str, data: Any) -> list[str]:
    if name not in _VALIDATORS:
        return [f"Unknown seed file: {name}"]
    return _VALIDATORS[name](data)


def save_seed_file(name: str, data: Any, backup: bool = True) -> Path:
    """Validate and write seed JSON to data/seed/. Returns path written."""
    errors = validate_seed_file(name, data)
    if errors:
        raise ValueError("; ".join(errors))

    path = DATA_DIR / name
    if backup and path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    return path
