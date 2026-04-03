import { useState, useCallback, useRef } from 'react';
import { AutoComplete, Space, Radio, Statistic, Table, Tag } from 'antd';
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

const DEFAULT_CODE = '000001.SH';

const PERIOD_OPTIONS = [
  { label: '分时', value: '1min' as KlinePeriod },
  { label: '日K', value: 'daily' as KlinePeriod },
  { label: '周K', value: 'weekly' as KlinePeriod },
  { label: '月K', value: 'monthly' as KlinePeriod },
];

const isIndexCode = (c: string) =>
  /^(0000|399|880|9)/.test(c) && c.endsWith('.SH') ||
  /^(399|980)/.test(c) && c.endsWith('.SZ') ||
  c.endsWith('.BJ') && /^8990/.test(c);

function DetailStrip({ tsCode, isIdx }: { tsCode: string; isIdx: boolean }) {
  const { data: holderNum } = useQuery({
    queryKey: ['holder-number', tsCode],
    queryFn: () => api.getHolderNumber(tsCode),
    enabled: !isIdx && !!tsCode,
    staleTime: 600_000,
  });
  const { data: top10 } = useQuery({
    queryKey: ['top10-holders', tsCode],
    queryFn: () => api.getTop10Holders(tsCode),
    enabled: !isIdx && !!tsCode,
    staleTime: 600_000,
  });

  const listH = 114;

  return (
    <div style={{ borderTop: '1px solid rgba(148,186,215,0.10)' }}>
      <StockNewsPanel tsCode={tsCode} height={150} extraTabs={isIdx ? undefined : [
        {
          key: 'holders',
          label: '股东人数',
          node: (
            <div style={{ overflowY: 'auto', height: listH, padding: '4px 12px' }}>
              <Table
                dataSource={(holderNum?.data ?? []) as Record<string, unknown>[]}
                rowKey={(_, i) => String(i)}
                size="small"
                pagination={false}
                scroll={{ y: listH - 30 }}
                columns={[
                  { title: '日期', dataIndex: 'end_date', width: 80, render: (v: string) => v || '-' },
                  { title: '股东数', dataIndex: 'holder_num', width: 80, align: 'right',
                    render: (v: number) => v ? v.toLocaleString() : '-' },
                  { title: '环比(%)', dataIndex: 'holder_num_change', width: 80, align: 'right',
                    render: (v: number | null) => v != null
                      ? <span style={{ color: v > 0 ? '#ff6f91' : v < 0 ? '#4ade80' : '#93a9bc' }}>{v > 0 ? '+' : ''}{v.toFixed(2)}</span>
                      : '-' },
                ]}
              />
            </div>
          ),
        },
        {
          key: 'top10',
          label: '十大股东',
          node: (
            <div style={{ overflowY: 'auto', height: listH, padding: '4px 12px' }}>
              <Table
                dataSource={(top10?.data ?? []) as Record<string, unknown>[]}
                rowKey={(_, i) => String(i)}
                size="small"
                pagination={false}
                scroll={{ y: listH - 30 }}
                columns={[
                  { title: '报告期', dataIndex: 'end_date', width: 80 },
                  { title: '股东名称', dataIndex: 'holder_name', ellipsis: true },
                  { title: '持股(万)', dataIndex: 'hold_amount', width: 80, align: 'right',
                    render: (v: number) => v ? (v / 1e4).toFixed(0) : '-' },
                  { title: '占比(%)', dataIndex: 'hold_ratio', width: 70, align: 'right',
                    render: (v: number) => v != null ? v.toFixed(2) : '-' },
                  { title: '增减', dataIndex: 'hold_change', width: 75, align: 'right',
                    render: (v: number | null) => {
                      if (v == null) return <Tag color="default" style={{ margin: 0 }}>新进</Tag>;
                      if (v > 0) return <span style={{ color: '#ff6f91' }}>+{(v / 1e4).toFixed(0)}万</span>;
                      if (v < 0) return <span style={{ color: '#4ade80' }}>{(v / 1e4).toFixed(0)}万</span>;
                      return <span style={{ color: '#93a9bc' }}>不变</span>;
                    } },
                ]}
              />
            </div>
          ),
        },
      ]} />
    </div>
  );
}

