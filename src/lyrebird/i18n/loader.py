"""i18n loader + locale negotiation."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Iterable, Optional, Set


def _flatten(d: dict, prefix: str = "") -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        elif isinstance(v, str):
            out[key] = v
        else:
            # numbers / bools / lists: coerce to string but leave a hint
            out[key] = str(v)
    return out


class I18nRegistry:
    """Loads JSON locale files and serves translations with fallback chain."""

    def __init__(self, root: Path, default: str = "zh", fallback: Optional[str] = None):
        self.root = Path(root)
        self.default = default
        self.fallback = fallback  # extra fallback if neither requested nor default has the key
        self._cache: Dict[str, Dict[str, str]] = {}
        self._scan()
        if default not in self._cache:
            raise FileNotFoundError(
                f"default locale {default!r} not found in {root}; "
                f"available: {list(self._cache)}"
            )

    def _scan(self) -> None:
        for path in sorted(self.root.glob("*.json")):
            locale = path.stem
            data = json.loads(path.read_text(encoding="utf-8"))
            self._cache[locale] = _flatten(data)

    def available(self) -> list[str]:
        return sorted(self._cache.keys())

    def get(self, locale: str) -> Dict[str, str]:
        """Return flat dict for the locale.

        Strategy: start from the default to ensure every key is present, then
        overlay the requested locale. This means clients can always rely on
        "every UI string has a value, even if it's still in the default tongue".
        """
        base = dict(self._cache.get(self.default, {}))
        if locale in self._cache and locale != self.default:
            base.update(self._cache[locale])
        return base

    def t(self, locale: str, key: str, **vars) -> str:
        """Translate. Chain: locale -> default -> fallback -> literal key."""
        chain = [locale, self.default]
        if self.fallback and self.fallback not in chain:
            chain.append(self.fallback)
        value = key  # last-ditch default
        for loc in chain:
            entries = self._cache.get(loc)
            if entries and key in entries:
                value = entries[key]
                break
        if vars and "{" in value:
            for k, v in vars.items():
                value = value.replace("{" + k + "}", str(v))
        return value


# ---------- locale negotiation ----------

_LANG_TAG = re.compile(r"^([A-Za-z]+)(?:-[A-Za-z0-9]+)*\s*(?:;\s*q\s*=\s*([\d.]+))?\s*$")


def _parse_accept_language(value: str) -> list[tuple[str, float]]:
    """Parse Accept-Language into (primary_tag, q) pairs sorted by q desc."""
    if not value:
        return []
    items: list[tuple[str, float]] = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = _LANG_TAG.match(chunk)
        if not m:
            continue
        tag = m.group(1).lower()
        try:
            q = float(m.group(2)) if m.group(2) else 1.0
        except ValueError:
            q = 1.0
        items.append((tag, q))
    items.sort(key=lambda x: -x[1])
    return items


def negotiate_locale(
    *,
    query: Optional[str],
    cookie: Optional[str],
    accept_language: Optional[str],
    available: Set[str] | Iterable[str],
    default: str,
) -> str:
    """Pick a locale based on (query, cookie, Accept-Language, default).

    Available is the set of supported locales. Negotiation returns one of them.
    """
    avail = set(available)
    if query and query in avail:
        return query
    if cookie and cookie in avail:
        return cookie
    if accept_language:
        for tag, _q in _parse_accept_language(accept_language):
            if tag in avail:
                return tag
    return default if default in avail else next(iter(avail), default)
