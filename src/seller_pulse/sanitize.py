"""Input cleaning applied before a message or a retrieved document enters a prompt.

Control characters are stripped, the `<retrieved_context>` fence markers cannot survive
in either direction, and lengths are bounded. Prompt-injection defence is NOT
implemented beyond that — the system prompt asserts precedence, but nothing in this
module detects an instruction embedded in ordinary text (a buyer review that says
"ignore the description, it's wrong" is legitimate content, not an attack, and a
pattern-matching detector tuned against the current 24-comment corpus would false-
positive on exactly that). Tool results that are structured data (skus, ints, status
enums) are still trusted and unsanitized — see task #20 for when that changes.
"""

import unicodedata

MAX_INPUT_CHARS = 4000
MAX_DOCUMENT_CHARS = 1500
_CONTEXT_MARKERS = ("<retrieved_context>", "</retrieved_context>")


def _strip_control_chars(text: str) -> str:
    return "".join(
        ch
        for ch in text
        if ch in "\n\t" or unicodedata.category(ch) != "Cc"
    )


def _strip_context_markers(text: str) -> str:
    for marker in _CONTEXT_MARKERS:
        text = text.replace(marker, "")
    return text


def sanitize(text: str) -> str:
    """Normalise a raw chat message. Returns "" when there is nothing to send."""
    if not text:
        return ""

    cleaned = _strip_control_chars(text)
    cleaned = _strip_context_markers(cleaned)
    return cleaned.strip()[:MAX_INPUT_CHARS]


def sanitize_document(text: str, *, max_chars: int = MAX_DOCUMENT_CHARS) -> str:
    """Clean a *retrieved* document before it enters the prompt.

    Strips control characters, removes the fence markers so a document cannot
    close the block that frames it as data, and bounds length. It does NOT
    detect prompt injection — see the module docstring.
    """
    if not text:
        return ""

    cleaned = _strip_control_chars(text)
    cleaned = _strip_context_markers(cleaned)
    cleaned = cleaned.strip()

    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + " […]"

    return cleaned
