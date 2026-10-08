"""Load `route_cases.jsonl` (rt-02): the gold route set for every query in `queries.jsonl`.

Each line is `{"id": "SQ-xx", "routes": [...], "why": "..."}`. An empty `routes` list means
core prompt only. Cases labelled with a deferred route (`memory`) load normally but report
`deferred`, so the classifier eval can skip them. Every problem with the file — a malformed line, a missing field, an id not in
`queries.jsonl`, a duplicate id, an unknown or repeated route — raises `HarnessError`.
"""

from dataclasses import dataclass
from pathlib import Path

from seller_pulse.config import DATA_DIR
from seller_pulse.evals.cases import _read_jsonl
from seller_pulse.evals.retrieval_eval import DEFAULT_QUERIES_PATH, HarnessError
from seller_pulse.router import DEFERRED_ROUTES, Route

DEFAULT_ROUTE_CASES_PATH = DATA_DIR / "synthetic_queries" / "route_cases.jsonl"
_REQUIRED = ("id", "routes", "why")


@dataclass(frozen=True)
class RouteCase:
    id: str
    routes: frozenset[Route]
    why: str
    query: str
    query_context: str | None

    @property
    def deferred(self) -> bool:
        """True if the case needs a route that isn't built yet; the classifier eval skips it."""
        return bool(self.routes & DEFERRED_ROUTES)

    @property
    def message(self) -> str:
        """What the classifier is sent: the query, plus pasted content (as `AgentCase.message`)."""
        return f"{self.query}\n{self.query_context}" if self.query_context else self.query


def _routes(raw: dict, where: str) -> frozenset[Route]:
    routes = raw["routes"]
    if not isinstance(routes, list):
        raise HarnessError(f"{where}: routes must be a list: {routes!r}")
    unknown = [r for r in routes if r not in set(Route)]
    if unknown:
        raise HarnessError(f"{where}: unknown routes {unknown}, expected {[r.value for r in Route]}")
    if len(set(routes)) != len(routes):
        raise HarnessError(f"{where}: duplicate routes {routes}")
    return frozenset(Route(r) for r in routes)


def load_route_cases(
    cases_path: Path = DEFAULT_ROUTE_CASES_PATH, queries_path: Path = DEFAULT_QUERIES_PATH
) -> list[RouteCase]:
    queries = {record["id"]: record for _, record in _read_jsonl(queries_path)}

    cases: list[RouteCase] = []
    seen: set[str] = set()
    for lineno, raw in _read_jsonl(cases_path):
        where = f"{cases_path.name}:{lineno}"
        missing = [key for key in _REQUIRED if key not in raw]
        if missing:
            raise HarnessError(f"{where}: missing {missing}")
        if raw["id"] in seen:
            raise HarnessError(f"{where}: duplicate case id {raw['id']!r}")
        seen.add(raw["id"])
        query = queries.get(raw["id"])
        if query is None:
            raise HarnessError(f"{where}: id {raw['id']!r} not in {queries_path.name}")
        if not isinstance(raw["why"], str) or not raw["why"].strip():
            raise HarnessError(f"{where}: why must be a non-empty string")

        cases.append(
            RouteCase(
                id=raw["id"],
                routes=_routes(raw, where),
                why=raw["why"],
                query=query["query"],
                query_context=query.get("query_context"),
            )
        )
    return cases
