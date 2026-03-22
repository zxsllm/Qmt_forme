import logging
import time

import pandas as pd
import tushare as ts

from app.core.config import settings

logger = logging.getLogger(__name__)


class TushareService:
    """Unified Tushare API wrapper with rate limiting and retry."""

    def __init__(self):
        if not settings.TUSHARE_TOKEN:
            raise ValueError("TUSHARE_TOKEN not set")
        self._pro = ts.pro_api(settings.TUSHARE_TOKEN)
        self._last_call_time: float = 0
        self._min_interval: float = 60.0 / settings.TUSHARE_DAILY_RPM

    def _rate_limit(self):
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call_time = time.time()

    def query(
        self,
        api_name: str,
        max_retries: int = 3,
        **kwargs,
    ) -> pd.DataFrame:
        for attempt in range(max_retries):
            self._rate_limit()
            try:
                df = self._pro.query(api_name, **kwargs)
                if df is not None and not df.empty:
                    logger.debug(
                        "Tushare %s: %d rows (attempt %d)",
                        api_name,
                        len(df),
                        attempt + 1,
                    )
                return df if df is not None else pd.DataFrame()
            except Exception as e:
                wait = 2 ** attempt
                logger.warning(
                    "Tushare %s failed (attempt %d/%d): %s, retry in %ds",
                    api_name,
                    attempt + 1,
                    max_retries,
                    e,
                    wait,
                )
                if attempt < max_retries - 1:
                    time.sleep(wait)
                else:
                    raise

        return pd.DataFrame()

    def stock_basic(self, **kwargs) -> pd.DataFrame:
        return self.query(
            "stock_basic",
            fields="ts_code,symbol,name,area,industry,market,list_date,list_status,exchange,curr_type,is_hs",
            **kwargs,
        )

    def trade_cal(self, **kwargs) -> pd.DataFrame:
        return self.query("trade_cal", **kwargs)

    def daily(self, **kwargs) -> pd.DataFrame:
        return self.query("daily", **kwargs)

    def daily_basic(self, **kwargs) -> pd.DataFrame:
        return self.query("daily_basic", **kwargs)

    def index_basic(self, **kwargs) -> pd.DataFrame:
        return self.query("index_basic", **kwargs)

    def index_daily(self, **kwargs) -> pd.DataFrame:
        return self.query("index_daily", **kwargs)

    def index_classify(self, **kwargs) -> pd.DataFrame:
        return self.query("index_classify", **kwargs)

    def stk_limit(self, **kwargs) -> pd.DataFrame:
        return self.query(
            "stk_limit",
            fields="trade_date,ts_code,pre_close,up_limit,down_limit",
            **kwargs,
        )

    def suspend_d(self, **kwargs) -> pd.DataFrame:
        return self.query("suspend_d", **kwargs)
