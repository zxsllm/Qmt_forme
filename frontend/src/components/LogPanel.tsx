import { mockLogs } from '../services/mockData';
import Panel from './Panel';

const levelColor: Record<string, string> = {
  info: 'var(--color-t3)',
  warn: 'var(--color-warn)',
  error: 'var(--color-up)',
};

export default function LogPanel({ className = '', secondary = false }: { className?: string; secondary?: boolean }) {
  return (
    <Panel title="系统日志" className={className} noPadding secondary={secondary}>
      <div className="font-mono" style={{ padding: '8px 16px' }}>
        {mockLogs.map((log, i) => (
          <div key={i} className="text-[11px] leading-relaxed" style={{ padding: '2px 0' }}>
            <span className="text-t4">{log.time}</span>
            {' '}
            <span style={{ color: levelColor[log.level] }}>[{log.level.toUpperCase()}]</span>
            {' '}
            <span style={{ color: log.level === 'info' ? 'var(--color-t2)' : levelColor[log.level] }}>
              {log.msg}
            </span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
