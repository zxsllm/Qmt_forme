import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import Panel from '../components/Panel';
import RiskPanel from '../components/RiskPanel';
import LogPanel from '../components/LogPanel';

export default function RiskPage() {
  const { data: feed } = useQuery({
    queryKey: ['feed-status'],
    queryFn: api.getFeedStatus,
    refetchInterval: 5000,
  });

  return (
    <div className="flex flex-col h-full" style={{ padding: 18, gap: 12 }}>
      <div className="flex" style={{ gap: 12, minHeight: 240 }}>
        <RiskPanel className="flex-1" />
        <Panel title="行情调度器" className="w-80">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 12 }}>
            <div className="flex justify-between">
              <span style={{ color: '#93a9bc' }}>状态</span>
              <span style={{ color: feed?.running ? '#4ade80' : '#334155' }}>
                {feed?.running ? '运行中' : '已停止'}
              </span>
            </div>
            <div className="flex justify-between">
              <span style={{ color: '#93a9bc' }}>交易时段</span>
              <span style={{ color: feed?.trading_time ? '#4ade80' : '#334155' }}>
                {feed?.trading_time ? '是' : '否'}
              </span>
            </div>
            <div className="flex justify-between">
              <span style={{ color: '#93a9bc' }}>监控股票</span>
              <span style={{ color: '#e6f1fa' }}>{feed?.watch_codes ?? 0} 只</span>
            </div>
          </div>
        </Panel>
      </div>
      <LogPanel className="flex-1" />
    </div>
  );
}
