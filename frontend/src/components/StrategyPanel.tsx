import { Switch, message } from 'antd';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import Panel from './Panel';

const AVAILABLE_STRATEGIES = [
  { name: 'ma_crossover', description: 'MA金叉/死叉', defaultCodes: ['000001.SZ'] },
];

export default function StrategyPanel({ className = '', secondary = false }: { className?: string; secondary?: boolean }) {
  const qc = useQueryClient();

  const { data: runnerStatus } = useQuery({
    queryKey: ['strategy-runner'],
    queryFn: api.getRunningStrategies,
    refetchInterval: 5000,
  });

  const runningNames = new Set(runnerStatus?.strategies?.map((s) => s.name) ?? []);

  const startMut = useMutation({
    mutationFn: (name: string) => {
      const cfg = AVAILABLE_STRATEGIES.find((s) => s.name === name);
      return api.startStrategy({
        strategy_name: name,
        codes: cfg?.defaultCodes ?? ['000001.SZ'],
      });
    },
    onSuccess: () => {
      message.success('策略已启动');
      qc.invalidateQueries({ queryKey: ['strategy-runner'] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const stopMut = useMutation({
    mutationFn: (name: string) => api.stopStrategy(name),
    onSuccess: () => {
      message.success('策略已停止');
      qc.invalidateQueries({ queryKey: ['strategy-runner'] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const handleToggle = (name: string, checked: boolean) => {
    if (checked) startMut.mutate(name);
    else stopMut.mutate(name);
  };

  return (
    <Panel title="策略" className={className} noPadding secondary={secondary}>
      {AVAILABLE_STRATEGIES.map((s) => {
        const running = runningNames.has(s.name);
        const info = runnerStatus?.strategies?.find((r) => r.name === s.name);
        return (
          <div
            key={s.name}
            className="flex items-center justify-between border-b border-edge"
            style={{ padding: '8px 16px' }}
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span
                  className="inline-block rounded-full shrink-0"
                  style={{ width: 6, height: 6, background: running ? 'var(--color-down)' : 'var(--color-t4)' }}
                />
                <span className={`text-[12px] ${running ? 'text-t1' : 'text-t4'}`}>{s.description}</span>
                {info && info.signals_today > 0 && (
                  <span className="text-[11px] text-t3">
                    {info.signals_today} 信号
                  </span>
                )}
              </div>
              <div className="text-t3 text-[11px] truncate" style={{ marginLeft: 14 }}>
                {s.name} {info ? `· ${info.total_codes} 只` : ''}
              </div>
            </div>
            <Switch
              size="small"
              checked={running}
              onChange={(checked) => handleToggle(s.name, checked)}
              loading={startMut.isPending || stopMut.isPending}
            />
          </div>
        );
      })}
    </Panel>
  );
}
