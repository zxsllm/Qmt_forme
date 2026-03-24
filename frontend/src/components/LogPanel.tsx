import type { CSSProperties } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';
import Panel from './Panel';

const actionColor: Record<string, string> = {
  ORDER_SUBMIT: '#93a9bc',
  ORDER_FILL: '#4ade80',
  ORDER_CANCEL: '#64748b',
  RISK_BLOCK: '#ff6f91',
  KILL_SWITCH_ON: '#ff6f91',
  KILL_SWITCH_OFF: '#4ade80',
  SETTLEMENT: '#93a9bc',
  BACKTEST_FILTER: '#64748b',
};

export default function LogPanel({ className = '', secondary = false, style }: { className?: string; secondary?: boolean; style?: CSSProperties }) {
  void secondary;
  const { data } = useQuery({
    queryKey: ['audit-log'],
    queryFn: api.getAuditLog,
    refetchInterval: 3000,
  });

  const events = data?.data ?? [];

  return (
    <Panel title="系统日志" className={className} noPadding style={style}>
      <div className="font-mono" style={{ padding: '10px 18px' }}>
        {events.length === 0 && (
          <div style={{ padding: '4px 0', fontSize: 11, color: '#334155' }}>暂无日志</div>
        )}
        {events.slice(-20).reverse().map((evt, i) => (
          <div key={i} style={{ fontSize: 11, lineHeight: 1.55, padding: '2px 0', color: '#d7e5f2' }}>
            <span style={{ color: '#334155' }}>
              {evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString('zh-CN', { hour12: false }) : ''}
            </span>
            {' '}
            <span style={{ color: actionColor[evt.action] ?? '#64748b' }}>
              [{evt.action}]
            </span>
            {' '}
            {evt.ts_code && <span style={{ color: '#93a9bc' }}>{evt.ts_code} </span>}
            <span style={{ color: '#93a9bc' }}>{evt.detail}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
