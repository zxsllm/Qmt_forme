import { useState } from 'react';
import { Input, Descriptions } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import Panel from '../components/Panel';
import ErrorBoundary from '../components/ErrorBoundary';
import KlineChart from '../components/KlineChart';

export default function KlinePage() {
  const [code, setCode] = useState('000001.SZ');
  const [inputVal, setInputVal] = useState('000001.SZ');

  const { data, isLoading } = useQuery({
    queryKey: ['stock-daily-full', code],
    queryFn: () => api.stockDaily(code),
    enabled: !!code,
  });

  const latest = data?.data?.[data.data.length - 1];

  return (
    <div className="flex flex-col h-full" style={{ padding: 18, gap: 12 }}>
      <Panel>
        <div className="flex items-center gap-3">
          <span style={{ color: '#93a9bc', fontSize: 13 }}>股票代码:</span>
          <Input.Search
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value.toUpperCase())}
            onSearch={(v) => v && setCode(v.toUpperCase())}
            placeholder="如 000001.SZ"
            style={{ width: 200 }}
            size="small"
            enterButton="查询"
            loading={isLoading}
          />
          {latest && (
            <Descriptions size="small" column={5} className="ml-4 flex-1">
              <Descriptions.Item label="收盘">
                <span style={{ color: (latest.pct_chg ?? 0) >= 0 ? '#ff6f91' : '#4ade80' }}>
                  {latest.close?.toFixed(2)}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="涨跌%">
                <span style={{ color: (latest.pct_chg ?? 0) >= 0 ? '#ff6f91' : '#4ade80' }}>
                  {latest.pct_chg != null ? `${latest.pct_chg >= 0 ? '+' : ''}${latest.pct_chg.toFixed(2)}%` : '-'}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="PE">{latest.pe?.toFixed(1) ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="PB">{latest.pb?.toFixed(2) ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="换手率">{latest.turnover_rate?.toFixed(2) ?? '-'}%</Descriptions.Item>
            </Descriptions>
          )}
        </div>
      </Panel>

      <Panel title={`K线图 · ${code}`} className="flex-1" noPadding style={{ minHeight: 0 }}>
        <ErrorBoundary fallbackMsg="K线图表加载失败">
          <KlineChart data={data?.data || []} height={560} indicators={['MA', 'VOL', 'MACD']} />
        </ErrorBoundary>
      </Panel>
    </div>
  );
}
