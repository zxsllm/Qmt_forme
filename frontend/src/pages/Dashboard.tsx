import { useState } from 'react';
import { Button, Input, Space, Radio } from 'antd';
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

  const { connected } = useMarketFeed();

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
  });

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const bars: any[] = (klineData as { data?: any[] } | undefined)?.data ?? [];
  const latest = period === 'daily' ? bars[bars.length - 1] : undefined;
  const latestClose = (latest as Record<string, unknown>)?.close as number | undefined;
  const latestPctChg = (latest as Record<string, unknown>)?.pct_chg as number | undefined;

  const pctColor = (latestPctChg ?? 0) >= 0 ? '#f87171' : '#4ade80';

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
      <Button size="small" type="primary" danger
        style={{ fontSize: 11, height: 22 }}
        onClick={() => setQuickSide('BUY')}
      >
        买入
      </Button>
      <Button size="small"
        style={{ fontSize: 11, height: 22, background: '#15803d', borderColor: '#15803d', color: '#fff' }}
        onClick={() => setQuickSide('SELL')}
      >
        卖出
      </Button>
      <span style={{ fontSize: 10, color: connected ? '#4ade80' : '#64748b' }}>
        ● {connected ? 'WS' : '离线'}
      </span>
    </Space>
  );

  const titleContent = (
    <Space size={8} align="center">
      <Input.Search
        value={inputVal}
        onChange={(e) => setInputVal(e.target.value.toUpperCase())}
        onSearch={(v) => { if (v) setCode(v.toUpperCase()); }}
        placeholder="股票代码"
        style={{ width: 140 }}
        size="small"
        enterButton="查"
      />
      <span style={{ fontWeight: 600, color: '#e2e8f0' }}>{stockName}</span>
      {latestClose != null && (
        <>
          <span style={{ color: pctColor, fontWeight: 600, fontSize: 14 }}>
            ¥{latestClose.toFixed(2)}
          </span>
          {latestPctChg != null && (
            <span style={{ color: pctColor, fontSize: 12 }}>
              {latestPctChg >= 0 ? '+' : ''}{latestPctChg.toFixed(2)}%
            </span>
          )}
        </>
      )}
    </Space>
  );

  return (
    <div className="flex flex-col h-full bg-bg-base" style={{ padding: 12, gap: 8 }}>
      <AccountCard />

      <Panel title={titleContent} extra={titleExtra} className="flex-1" noPadding style={{ minHeight: 0 }}>
        <div className="flex flex-col h-full">
          <div style={{ flex: 1, minHeight: 0 }}>
            <ErrorBoundary fallbackMsg="K线图表加载失败">
              <KlineChart data={bars} period={period} autoFill indicators={['MA', 'VOL']} />
            </ErrorBoundary>
          </div>
          <StockNewsPanel tsCode={code} height={150} />
        </div>
      </Panel>

      <div className="flex shrink-0" style={{ height: 280, gap: 6 }}>
        <SectorGainPanel />
        <SectorLosePanel />
        <StockGainPanel />
        <StockLosePanel />
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
