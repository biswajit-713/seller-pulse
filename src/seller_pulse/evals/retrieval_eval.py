"""The scored retrieval harness — Task 9's evidence, and the 6-pager §6 metric.

No LLM, no network beyond the local vector store, no new dependencies. Retrieval accuracy is a
property of the store, not of a model's phrasing, so scoring it offline keeps the check fast,
deterministic and runnable without a ``GROQ_API_KEY``. Cases are read from
``data/synthetic_queries/retrieval_cases.jsonl`` (`t1-09-eval-cases.md`) and joined against
``queries.jsonl`` for query text.

Queries are embedded with the *same* `DefaultEmbeddingFunction` the store was built with by
going through ``ReviewStore`` / ``PolicyStore`` (`rag/retrieval.py`), which construct their
collections via ``get_client`` / ``policy_collection`` / ``review_collection`` (`rag/store.py`).
That is the only path taken here — this module never opens a second Chroma client, because a
mismatched embedding config is refused by Chroma 1.x and a second client risks exactly that.

Exit 2 means the harness could not run — the store is missing or empty, an embedding-config
mismatch, a case's expected id does not exist anywhere in the store, or a case file is malformed.
Exit 1 means the harness *did* run and the scored pass rate regressed. Conflating the two is how
an empty index (`get_or_create_collection` silently creates one) hides behind a score that reads
as "retrieval got worse" when the real story is "the store was never ingested."
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from seller_pulse.config import DATA_DIR, DEFAULT_RETRIEVAL_CASES_PATH, load_settings
from seller_pulse.rag.retrieval import Hit, PolicyStore, ReviewStore
from seller_pulse.rag.stats import ReviewStats, compute
from seller_pulse.rag.store import get_client, policy_collection, review_collection

DEFAULT_QUERIES_PATH = DATA_DIR / "synthetic_queries" / "queries.jsonl"
PASS_THRESHOLD = 9  # out of 10 — 6-pager §6: ">= 9 of 10 test questions"
WIDEN_K = 20


@dataclass(frozen=True)
class Case:
    id: str
    query: str
    source_query: str | None
    assertions: tuple[dict[str, Any], ...]
    margin_watch: dict[str, Any] | None


@dataclass(frozen=True)
class AssertionResult:
    passed: bool
    detail: dict[str, Any]


@dataclass(frozen=True)
class CaseResult:
    case: Case
    assertions: tuple[AssertionResult, ...]
    margin: dict[str, Any] | None

    @property
    def passed(self) -> bool:
        return all(a.passed for a in self.assertions)


class HarnessError(RuntimeError):
    """A setup problem — the harness could not run, not that retrieval failed."""


def check_store(policy_count: int, review_count: int) -> None:
    """Refuse an empty store — `get_or_create_collection` would otherwise hide it as a low score."""
    if policy_count == 0 or review_count == 0:
        raise HarnessError(
            "the vector store is empty (policy_kb="
            f"{policy_count}, seller_reviews={review_count}). "
            "Run: uv run python -m seller_pulse.rag.ingest"
        )


def load_cases(cases_path: Path, queries_path: Path) -> list[Case]:
    queries: dict[str, str] = {}
    with open(queries_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            queries[record["id"]] = record["query"]

    cases: list[Case] = []
    with open(cases_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            query = raw["query"]
            source_query = raw.get("source_query")
            if query is None:
                if source_query is None:
                    raise HarnessError(f"case {raw['id']}: no query and no source_query")
                if source_query not in queries:
                    raise HarnessError(
                        f"case {raw['id']}: source_query {source_query!r} not found in "
                        f"{queries_path}"
                    )
                query = queries[source_query]
            cases.append(
                Case(
                    id=raw["id"],
                    query=query,
                    source_query=source_query,
                    assertions=tuple(raw["assertions"]),
                    margin_watch=raw.get("margin_watch"),
                )
            )
    return cases


def _validate_expected_ids(cases: list[Case], *, policy_ids: set[str], review_ids: set[str]) -> None:
    universes = {"policy_kb": policy_ids, "seller_reviews": review_ids}
    for case in cases:
        for assertion in case.assertions:
            if assertion["kind"] != "rank":
                continue
            universe = universes[assertion["collection"]]
            for expected_id in assertion["expect"]:
                if expected_id not in universe:
                    raise HarnessError(
                        f"case {case.id}: expected id {expected_id!r} does not exist in "
                        f"{assertion['collection']} — fix the case or re-ingest"
                    )


def check_rank(
    store: ReviewStore | PolicyStore,
    query_text: str,
    assertion: dict[str, Any],
    *,
    collection_size: int,
) -> AssertionResult:
    k = assertion["k"]
    mode = assertion.get("mode", "any")
    expect: list[str] = assertion["expect"]

    hits = store.search(query_text, k=k)
    present = {hit.id: hit for hit in hits}
    matched = [e for e in expect if e in present]
    passed = len(matched) == len(expect) if mode == "all" else bool(matched)

    detail: dict[str, Any] = {
        "collection": assertion["collection"],
        "k": k,
        "mode": mode,
        "expect": expect,
        "hits": hits,
        "matched": matched,
    }

    if not passed:
        missing = [e for e in expect if e not in present]
        wk = min(WIDEN_K, collection_size)
        widened_hits = store.search(query_text, k=wk) if wk > k else hits
        rank_by_id = {hit.id: (i + 1, hit.distance) for i, hit in enumerate(widened_hits)}
        detail["widened"] = {
            "k": wk,
            "entries": [
                {
                    "id": missing_id,
                    "rank": rank_by_id.get(missing_id, (None, None))[0],
                    "distance": rank_by_id.get(missing_id, (None, None))[1],
                }
                for missing_id in missing
            ],
        }

    return AssertionResult(passed=passed, detail=detail)


def check_value(stats: ReviewStats, assertion: dict[str, Any]) -> AssertionResult:
    field = assertion["field"]

    if field == "low_rated_count":
        expect = assertion["expect"]
        actual = len(stats.low_rated)
        return AssertionResult(
            passed=actual == expect,
            detail={"field": field, "actual": actual, "expect": expect},
        )

    if field == "distribution":
        expect = {int(k): v for k, v in assertion["expect"].items()}
        actual = stats.distribution
        return AssertionResult(
            passed=actual == expect,
            detail={"field": field, "actual": actual, "expect": expect},
        )

    if field == "worst_skus_min_n2":
        k = assertion.get("k", 3)
        candidates = [s for s in stats.per_sku if s.n >= 2][:k]
        actual = [{"sku": s.sku, "mean": s.mean} for s in candidates]
        expect = assertion["expect"]
        if assertion.get("mode") == "set":
            passed = sorted((e["sku"], e["mean"]) for e in actual) == sorted(
                (e["sku"], e["mean"]) for e in expect
            )
        else:
            passed = actual == expect
        return AssertionResult(
            passed=passed,
            detail={"field": field, "actual": actual, "expect": expect},
        )

    raise HarnessError(f"unknown value assertion field {field!r}")


def check_margin(policy_store: PolicyStore, query_text: str, margin_watch: dict[str, Any]) -> dict[str, Any]:
    pair: list[str] = margin_watch["pair"]
    hits = policy_store.search(query_text, k=max(len(pair), 3))
    distance_by_id = {hit.id: hit.distance for hit in hits}
    missing = [pid for pid in pair if pid not in distance_by_id]
    if missing:
        return {"ok": False, "pair": pair, "missing": missing}

    d_first, d_second = distance_by_id[pair[0]], distance_by_id[pair[1]]
    margin = d_second - d_first
    return {
        "ok": True,
        "pair": pair,
        "distances": (d_first, d_second),
        "margin": margin,
        "recorded_margin": margin_watch["recorded_margin"],
        "warn_below": margin_watch["warn_below"],
        "warn": margin < margin_watch["warn_below"],
    }


def run_case(
    case: Case,
    *,
    policy_store: PolicyStore,
    review_store: ReviewStore,
    stats: ReviewStats,
    collection_sizes: dict[str, int],
) -> CaseResult:
    stores = {"policy_kb": policy_store, "seller_reviews": review_store}
    results: list[AssertionResult] = []
    for assertion in case.assertions:
        if assertion["kind"] == "rank":
            store = stores[assertion["collection"]]
            size = collection_sizes[assertion["collection"]]
            results.append(check_rank(store, case.query, assertion, collection_size=size))
        elif assertion["kind"] == "value":
            results.append(check_value(stats, assertion))
        else:
            raise HarnessError(f"case {case.id}: unknown assertion kind {assertion['kind']!r}")

    margin = check_margin(policy_store, case.query, case.margin_watch) if case.margin_watch else None
    return CaseResult(case=case, assertions=tuple(results), margin=margin)


def _hit_line(hit: Hit, *, rank: int, expect: list[str]) -> str:
    marker = "*" if hit.id in expect else " "
    dist = f"{hit.distance:.3f}" if hit.distance is not None else "  n/a"
    label = hit.metadata.get("section_title") or hit.citation
    return f"    {rank}. {dist}  {hit.id}  {marker}  {label}"


def render(result: CaseResult) -> None:
    case = result.case
    header = f"{case.id}"
    if case.source_query:
        header += f"  ({case.source_query})"
    header += f"  {'PASS' if result.passed else 'FAIL'}"
    print(header)
    print(f"query: {case.query}")

    for assertion_result in result.assertions:
        detail = assertion_result.detail
        if "field" in detail:
            status = "OK" if assertion_result.passed else "MISMATCH"
            print(f"  value: {detail['field']} = {detail['actual']} (expect {detail['expect']}) {status}")
            continue

        verb = "ALL" if detail["mode"] == "all" else "ANY"
        expect_str = ", ".join(detail["expect"])
        print(f"  {detail['collection']} top-{detail['k']} — expect {verb} of {expect_str}")
        for i, hit in enumerate(detail["hits"], start=1):
            print(_hit_line(hit, rank=i, expect=detail["expect"]))
        print(f"  -> {len(detail['matched'])}/{len(detail['expect'])} expected ids in top-{detail['k']}")

        if not assertion_result.passed:
            widened = detail["widened"]
            print(f"  missing (widened probe, k={widened['k']}):")
            for entry in widened["entries"]:
                if entry["rank"] is None:
                    print(f"    {entry['id']}  not in top {widened['k']}")
                else:
                    print(f"    {entry['id']}  rank {entry['rank']:>2}  distance {entry['distance']:.4f}")

    if result.margin is not None:
        m = result.margin
        if not m["ok"]:
            print(f"  margin check FAILED — missing from top-k: {m['missing']}")
        else:
            delta = m["margin"] - m["recorded_margin"]
            status = "WARN" if m["warn"] else "OK"
            print(
                f"  margin {m['pair'][0]}/{m['pair'][1]}: {m['margin']:.5f}  "
                f"(recorded {m['recorded_margin']:.5f}, delta {delta:+.5f})   {status}"
            )

    print()


def _to_json(result: CaseResult) -> dict[str, Any]:
    def jsonable_assertion(a: AssertionResult) -> dict[str, Any]:
        detail = dict(a.detail)
        if "hits" in detail:
            detail["hits"] = [
                {"id": h.id, "distance": h.distance, "metadata": dict(h.metadata)} for h in detail["hits"]
            ]
        return {"passed": a.passed, **detail}

    return {
        "id": result.case.id,
        "source_query": result.case.source_query,
        "query": result.case.query,
        "passed": result.passed,
        "assertions": [jsonable_assertion(a) for a in result.assertions],
        "margin": result.margin,
    }


def main() -> int:
    json_mode = "--json" in sys.argv

    try:
        settings = load_settings()
        client = get_client(settings.chroma_path)
        policy_col = policy_collection(client)
        review_col = review_collection(client)
        policy_count = policy_col.count()
        review_count = review_col.count()
        check_store(policy_count, review_count)

        policy_store = PolicyStore(client)
        review_store = ReviewStore(client, seller_id=settings.seller_id)
        stats = compute(review_store)

        cases = load_cases(DEFAULT_RETRIEVAL_CASES_PATH, DEFAULT_QUERIES_PATH)

        policy_ids = set(policy_col.get()["ids"])
        review_ids = set(review_col.get()["ids"])
        _validate_expected_ids(cases, policy_ids=policy_ids, review_ids=review_ids)
    except Exception as exc:  # noqa: BLE001 - this boundary converts any setup failure to exit 2
        message = f"could not run retrieval check: {exc}"
        if json_mode:
            print(json.dumps({"error": message}))
        else:
            print(f"ERROR: {message}")
        return 2

    collection_sizes = {"policy_kb": policy_count, "seller_reviews": review_count}
    results = [
        run_case(
            case,
            policy_store=policy_store,
            review_store=review_store,
            stats=stats,
            collection_sizes=collection_sizes,
        )
        for case in cases
    ]

    passed_count = sum(1 for r in results if r.passed)
    margin_result = next((r.margin for r in results if r.margin is not None), None)

    if json_mode:
        for result in results:
            print(json.dumps(_to_json(result)))
        return 0 if passed_count >= PASS_THRESHOLD else 1

    print("SellerPulse retrieval check")
    print(
        f"store: {settings.chroma_path}   policy_kb: {policy_count}   "
        f"seller_reviews: {review_count}"
    )
    print("embedding: DefaultEmbeddingFunction (all-MiniLM-L6-v2, 384d, cosine)")
    print(f"cases: {DEFAULT_RETRIEVAL_CASES_PATH} ({len(cases)} scored)")
    print(f"run: {datetime.now().isoformat(timespec='seconds')}")
    print()
    print("─" * 66)

    for result in results:
        render(result)

    print("─" * 66)
    print(f"{passed_count}/{len(results)} cases      target >= {PASS_THRESHOLD}/{len(results)}")
    if margin_result is not None and margin_result["ok"]:
        print(
            f"margin watch: {margin_result['pair'][0]}/{margin_result['pair'][1]} "
            f"{margin_result['margin']:.5f} (recorded {margin_result['recorded_margin']:.5f})"
        )
    print(f"RESULT: {'PASS' if passed_count >= PASS_THRESHOLD else 'FAIL'}")

    return 0 if passed_count >= PASS_THRESHOLD else 1


if __name__ == "__main__":
    raise SystemExit(main())
