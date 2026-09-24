"""Input cleaning applied before a message is bundled into a prompt.

Only the cheap, uncontroversial normalisation lives here for now. Prompt-injection
defence is NOT implemented — the system prompt asserts precedence, but nothing in
this module detects or strips an attempt to override it.
"""

import unicodedata

MAX_INPUT_CHARS = 4000


def sanitize(text: str) -> str:
    """Normalise a raw chat message. Returns "" when there is nothing to send."""
    if not text:
        return ""

    # Drop control characters (category Cc) apart from newline and tab.
    cleaned = "".join(
        ch
        for ch in text
        if ch in "\n\t" or unicodedata.category(ch) != "Cc"
    )
    return cleaned.strip()[:MAX_INPUT_CHARS]
