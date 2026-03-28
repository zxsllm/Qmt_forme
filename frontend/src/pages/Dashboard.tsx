import { useState, useCallback, useRef } from 'react';
import { AutoComplete, Space, Radio } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import { useMarketFeed } from '../services/useMarketFeed';
import type { KlinePeriod } from '../components/KlineChart';
import Panel from '../components/Panel';
import ErrorBoundary from '../components/ErrorBoundary';
import AccountCard from '../components/AccountCard';
import KlineChart from '../components/KlineChart';
import StockNewsPanel from '../components/StockNewsPanel';
import OrderSubmitForm from '../components/OrderSubmitForm';
import SectorGainPanel from '../components/rankings/SectorGainPanel';
import SectorLosePanel from '../components/rankings/SectorLosePanel';
import StockGainPanel from '../components/rankings/StockGainPanel';
import StockLosePanel from '../components/rankings/StockLosePanel';
import TurnoverPanel from '../components/rankings/TurnoverPanel';
import MoneyFlowPanel from '../components/rankings/MoneyFlowPanel';
import GlobalIndexPanel from '../components/rankings/GlobalIndexPanel';

const DEFAULT_CODE = '000001.SZ';

const PERIOD_OPTIONS = [
  { label: '分时', value: '1min' as KlinePeriod },
  { label: '日K', value: 'daily' as KlinePeriod },
  { label: '周K', value: 'weekly' as KlinePeriod },
  { label: '月K', value: 'monthly' as KlinePeriod },
];

