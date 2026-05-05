"""对比 4-29 和 4-30 的 ts_code 覆盖差异，看 4-30 缺的票有什么共同点。"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from app.core.config import settings


def main():
    eng = create_engine(settings.DATABASE_URL.replace("+asyncpg","+psycopg"))
    with eng.connect() as conn:
        d29 = {r[0] for r in conn.execute(text(
            "SELECT DISTINCT ts_code FROM stock_min_kline "
            "WHERE freq='1min' AND trade_time::date='2026-04-29'"
        )).fetchall()}
        d30 = {r[0] for r in conn.execute(text(
            "SELECT DISTINCT ts_code FROM stock_min_kline "
            "WHERE freq='1min' AND trade_time::date='2026-04-30'"
        )).fetchall()}
        l_codes = {r[0] for r in conn.execute(text(
            "SELECT ts_code FROM stock_basic WHERE list_status='L'"
        )).fetchall()}
        print(f"4-29 ts_code: {len(d29)}")
        print(f"4-30 ts_code: {len(d30)}")
        print(f"stock_basic L: {len(l_codes)}")

        miss_30 = (l_codes & d29) - d30  # 4-29 有但 4-30 没有，且仍然在挂牌的
        print(f"\n4-29 有 / 4-30 缺 / 仍 L 状态：{len(miss_30)} 只")

        # 看缺的票里多少在停牌表 suspend_d
        if miss_30:
            sample = list(miss_30)
            placeholders = ",".join(f"'{c}'" for c in sample)
            sus = conn.execute(text(
                f"SELECT ts_code, suspend_timing FROM suspend_d "
                f"WHERE trade_date='20260430' AND ts_code IN ({placeholders})"
            )).fetchall()
            print(f"  其中 suspend_d 中 4-30 标记停牌：{len(sus)} 只")

            # 当天 stock_daily 是否有该票成交（停牌当天没成交）
            no_daily = conn.execute(text(
                f"SELECT COUNT(*) FROM stock_daily "
                f"WHERE trade_date='20260430' AND ts_code IN ({placeholders})"
            )).scalar()
            print(f"  其中 4-30 stock_daily 有日 K：{no_daily} / {len(miss_30)}")

            # 没在 suspend_d、也没在 stock_daily 的——真"丢了"
            sus_set = {r[0] for r in sus}
            with_daily = {r[0] for r in conn.execute(text(
                f"SELECT ts_code FROM stock_daily "
                f"WHERE trade_date='20260430' AND ts_code IN ({placeholders})"
            )).fetchall()}
            truly_missing = miss_30 - sus_set - (set(sample) - with_daily)
            # 简化：在 stock_daily 里有日 K 但 stock_min_kline 缺分钟线 → 真异常
            print(f"  4-30 有日 K（说明当天交易了）但分钟线缺失 = 真异常：{len(with_daily - d30)}")
            real_missing = sorted(with_daily - d30)
            print(f"  真异常样本（前 30）：{real_missing[:30]}")

            # 失败的那 1 只是不是 000695.SZ
            print(f"\n  日志报告失败的 000695.SZ 是否在 4-30 表里：{'000695.SZ' in d30}")
            print(f"  000695.SZ 在 stock_basic：list_status={conn.execute(text('SELECT list_status FROM stock_basic WHERE ts_code=:c'), {'c':'000695.SZ'}).scalar()}")

    eng.dispose()


if __name__ == "__main__":
    main()
