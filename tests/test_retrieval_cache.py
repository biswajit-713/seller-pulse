import logging

from seller_pulse.cache import CacheStats, MemoryCache
from seller_pulse.rag import store
from seller_pulse.rag.retrieval import PolicyStore, _query_args
from seller_pulse.rag.store import cached_embedder


def test_cached_embedder_computes_once_and_logs(monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(store, "embed_query", lambda t: calls.append(t) or [0.1, 0.2])
    stats = CacheStats()
    embed = cached_embedder(MemoryCache(max_entries=4, name="embed"), stats)
    with caplog.at_level(logging.INFO, logger=store.logger.name):
        assert embed("late refund?") == [0.1, 0.2]
        assert embed("late refund?") == [0.1, 0.2]
    assert calls == ["late refund?"]
    assert (stats.misses, stats.hits) == (1, 1)
    assert [r.getMessage() for r in caplog.records] == [
        "cache embed miss len=12",
        "cache embed hit len=12",
    ]


def test_query_args_uses_embedding_only_when_given():
    assert _query_args("q", None) == {"query_texts": ["q"]}
    assert _query_args("q", lambda t: [1.0]) == {"query_embeddings": [[1.0]]}


class _FakeCollection:
    def __init__(self):
        self.kwargs = None

    def query(self, **kwargs):
        self.kwargs = kwargs
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}


def test_stores_pass_embedding_to_chroma(monkeypatch):
    fake = _FakeCollection()
    monkeypatch.setattr("seller_pulse.rag.retrieval.policy_collection", lambda c: fake)
    PolicyStore(object(), embed=lambda t: [0.5]).search("q")
    assert fake.kwargs == {"query_embeddings": [[0.5]], "n_results": 2}
    PolicyStore(object()).search("q")
    assert fake.kwargs == {"query_texts": ["q"], "n_results": 2}
