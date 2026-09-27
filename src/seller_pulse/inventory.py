"""The listings domain.

This is the listings table — "inventory" is the tool-facing name (see `plan/03`), not a
separate concept. One module, one `Listing` type, one loader: two loaders over the same CSV
would give two structurally-identical types that a reader could never tell apart at a glance.

`status` is the source of truth for stock state, not a threshold computed from `stock_qty`.
Two rows (SKU-1013, SKU-1020) deliberately have `stock_qty == 0` with `status: Active` — a
seeded edge case a policy rule and specific reviews depend on (see `plan/rag-03-seller-id-column.md`).
Do not "fix" that by deriving status from quantity.

The CSV is loaded once at import into a module-level dict keyed by SKU. That trades away
lazy loading: importing this module with a missing or malformed CSV fails at import time, not
at first lookup. Acceptable for a static, committed 150-row file.
"""

import csv
from dataclasses import dataclass

from seller_pulse.config import DEFAULT_LISTINGS_PATH


@dataclass(frozen=True)
class Listing:
    seller_id: str
    sku: str
    title: str
    category: str
    price_usd: float
    stock_qty: int
    status: str


def _load_listings(path) -> dict[str, Listing]:
    with open(path, newline="", encoding="utf-8") as f:
        return {
            row["sku"]: Listing(
                seller_id=row["seller_id"],
                sku=row["sku"],
                title=row["title"],
                category=row["category"],
                price_usd=float(row["price_usd"]),
                stock_qty=int(row["stock_qty"]),
                status=row["status"],
            )
            for row in csv.DictReader(f)
        }


_LISTINGS: dict[str, Listing] = _load_listings(DEFAULT_LISTINGS_PATH)


def get_listing(sku: str) -> Listing | None:
    """Return the `Listing` for `sku`, or `None` if it isn't in the catalog.

    An absent SKU is a valid answer, not an error condition.
    """
    return _LISTINGS.get(sku)
