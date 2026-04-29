from datetime import datetime

import pytest

from app.execution import api
from app.execution.oms.account import AccountManager
from app.execution.oms.position_book import PositionBook
from app.shared.interfaces.models import Position


@pytest.mark.asyncio
async def test_refresh_positions_uses_today_snapshot(monkeypatch):
    old_book = api.trading_engine.position_book
    old_account_mgr = api.trading_engine.account_mgr

    try:
        book = PositionBook()
        book._positions["000001.SZ"] = Position(
            ts_code="000001.SZ",
            qty=100,
            available_qty=100,
            avg_cost=10.0,
            market_price=10.0,
        )
        acct = AccountManager(1_000_000.0)
        acct._account.cash = 999_000.0

        api.trading_engine.position_book = book
        api.trading_engine.account_mgr = acct

        monkeypatch.setattr(
            api,
            "get_rt_snapshot",
            lambda: ({"000001.SZ": {"close": 11.23}}, datetime.now().timestamp()),
        )

        positions = await api._refresh_positions_from_market()

        assert len(positions) == 1
        assert positions[0].market_price == 11.23
        assert positions[0].unrealized_pnl == pytest.approx(123.0)
        assert api.trading_engine.get_account().market_value == pytest.approx(1123.0)
        assert api.trading_engine.get_account().total_asset == pytest.approx(1_000_123.0)
    finally:
        api.trading_engine.position_book = old_book
        api.trading_engine.account_mgr = old_account_mgr
