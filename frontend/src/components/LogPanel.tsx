import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import Panel from './Panel';

const actionColor: Record<string, string> = {
  ORDER_SUBMIT: 'var(--color-t2)',
  ORDER_FILL: 'var(--color-down)',
  ORDER_CANCEL: 'var(--color-t3)',
  RISK_BLOCK: 'var(--color-up)',
  KILL_SWITCH_ON: 'var(--color-up)',
  KILL_SWITCH_OFF: 'var(--color-down)',
  SETTLEMENT: 'var(--color-t2)',
  BACKTEST_FILTER: 'var(--color-t3)',
};

export default function LogPanel({ className = '', secondary = false }: { className?: string; secondary?: boolean }) {
  const { data } = useQuery({
    queryKey: ['audit-log'],
    queryFn: api.getAuditLog,
    refetchInterval: 3000,
  });

  const events = data?.data ?? [];

  return (
    <Panel title="系统日志" className={className} noPadding secondary={secondary}>
      <div className="font-mono" style={{ padding: '8px 16px' }}>
        {events.length === 0 && (
          <div className="text-t4 text-[11px]" style={{ padding: '4px 0' }}>暂无日志</div>
        )}
        {events.slice(-20).reverse().map((evt, i) => (
          <div key={i} className="text-[11px] leading-relaxed" style={{ padding: '2px 0' }}>
            <span className="text-t4">
              {evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString('zh-CN', { hour12: false }) : ''}
            </span>
            {' '}
            <span style={{ color: actionColor[evt.action] ?? 'var(--color-t3)' }}>
              [{evt.action}]
            </span>
            {' '}
            {evt.ts_code && <span className="text-t2">{evt.ts_code} </span>}
            <span className="text-t2">{evt.detail}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
