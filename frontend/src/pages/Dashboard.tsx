import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import Panel from '../components/Panel';
import ErrorBoundary from '../components/ErrorBoundary';
import AccountCard from '../components/AccountCard';
import KlineChart from '../components/KlineChart';
import TradePlanTable from '../components/TradePlanTable';
import PositionOrderPanel from '../components/PositionOrderPanel';
import RiskPanel from '../components/RiskPanel';
import StrategyPanel from '../components/StrategyPanel';
import LogPanel from '../components/LogPanel';

const DEFAULT_CODE = '000001.SZ';

export default function Dashboard() {
  const { data: dailyData } = useQuery({
    queryKey: ['stock-daily', DEFAULT_CODE],
    queryFn: () => api.stockDaily(DEFAULT_CODE),
  });

  return (
    <div className="flex flex-col h-full bg-bg-base" style={{ padding: 16, gap: 10 }}>
      {/* Row 1: compact account stats */}
      <AccountCard />

      {/* Row 2: K-line hero + trading plan sidebar */}
      <div className="flex flex-1" style={{ minHeight: 0, gap: 10 }}>
        <Panel title="交易计划" className="w-[32%] min-w-72" noPadding secondary>
          <TradePlanTable />
        </Panel>

        <Panel title={`K线 · ${DEFAULT_CODE}`} className="flex-1" noPadding>
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
    </div>
  );
}
