"""The seller preference store: what the agent remembers between sessions.

Three keys, one JSON file per seller (`<root>/<seller_id>.json`) — the tenant partition by
file, mirroring `seller_id` in the CSVs. Schema and rationale: `docs/memory.md`.

Every update keeps the value it replaced in `previous_value`, so the agent can say "5 → 3"
instead of overriding a preference silently (`docs/requirements.md` §5).

No in-memory cache: `get_all()` reads the file every call, so a value saved by one process (or
earlier in the same session) is what the next read sees. Writes are atomic (temp file +
`os.replace`), so a crash mid-write leaves the old file intact. Concurrent writers are not
handled — last write wins; one seller, one app process in this prototype.
"""

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, get_args

PreferenceKey = Literal["notification_cadence", "reply_tone", "restock_threshold"]
PREFERENCE_KEYS: tuple[PreferenceKey, ...] = get_args(PreferenceKey)

# seller_id becomes a filename: no separators or dots, so it can't escape `root`.
_SELLER_ID = re.compile(r"[A-Za-z0-9_-]+")


@dataclass(frozen=True)
class Preference:
    key: PreferenceKey
    value: str
    updated_at: str  # ISO 8601, UTC
    previous_value: str | None


class PreferenceStore:
    def __init__(self, root: Path, seller_id: str):
        if not _SELLER_ID.fullmatch(seller_id):
            raise ValueError(f"seller_id {seller_id!r} is not a safe filename.")
        self._root = Path(root)
        self._path = self._root / f"{seller_id}.json"

    def get_all(self) -> dict[PreferenceKey, Preference]:
        """Every stored preference; empty when the seller has none yet.

        A corrupt file raises rather than reading as empty — an empty read would let the next
        `upsert` overwrite whatever the file held.
        """
        if not self._path.exists():
            return {}
        records = json.loads(self._path.read_text(encoding="utf-8"))
        return {key: Preference(key=key, **record) for key, record in records.items()}

    def upsert(self, key: PreferenceKey, value: str) -> Preference:
        """Store `value` under `key`, keeping the value it replaces in `previous_value`."""
        value = _validate(key, value)
        prefs = self.get_all()
        old = prefs.get(key)
        pref = Preference(
            key=key,
            value=value,
            updated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            previous_value=old.value if old else None,
        )
        prefs[key] = pref
        self._write(prefs)
        return pref

    def delete(self, key: PreferenceKey) -> Preference | None:
        """Remove `key`; return what was stored, or `None` if it wasn't set."""
        _check_key(key)
        prefs = self.get_all()
        removed = prefs.pop(key, None)
        if removed is not None:
            self._write(prefs)
        return removed

    def _write(self, prefs: dict[PreferenceKey, Preference]) -> None:
        records = {
            key: {k: v for k, v in asdict(pref).items() if k != "key"}
            for key, pref in prefs.items()
        }
        self._root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", dir=self._root, suffix=".tmp", delete=False, encoding="utf-8"
        ) as f:
            json.dump(records, f, indent=2)
        os.replace(f.name, self._path)


def _check_key(key: str) -> None:
    if key not in PREFERENCE_KEYS:
        raise ValueError(f"Unknown preference {key!r}; expected one of {', '.join(PREFERENCE_KEYS)}.")


def _validate(key: str, value: str) -> str:
    _check_key(key)
    value = value.strip()
    if not value:
        raise ValueError(f"{key} needs a value; use delete() to remove it.")
    if key == "restock_threshold":
        if not (value.isascii() and value.isdigit()):
            raise ValueError(f"restock_threshold must be a whole number of units ≥ 0, got {value!r}.")
        value = str(int(value))
    return value
