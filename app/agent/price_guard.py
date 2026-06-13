"""Deterministic output-grounding guard for hard facts the model re-types and
occasionally garbles: prices and reference IDs.

- Prices: a real catalog price quoted one digit off (1.699.000 -> 1.699.900) is
  snapped back to the unique grounded price it clearly meant.
- Reference IDs (ORD/WAR/TKT/ESC): an id that doesn't match a tool-returned one is
  snapped to the grounded id of the same prefix when there is exactly one.

In both cases zero or ambiguous matches are left untouched — we correct, never guess.
"""
from __future__ import annotations

import re

# Keys under which tools expose monetary values in their ToolResponse data/args.
_PRICE_KEYS = {"precio_cop", "precio", "price", "total", "monto", "valor"}

# Colombian price formats: grouped (1.699.000 / 1,699,000) or a $-prefixed run.
_PRICE_TOKEN = re.compile(r"\$?\s*\d{1,3}(?:[.,]\d{3})+|\$\s*\d{4,}")

# Below 6 digits it's not a catalog price (years, small counts) — leave it alone.
_MIN_PRICE_DIGITS = 6

# Reference ids the agent issues/echoes: order, warranty, ticket, escalation.
_ID_TOKEN = re.compile(r"\b(?:ORD|WAR|TKT|ESC)-[A-Za-z0-9]+\b", re.IGNORECASE)


def collect_grounded_prices(obj) -> set[int]:
    """Recursively pull every monetary value from tool args/data (and any nested
    structure) into a set of ints."""
    prices: set[int] = set()

    def walk(o) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(k, str) and k.lower() in _PRICE_KEYS and isinstance(
                    v, (int, float)
                ) and not isinstance(v, bool):
                    prices.add(int(v))
                walk(v)
        elif isinstance(o, (list, tuple)):
            for item in o:
                walk(item)

    walk(obj)
    return prices


def _near(a: str, b: str) -> bool:
    """True if digit-strings a and b differ by exactly one substitution or one
    adjacent transposition (the two slips an LLM makes when echoing a number)."""
    if len(a) != len(b):
        return False
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    if len(diff) == 1:
        return True
    if len(diff) == 2:
        i, j = diff
        return j == i + 1 and a[i] == b[j] and a[j] == b[i]
    return False


def _format(n: int, sep: str | None, dollar: bool) -> str:
    grouped = f"{n:,}"  # 1,699,000
    if sep == ".":
        grouped = grouped.replace(",", ".")
    elif sep is None:
        grouped = str(n)
    return ("$" if dollar else "") + grouped


def correct_prices(text: str, grounded: set[int]) -> tuple[str, list[tuple[int, int]]]:
    """Snap near-miss prices in `text` to the grounded price they clearly meant.

    Returns the corrected text and a list of (wrong, fixed) pairs that were changed
    (for logging). No-op when `grounded` is empty.
    """
    if not text or not grounded:
        return text, []

    fixes: list[tuple[int, int]] = []

    def repl(m: re.Match) -> str:
        token = m.group()
        digits = re.sub(r"\D", "", token)
        if len(digits) < _MIN_PRICE_DIGITS:
            return token
        val = int(digits)
        if val in grounded:
            return token  # already correct
        candidates = [g for g in grounded if _near(digits, str(g))]
        if len(candidates) != 1:
            return token  # zero or ambiguous -> don't guess
        fixed = candidates[0]
        fixes.append((val, fixed))
        sep = "." if "." in token else ("," if "," in token else None)
        return _format(fixed, sep, "$" in token)

    return _PRICE_TOKEN.sub(repl, text), fixes


def collect_grounded_ids(obj) -> set[str]:
    """Recursively pull every reference id (ORD/WAR/TKT/ESC-...) from tool data,
    uppercased."""
    ids: set[str] = set()

    def walk(o) -> None:
        if isinstance(o, str):
            ids.update(t.upper() for t in _ID_TOKEN.findall(o))
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for item in o:
                walk(item)

    walk(obj)
    return ids


def correct_ids(text: str, grounded: set[str]) -> tuple[str, list[tuple[str, str]]]:
    """Snap a reference id in `text` to the grounded id of the same prefix when there
    is exactly one. Returns the corrected text and the (wrong, fixed) pairs changed."""
    if not text or not grounded:
        return text, []

    by_prefix: dict[str, set[str]] = {}
    for gid in grounded:
        by_prefix.setdefault(gid.split("-", 1)[0], set()).add(gid)

    fixes: list[tuple[str, str]] = []

    def repl(m: re.Match) -> str:
        token = m.group()
        up = token.upper()
        if up in grounded:
            return token  # already correct
        candidates = by_prefix.get(up.split("-", 1)[0], set())
        if len(candidates) != 1:
            return token  # zero or ambiguous -> don't guess
        fixed = next(iter(candidates))
        fixes.append((token, fixed))
        return fixed

    return _ID_TOKEN.sub(repl, text), fixes
