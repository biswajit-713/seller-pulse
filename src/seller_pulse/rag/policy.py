"""The policy corpus, chunked at `## ` section boundaries.

`data/policy/seller_policy_handbook.md` is hand-converted once from the source PDF (see
`plan/rag-02-policy-corpus.md`) so that chunk boundaries are a reviewable diff, not a runtime
decision. Each `## ` section is followed by an HTML-comment metadata line
(`<!-- id: ... | topics: ... | type: ... -->`) that this module parses, not infers.

No sliding-window overlap: a section boundary is a clause boundary, and a policy question is
answered by a clause. Cross-section relationships (e.g. pol-2a / pol-5 both touching reviews)
are bridged by shared `topics` vocabulary at query time, not by duplicating text into a window.

`topics` is kept for documentation only. The prototype stored it delimiter-wrapped
(`"|reviews|incentives|"`) on the claim that this keeps metadata substring matches exact —
verified false: Chroma 1.5.9 has no substring operator for metadata `where` clauses
(`$contains` applies to `where_document`, not metadata), and a mismatched `where` on metadata
returns 0 rows silently rather than raising. No consumer filters on `topics` in this plan; if
one is added later, use one boolean key per topic (`topic_reviews: True`) instead.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from seller_pulse.config import DEFAULT_POLICY_PATH

_TITLE_RE = re.compile(r"^# (?P<title>.+)$", re.MULTILINE)

_SECTION_RE = re.compile(
    r"^## (?P<section_title>.+?)\s*\n"
    r"<!--\s*id:\s*(?P<chunk_id>\S+)\s*\|\s*topics:\s*(?P<topics>.+?)\s*\|\s*"
    r"type:\s*(?P<chunk_type>\S+)\s*-->\s*\n"
    r"(?P<body>.*?)"
    r"(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class PolicyChunk:
    chunk_id: str
    section_title: str
    body: str
    topics: tuple[str, ...]
    chunk_type: str
    doc_title: str

    @property
    def breadcrumb(self) -> str:
        """`<doc title> > <section title>` — thin sections (pol-3, pol-4) need the section
        header's context put back; embedding the bare body loses it."""
        return f"{self.doc_title} > {self.section_title}"

    @property
    def text(self) -> str:
        """What gets embedded: the breadcrumb, then the body."""
        return f"{self.breadcrumb}\n\n{self.body}"

    @property
    def metadata(self) -> dict[str, str]:
        return {
            "chunk_id": self.chunk_id,
            "doc_title": self.doc_title,
            "section_title": self.section_title,
            "chunk_type": self.chunk_type,
            "topics": ", ".join(self.topics),
        }


def load_chunks(path: Path = DEFAULT_POLICY_PATH) -> list[PolicyChunk]:
    text = path.read_text(encoding="utf-8")

    title_match = _TITLE_RE.search(text)
    if title_match is None:
        raise ValueError(f"{path}: no top-level '# ' title found")
    doc_title = title_match.group("title").strip()

    section_matches = list(_SECTION_RE.finditer(text))
    if not section_matches:
        raise ValueError(f"{path}: no '## ' sections found")

    chunks = []
    seen: dict[str, int] = {}
    for match in section_matches:
        chunk_id = match.group("chunk_id")
        seen[chunk_id] = seen.get(chunk_id, 0) + 1
        topics = tuple(t.strip() for t in match.group("topics").split(","))
        chunks.append(
            PolicyChunk(
                chunk_id=chunk_id,
                section_title=match.group("section_title").strip(),
                body=match.group("body").strip(),
                topics=topics,
                chunk_type=match.group("chunk_type").strip(),
                doc_title=doc_title,
            )
        )

    duplicates = sorted(chunk_id for chunk_id, count in seen.items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate chunk ids: {', '.join(duplicates)}")

    return chunks
