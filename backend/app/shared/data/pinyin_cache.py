"""
In-memory pinyin initial cache for stock name search.

Lazy-loaded on first search request. Maps uppercase pinyin initials
to lists of (ts_code, name) for fast prefix matching.
"""

import logging
from pypinyin import lazy_pinyin, Style

logger = logging.getLogger(__name__)

_cache: dict[str, list[tuple[str, str]]] | None = None
_entries: list[tuple[str, str, str, str]] | None = None  # (ts_code, name, pinyin, industry)


def _get_initials(name: str) -> str:
    """Extract uppercase pinyin initials from a Chinese stock name."""
    return "".join(lazy_pinyin(name, style=Style.FIRST_LETTER)).upper()


async def _ensure_loaded():
    global _cache, _entries
    if _cache is not None:
        return

    from app.core.database import async_session
    from sqlalchemy import text

    async with async_session() as session:
        result = await session.execute(
            text("SELECT ts_code, name, COALESCE(industry,'') FROM stock_basic WHERE list_status = 'L' ORDER BY ts_code")
        )
        rows = result.fetchall()

    cache: dict[str, list[tuple[str, str, str]]] = {}
    entries: list[tuple[str, str, str, str]] = []

    for ts_code, name, industry in rows:
        py = _get_initials(name)
        entries.append((ts_code, name, py, industry))
        cache.setdefault(py, []).append((ts_code, name, industry))

    _cache = cache
    _entries = entries
    logger.info("pinyin cache loaded: %d stocks", len(entries))


async def search_by_pinyin(query: str, limit: int = 20) -> list[dict]:
    """Search stocks by pinyin initial prefix. Returns list of dicts."""
    await _ensure_loaded()
    assert _entries is not None

    q = query.upper()
    results: list[dict] = []

    for ts_code, name, py, industry in _entries:
        if py.startswith(q):
            results.append({
                "ts_code": ts_code,
                "name": name,
                "industry": industry,
                "list_status": "L",
            })
            if len(results) >= limit:
                break

    return results
