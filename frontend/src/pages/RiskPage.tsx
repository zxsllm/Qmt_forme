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
    <div className="flex flex-col h-full bg-bg-base" style={{ padding: 16, gap: 10 }}>
      <div className="flex" style={{ gap: 10, minHeight: 240 }}>
        <RiskPanel className="flex-1" />
        <Panel title="行情调度器" className="w-80">
          <div className="text-[12px]" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div className="flex justify-between">
              <span className="text-t3">状态</span>
              <span className={feed?.running ? 'text-green-400' : 'text-t4'}>
                {feed?.running ? '运行中' : '已停止'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-t3">交易时段</span>
              <span className={feed?.trading_time ? 'text-green-400' : 'text-t4'}>
                {feed?.trading_time ? '是' : '否'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-t3">监控股票</span>
              <span className="text-t1">{feed?.watch_codes ?? 0} 只</span>
            </div>
          </div>
        </Panel>
      </div>
      <LogPanel className="flex-1" />
    </div>
  );
}
