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

    def rt_idx_k(self, **kwargs) -> pd.DataFrame:
        return self.query("rt_idx_k", **kwargs)

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

    def stk_auction(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "ts_code,trade_date,vol,price,amount,pre_close,turnover_rate,volume_ratio,float_share",
        )
        return self.query("stk_auction", **kwargs)

    def stk_auction_o(self, **kwargs) -> pd.DataFrame:
        """Historical opening auction OHLC (盘后更新). Has open/high/low/close/vwap."""
        kwargs.setdefault(
            "fields",
            "ts_code,trade_date,open,high,low,close,vol,amount,vwap",
        )
        return self.query("stk_auction_o", **kwargs)

    # ── 财经日历 ──────────────────────────────────────────────

    def eco_cal(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "date,time,currency,country,event,value,pre_value,fore_value")
        return self.query("eco_cal", **kwargs)

    # ── 资金流向 ─────────────────────────────────────────────

    def moneyflow_ind_ths(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "trade_date,ts_code,industry,lead_stock,close,pct_change,"
            "company_num,pct_change_stock,close_price,net_buy_amount,net_sell_amount,net_amount",
        )
        return self.query("moneyflow_ind_ths", **kwargs)

    def moneyflow_dc(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "ts_code,trade_date,buy_sm_amount,buy_md_amount,"
            "buy_lg_amount,buy_elg_amount,net_amount",
        )
        return self.query("moneyflow_dc", **kwargs)

    def moneyflow_hsgt(self, **kwargs) -> pd.DataFrame:
        return self.query("moneyflow_hsgt", **kwargs)

    # ── 资讯 ─────────────────────────────────────────────────

    def news(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "datetime,content,title,channels")
        return self.query("news", **kwargs)

    def anns(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "ts_code,ann_date,name,title,url")
        return self.query("anns_d", **kwargs)

    # ── 概念板块 ─────────────────────────────────────────────

    def irm_qa_sh(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "ts_code,name,trade_date,q,a,pub_time")
        return self.query("irm_qa_sh", **kwargs)

    def irm_qa_sz(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "ts_code,name,trade_date,q,a,pub_time,industry")
        return self.query("irm_qa_sz", **kwargs)

    def concept(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "code,name,src")
        return self.query("concept", **kwargs)

    def concept_detail(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "id,concept_name,ts_code,name")
        return self.query("concept_detail", **kwargs)

    # ── 财务数据 ─────────────────────────────────────────────

    def fina_indicator(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "ts_code,ann_date,end_date,eps,dt_eps,profit_dedt,roe,roe_waa,roe_dt,"
            "roa,netprofit_margin,grossprofit_margin,debt_to_assets,ocfps,bps,"
            "current_ratio,quick_ratio,netprofit_yoy,dt_netprofit_yoy,tr_yoy,or_yoy",
        )
        return self.query("fina_indicator", **kwargs)

    def income(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "ts_code,ann_date,f_ann_date,end_date,report_type,"
            "total_revenue,revenue,oper_cost,sell_exp,admin_exp,fin_exp,rd_exp,"
            "operate_profit,total_profit,income_tax,n_income,n_income_attr_p,basic_eps",
        )
        return self.query("income", **kwargs)

    def forecast(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "ts_code,ann_date,end_date,type,p_change_min,p_change_max,"
            "net_profit_min,net_profit_max,last_parent_net,summary,change_reason",
        )
        return self.query("forecast", **kwargs)

    def fina_mainbz(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "ts_code,end_date,bz_item,bz_sales,bz_profit,bz_cost,curr_type",
        )
        return self.query("fina_mainbz", **kwargs)

    def disclosure_date(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "ts_code,ann_date,end_date,pre_date,actual_date,modify_date",
        )
        return self.query("disclosure_date", **kwargs)

    # ── 打板/情绪面 ──────────────────────────────────────────

    def limit_list_ths(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "trade_date,ts_code,name,pct_chg,limit_type,first_lu_time,last_lu_time,"
            "open_num,limit_amount,turnover_rate,tag,status",
        )
        return self.query("limit_list_ths", **kwargs)

    def limit_list_d(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "trade_date,ts_code,name,industry,close,pct_chg,amount,limit_amount,"
            "float_mv,first_time,last_time,open_times,limit_times,limit",
        )
        return self.query("limit_list_d", **kwargs)

    def limit_step(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault("fields", "ts_code,name,trade_date,nums")
        return self.query("limit_step", **kwargs)

    def top_list(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "trade_date,ts_code,name,close,pct_change,turnover_rate,"
            "amount,l_sell,l_buy,l_amount,net_amount,net_rate,reason",
        )
        return self.query("top_list", **kwargs)

    def hm_detail(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "trade_date,ts_code,ts_name,buy_amount,sell_amount,net_amount,hm_name,tag",
        )
        return self.query("hm_detail", **kwargs)

    def limit_cpt_list(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "ts_code,name,trade_date,days,up_stat,cons_nums,up_nums,pct_chg,rank",
        )
        return self.query("limit_cpt_list", **kwargs)

    def dc_hot(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "trade_date,data_type,ts_code,ts_name,rank,pct_change,current_price",
        )
        return self.query("dc_hot", **kwargs)

    # ── Convertible Bond ──────────────────────────────────────────

    def cb_basic(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "ts_code,bond_short_name,stk_code,stk_short_name,maturity,"
            "maturity_date,list_date,delist_date,exchange,"
            "conv_start_date,conv_end_date,conv_price,first_conv_price,"
            "issue_size,remain_size,call_clause,put_clause,reset_clause,"
            "conv_clause,par,issue_price",
        )
        return self.query("cb_basic", **kwargs)

    def cb_daily(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "ts_code,trade_date,pre_close,open,high,low,close,change,"
            "pct_chg,vol,amount,bond_value,bond_over_rate,cb_value,cb_over_rate",
        )
        return self.query("cb_daily", **kwargs)

    def cb_call(self, **kwargs) -> pd.DataFrame:
        kwargs.setdefault(
            "fields",
            "ts_code,call_type,is_call,ann_date,call_date,call_price,"
            "call_price_tax,call_vol,call_amount,payment_date,call_reg_date",
        )
        return self.query("cb_call", **kwargs)
