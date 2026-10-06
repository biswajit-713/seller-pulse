"""Load `agent_cases.jsonl` (ev-01) and join each case to its query in `queries.jsonl`.

The case file never copies query text: `query`, `query_context`, `expected_behavior`,
`expected_answer` and `notes` come from the joined `queries.jsonl` record. Every problem with
the files — a malformed line, a missing field, an unknown `source_query`, a duplicate id, a
check `run_checks` would reject — raises `HarnessError`, which the runner maps to exit 2.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from seller_pulse.config import DATA_DIR
from seller_pulse.evals.checks import run_checks
from seller_pulse.evals.judge import Rubric
from seller_pulse.evals.retrieval_eval import DEFAULT_QUERIES_PATH, HarnessError

DEFAULT_AGENT_CASES_PATH = DATA_DIR / "synthetic_queries" / "agent_cases.jsonl"
STATUSES = frozenset({"scored", "known_gap"})
_REQUIRED = ("id", "source_query", "status", "bucket", "checks", "why")


@dataclass(frozen=True)
class AgentCase:
    id: str
    source_query: str
    status: str  # scored | known_gap
    bucket: str
    checks: list[dict]
    why: str
    query: str
    query_context: str | None
    expected_behavior: str
    expected_answer: str
    notes: str | None
    groundedness_allow: tuple[str, ...] = ()

    @property
    def scored(self) -> bool:
        return self.status == "scored"

    @property
    def message(self) -> str:
        """What the agent is sent: the query, plus pasted content (as `retrieval_cases` SR-02)."""
        return f"{self.query}\n{self.query_context}" if self.query_context else self.query

    @property
    def rubric(self) -> Rubric:
        return Rubric(
            query=self.query,
            query_context=self.query_context,
            expected_behavior=self.expected_behavior,
            expected_answer=self.expected_answer,
            notes=self.notes,
        )


def _read_jsonl(path: Path) -> list[tuple[int, dict]]:
    records = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise HarnessError(f"{path.name}:{lineno}: malformed JSON ({exc})") from exc
            if not isinstance(record, dict):
                raise HarnessError(f"{path.name}:{lineno}: expected a JSON object")
            records.append((lineno, record))
    return records


def _allow_values(raw: dict, where: str) -> tuple[str, ...]:
    """`groundedness_allow` entries are `{"value": ..., "why": ...}` — an unexplained allow is refused."""
    values = []
    for entry in raw.get("groundedness_allow", []):
        if not isinstance(entry, dict) or not entry.get("value") or not entry.get("why"):
            raise HarnessError(f"{where}: groundedness_allow entries need a value and a why: {entry!r}")
        values.append(str(entry["value"]))
    return tuple(values)


def load_cases(
    cases_path: Path = DEFAULT_AGENT_CASES_PATH, queries_path: Path = DEFAULT_QUERIES_PATH
) -> list[AgentCase]:
    queries = {record["id"]: record for _, record in _read_jsonl(queries_path)}

    cases: list[AgentCase] = []
    seen: set[str] = set()
    for lineno, raw in _read_jsonl(cases_path):
        where = f"{cases_path.name}:{lineno}"
        missing = [key for key in _REQUIRED if key not in raw]
        if missing:
            raise HarnessError(f"{where}: missing {missing}")
        if raw["id"] in seen:
            raise HarnessError(f"{where}: duplicate case id {raw['id']!r}")
        seen.add(raw["id"])
        if raw["status"] not in STATUSES:
            raise HarnessError(f"{where}: status {raw['status']!r} not one of {sorted(STATUSES)}")
        query = queries.get(raw["source_query"])
        if query is None:
            raise HarnessError(f"{where}: source_query {raw['source_query']!r} not in {queries_path.name}")
        try:
            run_checks(raw["checks"], "", [])  # validates kinds, dimensions and required fields
        except (ValueError, KeyError, TypeError, re.error) as exc:
            raise HarnessError(f"{where}: malformed check ({exc})") from exc

        cases.append(
            AgentCase(
                id=raw["id"],
                source_query=raw["source_query"],
                status=raw["status"],
                bucket=raw["bucket"],
                checks=raw["checks"],
                why=raw["why"],
                query=query["query"],
                query_context=query.get("query_context"),
                expected_behavior=query["expected_behavior"],
                expected_answer=query["expected_answer"],
                notes=query.get("notes"),
                groundedness_allow=_allow_values(raw, where),
            )
        )
    return cases