export default function Dashboard() {
  const [code, setCode] = useState(DEFAULT_CODE);
  const [inputVal, setInputVal] = useState(DEFAULT_CODE);
  const [period, setPeriod] = useState<KlinePeriod>('daily');
  const [quickSide, setQuickSide] = useState<'BUY' | 'SELL' | null>(null);
  const [searchOptions, setSearchOptions] = useState<{ value: string; label: React.ReactNode }[]>([]);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const { connected } = useMarketFeed();

  const handleStockSelect = useCallback((tsCode: string) => {
    setCode(tsCode);
    setInputVal(tsCode);
  }, []);

  const onSearchInput = useCallback((text: string) => {
    setInputVal(text);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!text || text.length < 1) { setSearchOptions([]); return; }

    debounceRef.current = setTimeout(async () => {
      try {
        const res = await api.searchStocks(text);
        setSearchOptions(
          res.data.map((s) => ({
            value: s.ts_code,
            label: (
              <span>
                <b style={{ color: '#6bc7ff' }}>{s.ts_code}</b>
                <span style={{ marginLeft: 8, color: '#93a9bc', fontSize: 12 }}>
                  {s.name}
                </span>
              </span>
            ),
          })),
        );
      } catch {
        setSearchOptions([]);
      }
    }, 200);
  }, []);

  const { data: stockInfo } = useQuery({
    queryKey: ['stock-search-info', code],
    queryFn: () => api.searchStocks(code.split('.')[0]),
    enabled: !!code,
  });

  const stockName = stockInfo?.data?.[0]?.name ?? '';

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fetchFn = (): Promise<any> => {
    switch (period) {
      case '1min': return api.stockMinutes(code);
      case 'weekly': return api.stockWeekly(code);
      case 'monthly': return api.stockMonthly(code);
      default: return api.stockDaily(code);
    }
  };

  const { data: klineData } = useQuery({
    queryKey: ['kline-data', code, period],
    queryFn: fetchFn,
    enabled: !!code,
    refetchInterval: period === '1min' ? 30_000 : undefined,
  });

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const bars: any[] = (klineData as { data?: any[] } | undefined)?.data ?? [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const preCloseFromApi = (klineData as any)?.pre_close as number | undefined;
  const lastBar = bars.length > 0 ? bars[bars.length - 1] : undefined;
  const latestClose = (lastBar as Record<string, unknown>)?.close as number | undefined;
  const latestPctChg = (lastBar as Record<string, unknown>)?.pct_chg as number | undefined;
  const preClose = preCloseFromApi ?? (lastBar as Record<string, unknown>)?.pre_close as number | undefined;
  const computedPctChg = latestPctChg ?? (latestClose && preClose && preClose > 0
    ? ((latestClose - preClose) / preClose) * 100
    : undefined);

  const pctColor = (computedPctChg ?? 0) >= 0 ? '#ff6f91' : '#4ade80';

  const titleExtra = (
    <Space size={8} align="center">
      <Radio.Group
        size="small"
        value={period}
        onChange={(e) => setPeriod(e.target.value)}
        optionType="button"
        buttonStyle="solid"
        options={PERIOD_OPTIONS}
      />
      <button
        className="shrink-0"
        style={{
          background: 'linear-gradient(135deg, #99502c, #b54f61)',
          border: 0,
          borderRadius: 14,
          padding: '4px 10px',
          fontSize: 11,
          fontWeight: 600,
          color: '#f3fbff',
          cursor: 'pointer',
        }}
        onClick={() => setQuickSide('BUY')}
      >
        买入
      </button>
      <button
        className="shrink-0"
        style={{
          background: 'linear-gradient(135deg, #15803d, #22c55e)',
          border: 0,
          borderRadius: 14,
          padding: '4px 10px',
          fontSize: 11,
          fontWeight: 600,
          color: '#f3fbff',
          cursor: 'pointer',
        }}
        onClick={() => setQuickSide('SELL')}
      >
        卖出
      </button>
      <span style={{ fontSize: 10, color: connected ? '#4ade80' : '#334155' }}>
        ● {connected ? 'WS' : '离线'}
      </span>
    </Space>
  );

  const titleContent = (
    <Space size={8} align="center">
      <AutoComplete
        value={inputVal}
        options={searchOptions}
        onSearch={onSearchInput}
        onSelect={(v: string) => { setCode(v); setInputVal(v); }}
        placeholder="代码/名称/拼音"
        style={{ width: 180 }}
        size="small"
      />
      <span style={{ fontWeight: 600, color: '#e6f1fa' }}>{stockName}</span>
      {latestClose != null && (
        <>
          <span style={{ color: pctColor, fontWeight: 600, fontSize: 14 }}>
            ¥{latestClose.toFixed(2)}
          </span>
          {computedPctChg != null && (
            <span style={{ color: pctColor, fontSize: 12 }}>
              {computedPctChg >= 0 ? '+' : ''}{computedPctChg.toFixed(2)}%
            </span>
          )}
        </>
      )}
    </Space>
  );

  return (
    <div className="flex flex-col h-full" style={{ padding: 18, gap: 12 }}>
      <AccountCard />

      <Panel title={titleContent} extra={titleExtra} className="flex-1" noPadding style={{ minHeight: 0 }}>
        <div className="flex flex-col h-full">
          <div style={{ flex: 1, minHeight: 0 }}>
            <ErrorBoundary fallbackMsg="K线图表加载失败">
              <KlineChart
                data={bars}
                period={period}
                autoFill
                indicators={period === '1min' ? ['VOL'] : ['MA', 'VOL']}
                preClose={preClose}
              />
            </ErrorBoundary>
          </div>
          <StockNewsPanel tsCode={code} height={150} />
        </div>
      </Panel>

      <div className="flex shrink-0" style={{ height: 280, gap: 10 }}>
        <SectorGainPanel onStockClick={handleStockSelect} />
        <SectorLosePanel onStockClick={handleStockSelect} />
        <StockGainPanel onStockClick={handleStockSelect} />
        <StockLosePanel onStockClick={handleStockSelect} />
        <TurnoverPanel />
        <MoneyFlowPanel />
        <GlobalIndexPanel />
      </div>

      <OrderSubmitForm
        open={!!quickSide}
        onClose={() => setQuickSide(null)}
        defaultCode={code}
      />
    </div>
  );
}
