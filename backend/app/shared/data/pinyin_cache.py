"""
In-memory pinyin initial cache for stock name search.

Lazy-loaded on first search request. Maps uppercase pinyin initials
to lists of (ts_code, name) for fast prefix matching.
"""

import logging
from pypinyin import lazy_pinyin, Style

logger = logging.getLogger(__name__)

_entries: list[tuple[str, str, str, str, str]] | None = None  # (ts_code, name, pinyin, industry, type)


def _get_initials(name: str) -> str:
    """Extract uppercase pinyin initials from a Chinese stock name."""
    return "".join(lazy_pinyin(name, style=Style.FIRST_LETTER)).upper()


async def _ensure_loaded():
    global _entries
    if _entries is not None:
        return

    from app.core.database import async_session
    from sqlalchemy import text

    entries: list[tuple[str, str, str, str, str]] = []

    async with async_session() as session:
        # 股票
        r1 = await session.execute(text(
            "SELECT ts_code, name, COALESCE(industry,'') FROM stock_basic WHERE list_status = 'L' ORDER BY ts_code"
        ))
        for ts_code, name, industry in r1.fetchall():
            entries.append((ts_code, name, _get_initials(name), industry, "stock"))

        # 可转债 (active 集合：list_date 已上、未退市)
        r2 = await session.execute(text(
            "SELECT ts_code, COALESCE(bond_short_name,''), COALESCE(stk_short_name,'') "
            "FROM cb_basic "
            "WHERE list_date IS NOT NULL AND list_date <> '' "
            "  AND (delist_date IS NULL OR delist_date = '' OR delist_date > to_char(now(),'YYYYMMDD'))"
        ))
        for ts_code, bond_name, stk_name in r2.fetchall():
            display = bond_name or stk_name or ts_code
            # 拼音用债名首字母 + 正股名首字母合并，方便用户用任一拼音命中
            py = _get_initials(bond_name) + _get_initials(stk_name)
            industry = stk_name  # CB 的"行业"列借给"对应正股名"展示
            entries.append((ts_code, display, py, industry, "cb"))

    _entries = entries
    n_stock = sum(1 for e in entries if e[4] == "stock")
    n_cb = sum(1 for e in entries if e[4] == "cb")
    logger.info("pinyin cache loaded: %d stocks + %d CBs", n_stock, n_cb)


async def search_by_pinyin(query: str, limit: int = 20) -> list[dict]:
    """Search by pinyin initial prefix across stocks + CBs. Returns list of dicts."""
    await _ensure_loaded()
    assert _entries is not None

    q = query.upper()
    results: list[dict] = []

    for ts_code, name, py, industry, ttype in _entries:
        if py.startswith(q):
            results.append({
                "ts_code": ts_code,
                "name": name,
                "industry": industry,
                "list_status": "L" if ttype == "stock" else "CB",
                "type": ttype,
            })
            if len(results) >= limit:
                break

    return results