export default function Dashboard() {
  const [code, setCode] = useState(DEFAULT_CODE);
  const [inputVal, setInputVal] = useState(DEFAULT_CODE);
  const [period, setPeriod] = useState<KlinePeriod>('daily');
  const [quickSide, setQuickSide] = useState<'BUY' | 'SELL' | null>(null);
  const [searchOptions, setSearchOptions] = useState<{ value: string; label: React.ReactNode }[]>([]);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const { connected } = useMarketFeed();
  const isIdx = isIndexCode(code);

  const handleStockSelect = useCallback((tsCode: string) => {
    setCode(tsCode);
    setInputVal(tsCode);
  }, []);

  const { data: valuation } = useQuery({
    queryKey: ['index-valuation', code],
    queryFn: () => api.indexValuation(code, '', '', 1),
    enabled: isIdx && !!code,
    staleTime: 300_000,
  });
  const valRow = (valuation?.data?.length ?? 0) > 0 ? valuation!.data[valuation!.data.length - 1] : null;

  const onSearchInput = useCallback((text: string) => {
    setInputVal(text);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!text || text.length < 1) { setSearchOptions([]); return; }

    debounceRef.current = setTimeout(async () => {
      try {
        const res = await api.searchStocks(text, true);
        setSearchOptions(
          res.data.map((s) => {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const isIndex = (s as any).type === 'index' || s.list_status === 'INDEX';
            return {
              value: s.ts_code,
              label: (
                <span>
                  <b style={{ color: isIndex ? '#faad14' : '#6bc7ff' }}>{s.ts_code}</b>
                  <span style={{ marginLeft: 8, color: '#93a9bc', fontSize: 12 }}>
                    {s.name}
                  </span>
                  {isIndex && (
                    <span style={{ marginLeft: 6, color: '#faad14', fontSize: 11 }}>[指数]</span>
                  )}
                </span>
              ),
            };
          }),
        );
      } catch {
        setSearchOptions([]);
      }
    }, 200);
  }, []);

  const { data: stockInfo } = useQuery({
    queryKey: ['stock-search-info', code],
    queryFn: () => api.searchStocks(code, true),
    enabled: !!code,
  });

  const stockName = stockInfo?.data?.find(s => s.ts_code === code)?.name
    ?? stockInfo?.data?.[0]?.name ?? '';

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
    refetchInterval: period === '1min' ? 5_000 : undefined,
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
                isIndex={isIdx}
              />
            </ErrorBoundary>
          </div>
          {isIdx && valRow && (
            <div style={{
              display: 'flex', gap: 16, padding: '6px 14px',
              background: 'rgba(107,199,255,0.04)',
              borderTop: '1px solid rgba(148,186,215,0.10)',
            }}>
              {[
                { title: 'PE', val: (valRow.pe as number)?.toFixed(1) },
                { title: 'PE(TTM)', val: (valRow.pe_ttm as number)?.toFixed(1) },
                { title: 'PB', val: (valRow.pb as number)?.toFixed(2) },
                { title: '换手率', val: `${(valRow.turnover_rate as number)?.toFixed(2)}%` },
                { title: '总市值', val: (() => { const v = valRow.total_mv as number; return v >= 1e8 ? `${(v / 1e8).toFixed(1)}万亿` : v >= 1e4 ? `${(v / 1e4).toFixed(0)}亿` : String(v ?? '-'); })() },
              ].map(s => (
                <Statistic key={s.title} title={s.title} value={s.val ?? '-'}
                  valueStyle={{ fontSize: 13, color: '#e6f1fa', fontWeight: 500 }}
                  style={{ minWidth: 80 }}
                />
              ))}
            </div>
          )}
          <DetailStrip tsCode={code} isIdx={isIdx} />
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
