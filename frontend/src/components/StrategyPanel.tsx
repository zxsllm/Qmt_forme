import { Switch } from 'antd';
import { mockStrategies } from '../services/mockData';
import Panel from './Panel';

export default function StrategyPanel({ className = '', secondary = false }: { className?: string; secondary?: boolean }) {
  return (
    <Panel title="策略" className={className} noPadding secondary={secondary}>
      {mockStrategies.map((s) => (
        <div
          key={s.id}
          className="flex items-center justify-between border-b border-edge"
          style={{ padding: '8px 16px' }}
        >
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span
                className="inline-block rounded-full shrink-0"
                style={{ width: 6, height: 6, background: s.enabled ? 'var(--color-down)' : 'var(--color-t4)' }}
              />
              <span className={`text-[12px] ${s.enabled ? 'text-t1' : 'text-t4'}`}>{s.name}</span>
              {s.pnl_today !== 0 && (
                <span
                  className="text-[11px]"
                  style={{ color: s.pnl_today >= 0 ? 'var(--color-up)' : 'var(--color-down)' }}
                >
                  {s.pnl_today > 0 ? '+' : ''}{s.pnl_today}
                </span>
              )}
            </div>
            <div className="text-t3 text-[11px] truncate" style={{ marginLeft: 14 }}>{s.description}</div>
          </div>
          <Switch size="small" checked={s.enabled} />
        </div>
      ))}
    </Panel>
  );
}
