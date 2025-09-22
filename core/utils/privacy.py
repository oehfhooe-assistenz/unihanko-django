# core/utils/privacy.py
import re
import textwrap

def mask_iban(iban: str | None, head: int = 6, tail: int = 4, fill: str = "*") -> str:
    """
    Show the first `head` and last `tail` characters; mask the middle.
    Returned string is grouped in blocks of 4 for readability.
    """
    s = re.sub(r"\s+", "", (iban or ""))
    if not s:
        return ""
    n_mask = max(0, len(s) - head - tail)
    masked = s if n_mask <= 0 else s[:head] + (fill * n_mask) + (s[-tail:] if tail else "")
    return " ".join(textwrap.wrap(masked, 4))

