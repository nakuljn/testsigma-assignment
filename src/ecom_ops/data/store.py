"""
MockStore — the single source of truth for store data.

Loads seed JSON files on init.
Exposes read APIs (return copies so agents can't mutate internal state).
Is the ONLY place that commits writes (price changes, restock orders, etc.).
"""

from __future__ import annotations

import json
import copy
from pathlib import Path
from typing import Optional

from ecom_ops.config.settings import DATA_DIR


class MockStore:
    def __init__(self, data_dir: Optional[Path] = None):
        self._dir = data_dir or DATA_DIR
        self._catalog: list[dict] = self._load("catalog.json")
        self._inventory: list[dict] = self._load("inventory.json")
        self._sales_history: dict = self._load("sales_history.json")
        self._reviews: list[dict] = self._load("reviews.json")
        self._committed_changes: list[dict] = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self, filename: str) -> list | dict:
        path = self._dir / filename
        with open(path) as f:
            return json.load(f)

    # ------------------------------------------------------------------
    # Read APIs — return deep copies so agents can't mutate store state
    # ------------------------------------------------------------------

    def get_catalog(self) -> list[dict]:
        return copy.deepcopy(self._catalog)

    def get_inventory(self) -> list[dict]:
        return copy.deepcopy(self._inventory)

    def get_sales_history(self) -> dict:
        return copy.deepcopy(self._sales_history)

    def get_reviews(self) -> list[dict]:
        return copy.deepcopy(self._reviews)

    def get_committed_changes(self) -> list[dict]:
        return copy.deepcopy(self._committed_changes)

    # ------------------------------------------------------------------
    # Write APIs — only the Orchestrator should call these
    # ------------------------------------------------------------------

    def commit_price_change(self, sku: str, old_price: float, new_price: float, driver: str) -> dict:
        for item in self._catalog:
            if item["id"] == sku:
                item["current_price"] = new_price
                break
        change = {
            "type": "price_change",
            "sku": sku,
            "old_price": old_price,
            "new_price": new_price,
            "driver": driver,
        }
        self._committed_changes.append(change)
        return change

    def commit_restock(self, sku: str, qty: int, urgency: str) -> dict:
        for item in self._inventory:
            if item["sku"] == sku:
                item["stock_level"] += qty
                break
        change = {
            "type": "restock_order",
            "sku": sku,
            "qty_ordered": qty,
            "urgency": urgency,
        }
        self._committed_changes.append(change)
        return change

    def commit_campaign(self, sku: str, channel: str, subject: str) -> dict:
        change = {
            "type": "campaign_launched",
            "sku": sku,
            "channel": channel,
            "subject": subject,
        }
        self._committed_changes.append(change)
        return change

    # ------------------------------------------------------------------
    # Convenience lookups
    # ------------------------------------------------------------------

    def get_product(self, sku: str) -> Optional[dict]:
        return next((p for p in self._catalog if p["id"] == sku), None)

    def get_inventory_record(self, sku: str) -> Optional[dict]:
        return next((r for r in self._inventory if r["sku"] == sku), None)

    def get_reviews_for_sku(self, sku: str) -> Optional[dict]:
        return next((r for r in self._reviews if r["sku"] == sku), None)
