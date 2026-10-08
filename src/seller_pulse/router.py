"""Prompt routing: which prompt modules (and tools) a turn needs (`plan/rt-00-overview.md`).

Not to be confused with `rag.retrieval.Route` (stats / general), which picks the *retrieval*
shape. That one is renamed when routing is wired into `chat.respond` (rt-06).
"""

from enum import StrEnum


class Route(StrEnum):
    DATA = "data"  # sales, inventory, figures, forecasts -> tool rules, tools bound
    REVIEWS = "reviews"  # review search/stats, listings, drafts, rewrites
    POLICY = "policy"  # anything that might touch a marketplace rule -> refusal procedure
    MEMORY = "memory"  # saved preferences -> memory tools (w2-13); gold label only, no module yet


# Routes that are labelled in the gold set but not built yet. Cases carrying one are skipped in
# the classifier eval until the route lands.
DEFERRED_ROUTES = frozenset({Route.MEMORY})

# Every route that is built. The fail-open answer: a classifier error routes here.
ALL_ROUTES = frozenset(Route) - DEFERRED_ROUTES
