# Memory: the seller preference store

What SellerPulse remembers about a seller between visits, and how it is stored. Code:
`src/seller_pulse/memory.py` (`PreferenceStore`). Requirement: `docs/requirements.md` §4 —
persist notification cadence, reply tone and restock threshold across at least two sessions —
and §5 — respect stored preferences and never silently override them.

## 1. The three preferences

| Key | Value | Validation | Example (source) |
|---|---|---|---|
| `notification_cadence` | free text: when to alert, and on what | non-blank | `weekly, every Friday: best-sellers at or below the restock threshold` (SQ-05) |
| `reply_tone` | free text: how review-reply drafts should read | non-blank | `short and warm, no emojis` (SQ-16) |
| `restock_threshold` | whole number of units, as a string | ASCII digits only, ≥ 0; stored normalised (`"05"` → `"5"`) | `3`, set by SQ-22 (SQ-05 saves no threshold, so it starts unset) |

Any other key is rejected (`ValueError`). There is no "blank value" preference — removing one
is `delete(key)`.

## 2. Record schema

```python
@dataclass(frozen=True)
class Preference:
    key: PreferenceKey          # one of the three above
    value: str
    updated_at: str             # ISO 8601, UTC, seconds precision
    previous_value: str | None  # the value this one replaced; None on first write
```

`PreferenceStore(root, seller_id)` exposes:

- `get_all() -> dict[key, Preference]` — empty dict when the seller has nothing stored yet.
- `upsert(key, value) -> Preference` — validates, writes, returns the stored record.
- `delete(key) -> Preference | None` — returns what was removed, or `None` if it wasn't set.

## 3. File layout

One JSON file per seller: `<MEMORY_PATH>/<seller_id>.json`, where `MEMORY_PATH` defaults to
`data/memory/`. The file is the tenant partition, the same way `seller_id` partitions the CSVs.
A store can only see its own seller's file. `seller_id` must match `[A-Za-z0-9_-]+`, so it
can't point outside the directory.

The file is a JSON object keyed by preference (the key isn't repeated inside the record):

```json
{
  "restock_threshold": {
    "value": "3",
    "updated_at": "2026-10-15T04:09:20+00:00",
    "previous_value": "5"
  }
}
```

`data/memory/` is not gitignored. Note that the live two-session check (w2-15) starts from an
empty directory.

## 4. Why `previous_value`

§5 forbids overriding a preference silently. When SQ-22 changes the threshold, the agent has to
say the change out loud ("unset → 3" for SQ-22, "5 → 3" for a later change), and it can only do
that if the old value is still on hand.
`upsert` always returns the record with `previous_value` filled in, so whatever confirms an
update has both numbers. Only one step of history is kept; this is not an audit log.

## 5. Behaviour guarantees

- **Read every call, no cache.** `get_all()` reads the file each time, so a preference saved
  earlier in the session, or by an earlier app process, is visible on the next read.
- **Atomic writes.** Each write goes to a temp file in the same directory, then `os.replace`.
  A crash mid-write leaves the previous file intact.
- **Corrupt file fails loudly.** An unparseable file raises; it isn't read as empty. Reading
  it as empty would let the next `upsert` overwrite whatever the file held.
- **Single writer assumed.** Concurrent writers aren't locked; the last write wins. That's fine
  for one seller and one app process in this prototype.

## 6. Write and read back across processes

Two separate `python -c` processes against the same directory: the first writes the threshold
as 5, the second updates it to 3 and reads it back with a fresh store.

```
$ python -c "PreferenceStore(D, 'SELLER-001').upsert('restock_threshold', '5')"
$ python -c "s = PreferenceStore(D, 'SELLER-001'); print(s.upsert('restock_threshold', '3')); print(PreferenceStore(D, 'SELLER-001').get_all())"
Preference(key='restock_threshold', value='3', updated_at='2026-10-15T04:09:20+00:00', previous_value='5')
{'restock_threshold': Preference(key='restock_threshold', value='3', updated_at='2026-10-15T04:09:20+00:00', previous_value='5')}
```
