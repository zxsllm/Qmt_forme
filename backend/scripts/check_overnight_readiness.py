"""Longtou overnight mode - Data completeness check for 5/6 9:30 AM market open"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from app.core.config import settings


def main():
    # Convert async URL to sync (psycopg instead of asyncpg)
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
    print(f"[DB] {sync_url.split('@')[0]}...@...{sync_url.split('/')[-1]}")
    
    try:
        eng = create_engine(sync_url, echo=False)
        conn = eng.connect()
    except Exception as e:
        print(f"[FAIL] DB connection: {e}")
        print("[NOTE] Install psycopg2 or psycopg3 for PostgreSQL")
        return

    print("\n" + "=" * 80)
    print("Longtou Overnight Mode - Data Readiness Check (5/6 9:30 AM)")
    print("=" * 80)
    
    blocker_list = []
    
    # ─────────────────────────────────────────────────────────────
    # 1. 4/30 daily_sector_review (source='bankuai', scope='daily')
    # ─────────────────────────────────────────────────────────────
    print("\n1. 4/30 daily_sector_review members (bankuai+daily scope)")
    try:
        result = conn.execute(text("""
            SELECT COUNT(*) as cnt 
            FROM daily_sector_review 
            WHERE trade_date = '20250430' 
              AND source = 'bankuai'
              AND raw_meta->>'scope' = 'daily'
        """))
        cnt = result.scalar()
        if cnt > 0:
            print(f"   [OK] {cnt} records")
        else:
            print(f"   [MISS] 0 records")
            blocker_list.append("daily_sector_review 4/30 missing")
    except Exception as e:
        print(f"   [ERR] Query failed: {str(e)[:60]}")
        blocker_list.append("daily_sector_review query error")
    
    # ─────────────────────────────────────────────────────────────
    # 2. 4/30 limit_stats (first_time, open_times completeness)
    # ─────────────────────────────────────────────────────────────
    print("\n2. 4/30 limit_stats daily limit-up stocks (first_time + open_times)")
    try:
        result = conn.execute(text("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN first_time IS NOT NULL THEN 1 ELSE 0 END) as with_first_time,
                   SUM(CASE WHEN open_times IS NOT NULL THEN 1 ELSE 0 END) as with_open_times
            FROM limit_stats
            WHERE trade_date = '20250430'
        """))
        row = result.first()
        total, with_first_time, with_open_times = row if row else (0, 0, 0)
        
        if total == 0:
            print(f"   [MISS] 0 records")
            blocker_list.append("limit_stats 4/30 completely missing")
        elif with_first_time == total and with_open_times == total:
            print(f"   [OK] {total} records, fields complete")
        else:
            print(f"   [WARN] total={total}, first_time={with_first_time}, open_times={with_open_times}")
            if with_first_time < total * 0.95 or with_open_times < total * 0.95:
                blocker_list.append("limit_stats missing >5% fields")
    except Exception as e:
        print(f"   [ERR] Query failed: {str(e)[:60]}")
        blocker_list.append("limit_stats query error")
    
    # ─────────────────────────────────────────────────────────────
    # 3. 4/30 limit_list_ths 'X_day_Y_board' tag completeness
    # ─────────────────────────────────────────────────────────────
    print("\n3. 4/30 limit_list_ths 'X day Y board' tag (parse board count)")
    try:
        result = conn.execute(text("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN tag IS NOT NULL AND tag != '' THEN 1 ELSE 0 END) as with_tag
            FROM limit_list_ths
            WHERE trade_date = '20250430'
        """))
        row = result.first()
        total, with_tag = row if row else (0, 0)
        
        if total == 0:
            print(f"   [MISS] 0 records")
            blocker_list.append("limit_list_ths 4/30 completely missing")
        elif with_tag == total:
            print(f"   [OK] {total} records, tags complete")
        else:
            print(f"   [WARN] total={total}, with_tag={with_tag}")
            if with_tag < total * 0.95:
                blocker_list.append("limit_list_ths missing >5% tags")
    except Exception as e:
        print(f"   [ERR] Query failed: {str(e)[:60]}")
        blocker_list.append("limit_list_ths query error")
    
    # ─────────────────────────────────────────────────────────────
    # 4. 4/30 Daily & Minute-bar data completeness
    # ─────────────────────────────────────────────────────────────
    print("\n4. 4/30 Daily bars & minute-bars completeness")
    try:
        result = conn.execute(text("SELECT COUNT(*) FROM stock_daily WHERE trade_date = '20250430'"))
        sd_cnt = result.scalar() or 0
        
        result = conn.execute(text("SELECT COUNT(*) FROM cb_daily WHERE trade_date = '20250430'"))
        cb_cnt = result.scalar() or 0
        
        result = conn.execute(text("SELECT COUNT(*) FROM stock_min_kline WHERE DATE(trade_time)::text = '2025-04-30'"))
        skm_cnt = result.scalar() or 0
        
        result = conn.execute(text("SELECT COUNT(*) FROM cb_min_kline WHERE DATE(trade_time)::text = '2025-04-30'"))
        cbm_cnt = result.scalar() or 0
        
        if sd_cnt == 0 or skm_cnt == 0:
            print(f"   [MISS] stock_daily={sd_cnt}, stock_min={skm_cnt}")
            blocker_list.append("4/30 daily or minute-bar data missing")
        else:
            print(f"   [OK] stock_daily={sd_cnt}, cb_daily={cb_cnt}, stock_min={skm_cnt}, cb_min={cbm_cnt}")
    except Exception as e:
        print(f"   [ERR] Query failed: {str(e)[:60]}")
        blocker_list.append("Daily/minute-bar query error")
    
    # ─────────────────────────────────────────────────────────────
    # 5. 5/1 ~ 5/5 Labor Day holiday trade_cal marking
    # ─────────────────────────────────────────────────────────────
    print("\n5. 5/1~5/5 Labor Day holiday is_open=0 confirmation")
    try:
        result = conn.execute(text("""
            SELECT COUNT(*) as correct FROM trade_cal
            WHERE cal_date IN ('20250501','20250502','20250503','20250504','20250505')
              AND is_open = 0
        """))
        correct = result.scalar() or 0
        
        if correct == 5:
            print(f"   [OK] All 5 days marked as closed")
        else:
            print(f"   [MISS] Only {correct}/5 correct")
            blocker_list.append(f"Holiday marking incomplete ({correct}/5)")
    except Exception as e:
        print(f"   [ERR] Query failed: {str(e)[:60]}")
        blocker_list.append("Holiday marking query error")
    
    # ─────────────────────────────────────────────────────────────
    # 6. 5/6 stock_daily pre-market (should be empty)
    # ─────────────────────────────────────────────────────────────
    print("\n6. 5/6 stock_daily pre-market (should be empty)")
    try:
        result = conn.execute(text("SELECT COUNT(*) FROM stock_daily WHERE trade_date = '20250506'"))
        cnt = result.scalar() or 0
        
        if cnt == 0:
            print(f"   [OK] Empty (correct for pre-market)")
        else:
            print(f"   [WARN] {cnt} records (non-empty)")
    except Exception as e:
        print(f"   [ERR] Query failed: {str(e)[:60]}")
    
    # ─────────────────────────────────────────────────────────────
    # 7. 5/6 trade_cal is_open=1 confirmation
    # ─────────────────────────────────────────────────────────────
    print("\n7. 5/6 trade_cal is_open=1 confirmation")
    try:
        result = conn.execute(text("SELECT is_open FROM trade_cal WHERE cal_date = '20250506'"))
        row = result.first()
        
        if row and row[0] == 1:
            print(f"   [OK] Marked as market open")
        else:
            print(f"   [MISS] Not marked or missing")
            blocker_list.append("5/6 trade_cal not marked as open")
    except Exception as e:
        print(f"   [ERR] Query failed: {str(e)[:60]}")
        blocker_list.append("trade_cal query error")
    
    # ─────────────────────────────────────────────────────────────
    # Summary Report
    # ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    if blocker_list:
        print(f"\n[BLOCKER] {len(blocker_list)} blocking issue(s):")
        for i, blocker in enumerate(blocker_list, 1):
            print(f"   {i}. {blocker}")
        print("\n[ACTION] Strategy cannot run. Data gaps must be filled first.")
    else:
        print("\n[SUCCESS] All critical data complete. Strategy ready for live trading.")
    
    print("=" * 80)
    
    conn.close()
    eng.dispose()


if __name__ == "__main__":
    main()
