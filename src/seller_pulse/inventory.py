"""The listings domain.

This is the listings table — "inventory" is the tool-facing name (see `docs/tools.md` §4),
not a separate concept. One module, one `Listing` type, one loader: two loaders over the same CSV
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
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

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


def listings_for(seller_id: str) -> list[Listing]:
    """The seller's listings, in catalog order. Another seller's listing never appears."""
    return [l for l in _LISTINGS.values() if l.seller_id == seller_id]


def catalog_size() -> int:
    """Return the number of SKUs in the catalog.

    The denominator `rag/stats.py` needs for "N of the catalog have no reviews" — the review
    store only knows how many SKUs *have* reviews, not how many exist.
    """
    return len(_LISTINGS)


SKU_PATTERN = re.compile(r"^SKU-\d{4}$")


def _error(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


def normalise_sku(sku: str) -> str:
    return sku.strip().upper()


def check_inventory_status(seller_id: str, sku: str) -> dict:
    """Return the docs/tools.md envelope. Never raises for bad input.

    `status` and `stock_qty` are reported verbatim — never derived from each other.
    """
    normalised = normalise_sku(sku)
    if not SKU_PATTERN.match(normalised):
        return _error("INVALID_SKU", f"'{sku.strip()}' is not a SKU. Expected the form SKU-1234.")

    listing = get_listing(normalised)
    # Another tenant's SKU is reported as unknown, so the error never reveals it exists.
    if listing is None or listing.seller_id != seller_id:
        return _error("UNKNOWN_SKU", f"{normalised} is not in your catalog.")

    return {
        "ok": True,
        "data": {
            "sku": listing.sku,
            "title": listing.title,
            "stock_qty": listing.stock_qty,
            "status": listing.status,
            "price_usd": listing.price_usd,
        },
    }


MIN_NAME_CHARS = 4
MAX_MATCHES = 3
FUZZY_CUTOFF = 0.8


def _norm_title(text: str) -> str:
    """Lowercase, alphanumerics only: `Boho Wall Hanging - Macrame` and `BohoWall hanging` align."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _fuzzy_score(query: str, title: str) -> float:
    """Best `difflib` ratio of ``query`` against any same-length-plus-one stretch of ``title``.

    A whole-title ratio punishes a partial name ("Boho Wal Hanging" vs the full title), so the
    query is slid along the title instead.
    """
    width = len(query) + 1
    starts = range(max(1, len(title) - width + 1))
    return max(SequenceMatcher(None, query, title[i : i + width]).ratio() for i in starts)


def find_listing(seller_id: str, name: str) -> dict:
    """Resolve a product name to the seller's SKUs. Never raises for bad input.

    A normalised substring match first (case, spaces and punctuation ignored); only when that
    finds nothing, the closest titles by sliding `difflib` ratio, so a typo still resolves. Several
    candidates are returned as-is for the caller to disambiguate.
    """
    query = _norm_title(name)
    if len(query) < MIN_NAME_CHARS:
        return _error("INVALID_NAME", f"'{name.strip()}' is too short to match a listing. Give more of the product name.")

    # Tenant filter first: another seller's listing is indistinguishable from no match.
    rows = [(listing, _norm_title(listing.title)) for listing in _LISTINGS.values() if listing.seller_id == seller_id]
    matches = [listing for listing, title in rows if query in title]
    if not matches:
        scored = sorted(
            ((_fuzzy_score(query, title), listing) for listing, title in rows),
            key=lambda pair: pair[0],
            reverse=True,
        )
        matches = [listing for score, listing in scored if score >= FUZZY_CUTOFF]
    if not matches:
        return _error("UNKNOWN_LISTING", f"No listing in your catalog matches '{name.strip()}'.")
    return {
        "ok": True,
        "data": {
            "matches": [{"sku": m.sku, "title": m.title, "status": m.status} for m in matches[:MAX_MATCHES]],
            "truncated": len(matches) > MAX_MATCHES,
        },
    }


MAX_LOW_STOCK = 20


def list_low_stock(seller_id: str, threshold: int) -> dict:
    """The seller's listings with `stock_qty <= threshold`, lowest stock first. Never raises.

    `status` and `stock_qty` are reported verbatim, as in `check_inventory_status`: an Active
    listing at 0 units is returned as-is, for the agent to flag. `count` is every match;
    `items` is capped at `MAX_LOW_STOCK`.
    """
    if threshold < 0:
        return _error("INVALID_THRESHOLD", f"{threshold} is not a stock level. Give a whole number, 0 or more.")

    # Tenant filter first: another seller's listing never appears in the result.
    low = sorted(
        (l for l in _LISTINGS.values() if l.seller_id == seller_id and l.stock_qty <= threshold),
        key=lambda l: (l.stock_qty, l.sku),
    )
    return {
        "ok": True,
        "data": {
            "threshold": threshold,
            "count": len(low),
            "items": [
                {"sku": l.sku, "title": l.title, "stock_qty": l.stock_qty, "status": l.status}
                for l in low[:MAX_LOW_STOCK]
            ],
            "truncated": len(low) > MAX_LOW_STOCK,
        },
    }
