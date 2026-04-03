import sys
sys.path.insert(0, 'backend')
from app.execution.feed.data_sync import run_post_market_sync

results = run_post_market_sync('20260401')
targets = ['share_float', 'stk_holdertrade', 'margin', 'hk_hold',
           'top_inst', 'index_dailybasic', 'top10_floatholders', 'stk_holdernumber']
for k, v in results.items():
    if k in targets:
        print(f"{k}: {'OK' if v else 'FAIL'}")
