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

    # ── 基础数据 ─────────────────────────────────────────────

    def stock_basic(self, **kwargs) -> pd.DataFrame:
        return self.query(
            "stock_basic",
            fields="ts_code,symbol,name,area,industry,market,list_date,list_status,exchange,curr_type,is_hs",
            **kwargs,
        )

    def trade_cal(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "exchange,cal_date,is_open,pretrade_date")
        return self.query("trade_cal", **kwargs)

    def stock_st(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "ts_code,name,trade_date,type,type_name")
        return self.query("stock_st", **kwargs)

    # ── 行情数据 ─────────────────────────────────────────────

    def daily(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount")
        return self.query("daily", **kwargs)

    def daily_basic(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,"
            "pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,"
            "total_share,float_share,free_share,total_mv,circ_mv",
        )
        return self.query("daily_basic", **kwargs)

    def stk_limit(self, **kwargs) -> pd.DataFrame:
        return self.query(
            "stk_limit",
            fields="trade_date,ts_code,pre_close,up_limit,down_limit",
            **kwargs,
        )

    def suspend_d(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "ts_code,trade_date,suspend_timing,suspend_type")
        return self.query("suspend_d", **kwargs)

    def adj_factor(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "ts_code,trade_date,adj_factor")
        return self.query("adj_factor", **kwargs)

    def stk_mins(self, **kwargs) -> pd.DataFrame:
        return self.query("stk_mins", **kwargs)

    def rt_k(self, **kwargs) -> pd.DataFrame:
        return self.query("rt_k", **kwargs)

    # ── 指数 ─────────────────────────────────────────────────

    def index_basic(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "ts_code,name,fullname,market,publisher,index_type,category,base_date,base_point,list_date")
        return self.query("index_basic", **kwargs)

    def index_daily(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "ts_code,trade_date,close,open,high,low,pre_close,change,pct_chg,vol,amount")
        return self.query("index_daily", **kwargs)

    def index_classify(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "index_code,industry_name,level,industry_code,src")
        return self.query("index_classify", **kwargs)

    def index_global(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "ts_code,trade_date,open,close,high,low,pre_close,change,pct_chg,vol,amount")
        return self.query("index_global", **kwargs)

    def sw_daily(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "ts_code,trade_date,name,open,low,high,close,change,pct_change,vol,amount,pe,pb,float_mv,total_mv",
        )
        return self.query("sw_daily", **kwargs)

    # ── 资金流向 ─────────────────────────────────────────────

    def moneyflow_dc(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "ts_code,trade_date,buy_sm_amount,sell_sm_amount,"
            "buy_md_amount,sell_md_amount,buy_lg_amount,sell_lg_amount,"
            "buy_elg_amount,sell_elg_amount,net_mf_amount",
        )
        return self.query("moneyflow_dc", **kwargs)

    def moneyflow_hsgt(self, **kwargs) -> pd.DataFrame:
        return self.query("moneyflow_hsgt", **kwargs)

    # ── 资讯 ─────────────────────────────────────────────────

    def news(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "datetime,content,title,channels,src")
        return self.query("major_news", **kwargs)

    def anns(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "ts_code,ann_date,name,title,url")
        return self.query("anns_d", **kwargs)

    # ── 概念板块 ─────────────────────────────────────────────

    def concept(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "code,name,src")
        return self.query("concept", **kwargs)

    def concept_detail(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "id,concept_name,ts_code,name")
        return self.query("concept_detail", **kwargs)
