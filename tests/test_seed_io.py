"""Tests for seed data load/save/validate."""
import json
import pytest
from pathlib import Path

from ecom_ops.data.seed_io import (
    load_seed_file,
    save_seed_file,
    validate_catalog,
    validate_inventory,
)


def test_load_catalog_has_15_skus():
    catalog = load_seed_file("catalog.json")
    assert len(catalog) == 15


def test_validate_catalog_rejects_bad_row():
    errors = validate_catalog([{"id": "X"}])
    assert errors


def test_save_seed_roundtrip(tmp_path, monkeypatch):
    import ecom_ops.config.settings as settings
    import ecom_ops.data.seed_io as seed_io

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(seed_io, "DATA_DIR", tmp_path)

    data = [{"id": "SKU-TEST", "name": "Test", "category": "X", "cost": 1.0, "current_price": 2.0}]
    path = save_seed_file("catalog.json", data)
    assert path.exists()
    loaded = json.loads(path.read_text())
    assert loaded[0]["id"] == "SKU-TEST"


def test_save_inventory_validates():
    with pytest.raises(ValueError):
        save_seed_file("inventory.json", [{"sku": "X"}])  # missing fields
