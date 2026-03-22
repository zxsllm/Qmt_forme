import { useState } from 'react';
import { Button, Space } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import { useMarketFeed } from '../services/useMarketFeed';
import Panel from '../components/Panel';
import ErrorBoundary from '../components/ErrorBoundary';
import AccountCard from '../components/AccountCard';
import KlineChart from '../components/KlineChart';
import TradePlanTable from '../components/TradePlanTable';
import PositionOrderPanel from '../components/PositionOrderPanel';
import RiskPanel from '../components/RiskPanel';
import StrategyPanel from '../components/StrategyPanel';
import LogPanel from '../components/LogPanel';
import OrderSubmitForm from '../components/OrderSubmitForm';

const DEFAULT_CODE = '000001.SZ';

export default function Dashboard() {
  const [quickSide, setQuickSide] = useState<'BUY' | 'SELL' | null>(null);

  const { data: dailyData } = useQuery({
    queryKey: ['stock-daily', DEFAULT_CODE],
    queryFn: () => api.stockDaily(DEFAULT_CODE),
  });

  const { connected } = useMarketFeed();

  return (
    <div className="flex flex-col h-full bg-bg-base" style={{ padding: 16, gap: 10 }}>
      {/* Row 1: compact account stats */}
      <AccountCard />

      {/* Row 2: K-line hero + trading plan sidebar */}
      <div className="flex flex-1" style={{ minHeight: 0, gap: 10 }}>
        <Panel title="活跃订单" className="w-[32%] min-w-72" noPadding secondary>
          <TradePlanTable />
        </Panel>

        <Panel
          title={`K线 · ${DEFAULT_CODE}`}
          className="flex-1"
          noPadding
          extra={
            <Space size={8}>
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
          }
        >
          <ErrorBoundary fallbackMsg="K线图表加载失败">
            <KlineChart data={dailyData?.data || []} autoFill indicators={['MA', 'VOL']} />
          </ErrorBoundary>
        </Panel>
      </div>

      {/* Row 3: Positions/Orders + Risk + Strategy + Logs */}
      <div className="flex shrink-0" style={{ height: 260, gap: 10 }}>
        <PositionOrderPanel className="flex-[2.5] min-w-0" />
        <RiskPanel className="w-72 min-w-56" secondary />
        <div className="flex flex-col w-72 min-w-56" style={{ gap: 10 }}>
          <StrategyPanel className="flex-1" secondary />
          <LogPanel className="flex-1" secondary />
        </div>
      </div>

      {/* Quick order from K-line chart */}
      <OrderSubmitForm
        open={!!quickSide}
        onClose={() => setQuickSide(null)}
        defaultCode={DEFAULT_CODE}
      />
    </div>
  );
}
