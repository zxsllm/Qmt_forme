import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = "postgresql+asyncpg://postgres:zxslchj12345@localhost:5432/ai_trade"

async def check_data():
    """检查龙头隔夜模式所需的历史数据完整度"""
    
    engine = create_async_engine(DATABASE_URL, echo=False)
    
    async with engine.begin() as conn:
        print("=" * 80)
        print("龙头隔夜模式 - 5/6 9:30 开盘前数据完整度检查")
        print("=" * 80)
        
        # 1. 4/30 daily_sector_review
        print("\n1. 4/30 daily_sector_review 板块成员（bankuai+daily scope）")
        result = await conn.execute(
            sa.text("""
            SELECT COUNT(*) as cnt 
            FROM daily_sector_review 
            WHERE trade_date = '20250430' 
              AND source = 'bankuai'
              AND raw_meta->>'scope' = 'daily'
            """)
        )
        cnt = (await result.first())[0]
        print(f"   {'✓' if cnt > 0 else '✗'} {cnt} 条")
        
        # 2. 4/30 limit_stats
        print("\n2. 4/30 limit_stats 当日涨停股（first_time + open_times）")
        result = await conn.execute(
            sa.text("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN first_time IS NOT NULL THEN 1 ELSE 0 END) as with_first_time,
                   SUM(CASE WHEN open_times IS NOT NULL THEN 1 ELSE 0 END) as with_open_times
            FROM limit_stats
            WHERE trade_date = '20250430'
            """)
        )
        row = await result.first()
        total, with_first_time, with_open_times = row
        status = "✓" if total > 0 and with_first_time == total and with_open_times == total else "⚠" if total > 0 else "✗"
        print(f"   {status} 总{total}|first_time{with_first_time}|open_times{with_open_times}")
        
        # 3. 4/30 limit_list_ths
        print("\n3. 4/30 limit_list_ths 'X天Y板' tag 完整性")
        result = await conn.execute(
            sa.text("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN tag IS NOT NULL AND tag != '' THEN 1 ELSE 0 END) as with_tag
            FROM limit_list_ths
            WHERE trade_date = '20250430'
            """)
        )
        row = await result.first()
        total, with_tag = row
        status = "✓" if total > 0 and with_tag == total else "⚠" if total > 0 else "✗"
        print(f"   {status} 总{total}|有tag{with_tag}")
        
        # 4. 4/30 日线 & 分钟线
        print("\n4. 4/30 日线 & 分钟线数据完整性")
        
        result = await conn.execute(sa.text("SELECT COUNT(*) FROM stock_daily WHERE trade_date = '20250430'"))
        sd_cnt = (await result.first())[0] or 0
        
        result = await conn.execute(sa.text("SELECT COUNT(*) FROM cb_daily WHERE trade_date = '20250430'"))
        cb_cnt = (await result.first())[0] or 0
        
        result = await conn.execute(sa.text("SELECT COUNT(*) FROM stock_min_kline WHERE DATE(trade_time) = '2025-04-30'"))
        skm_cnt = (await result.first())[0] or 0
        
        result = await conn.execute(sa.text("SELECT COUNT(*) FROM cb_min_kline WHERE DATE(trade_time) = '2025-04-30'"))
        cbm_cnt = (await result.first())[0] or 0
        
        status = "✓" if sd_cnt > 0 and skm_cnt > 0 else "⚠"
        print(f"   {status} stock_daily:{sd_cnt} cb_daily:{cb_cnt} stock_min:{skm_cnt} cb_min:{cbm_cnt}")
        
        # 5. 5/1-5/5 假期标记
        print("\n5. 5/1~5/5 五一假期 is_open=0 确认")
        result = await conn.execute(
            sa.text("""
            SELECT COUNT(*) as correct FROM trade_cal
            WHERE cal_date IN ('20250501','20250502','20250503','20250504','20250505')
              AND is_open = 0
            """)
        )
        correct = (await result.first())[0] or 0
        status = "✓" if correct == 5 else "✗"
        print(f"   {status} {correct}/5 正确标记为闭市")
        
        # 6. 5/6 stock_daily 盘前状态
        print("\n6. 5/6 stock_daily 当日（盘前应为空）")
        result = await conn.execute(sa.text("SELECT COUNT(*) FROM stock_daily WHERE trade_date = '20250506'"))
        cnt = (await result.first())[0] or 0
        status = "✓" if cnt == 0 else "⚠"
        print(f"   {status} {cnt} 条（{'正确' if status == '✓' else '警告'}）")
        
        # 7. 5/6 trade_cal is_open=1
        print("\n7. 5/6 trade_cal is_open=1 确认")
        result = await conn.execute(sa.text("SELECT is_open FROM trade_cal WHERE cal_date = '20250506'"))
        row = await result.first()
        if row and row[0] == 1:
            print(f"   ✓ 已标记为开市")
        else:
            print(f"   ✗ 缺失或未标记为开市")
        
        print("\n" + "=" * 80)
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check_data())
