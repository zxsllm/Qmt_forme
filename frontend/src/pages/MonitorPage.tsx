import { Tag, Empty, Badge } from 'antd';
import { WarningOutlined, ThunderboltOutlined, RiseOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { api, type MonitorSnapshot, type MonitorAnomalyEvent, type MonitorSectorRow, type LargecapAlertEvent } from '../services/api';

function pctColor(v: number | null | undefined): string {
  if (v == null) return '#64748b';
  if (v > 0.3) return '#ef4444';
  if (v > 0) return '#f97316';
  if (v < -0.3) return '#22c55e';
  if (v < 0) return '#4ade80';
  return '#94a3b8';
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '-';
  return `${v > 0 ? '+' : ''}${v.toFixed(2)}%`;
}

function IndexCards({ data }: { data: MonitorSnapshot }) {
  return (
    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
      {data.indices.map((idx) => (
        <div key={idx.code} style={{
          flex: '1 1 160px', minWidth: 155, padding: '10px 14px',
          background: 'linear-gradient(135deg, rgba(16,34,49,0.7), rgba(10,22,33,0.9))',
          borderRadius: 14, border: '1px solid rgba(148,186,215,0.10)',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <span style={{ color: '#93a9bc', fontSize: 11 }}>{idx.name}</span>
            <span style={{ color: '#e6f1fa', fontWeight: 700, fontSize: 15 }}>{idx.price.toFixed(2)}</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {['1min', '5min', '15min'].map((w) => {
              const v = idx.windows[w];
              return (
                <div key={w} style={{ flex: 1, textAlign: 'center' }}>
                  <div style={{ color: '#556677', fontSize: 9 }}>{w}</div>
                  <div style={{ color: pctColor(v), fontWeight: 600, fontSize: 12 }}>{fmtPct(v)}</div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function AnomalyFeed({ anomalies }: { anomalies: MonitorAnomalyEvent[] }) {
  if (anomalies.length === 0) {
    return (
      <div style={{
        padding: '20px 16px', textAlign: 'center',
        background: 'rgba(34,197,94,0.04)', borderRadius: 14,
        border: '1px solid rgba(34,197,94,0.12)',
      }}>
        <div style={{ color: '#22c55e', fontSize: 13, fontWeight: 600 }}>盘面平静</div>
        <div style={{ color: '#556677', fontSize: 11, marginTop: 4 }}>
          暂无异动信号 · 阈值: 1分钟±0.3% / 5分钟±0.5% / 15分钟±1.0%
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {anomalies.map((ev, i) => {
        const isUp = ev.delta_pct > 0;
        const borderColor = isUp ? 'rgba(239,68,68,0.25)' : 'rgba(34,197,94,0.25)';
        const bgColor = isUp ? 'rgba(239,68,68,0.04)' : 'rgba(34,197,94,0.04)';
        return (
          <div key={`${ev.ts}-${i}`} style={{
            padding: '10px 14px', borderRadius: 12,
            background: bgColor, border: `1px solid ${borderColor}`,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <ThunderboltOutlined style={{ color: isUp ? '#ef4444' : '#22c55e', fontSize: 14 }} />
              <span style={{ color: '#e6f1fa', fontWeight: 600, fontSize: 13 }}>
                {ev.index_name}
              </span>
              <Tag color={isUp ? 'red' : 'green'} style={{ margin: 0, fontSize: 11 }}>
                {fmtPct(ev.delta_pct)} / {ev.window}
              </Tag>
              <span style={{ color: '#556677', fontSize: 10, marginLeft: 'auto' }}>{ev.time}</span>
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {ev.top_sectors.map((s, j) => (
                <Tag key={s.name} style={{
                  margin: 0, fontSize: 11, fontWeight: j < 3 ? 600 : 400,
                  background: j < 3 ? (isUp ? 'rgba(239,68,68,0.12)' : 'rgba(34,197,94,0.12)') : 'transparent',
                  border: j < 3 ? `1px solid ${isUp ? 'rgba(239,68,68,0.3)' : 'rgba(34,197,94,0.3)'}` : '1px solid rgba(148,186,215,0.12)',
                  color: j < 3 ? (isUp ? '#f87171' : '#4ade80') : '#93a9bc',
                }}>
                  {s.name} {s.delta > 0 ? '+' : ''}{s.delta.toFixed(2)}%
                </Tag>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function SectorHeatmap({ sectors }: { sectors: MonitorSectorRow[] }) {
  const sorted = [...sectors].sort((a, b) => b.pct_chg - a.pct_chg);
  const maxAbs = Math.max(...sorted.map(s => Math.abs(s.pct_chg)), 1);

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
      {sorted.map((s) => {
        const intensity = Math.min(Math.abs(s.pct_chg) / maxAbs, 1);
        const bg = s.pct_chg > 0
          ? `rgba(239,68,68,${0.08 + intensity * 0.35})`
          : s.pct_chg < 0
            ? `rgba(34,197,94,${0.08 + intensity * 0.35})`
            : 'rgba(148,186,215,0.06)';
        const color = s.pct_chg > 0 ? '#f87171' : s.pct_chg < 0 ? '#4ade80' : '#94a3b8';

        return (
          <div key={s.name} style={{
            padding: '5px 8px', borderRadius: 8, background: bg,
            border: '1px solid rgba(148,186,215,0.06)',
            minWidth: 90, textAlign: 'center',
          }}>
            <div style={{ color: '#c8d6e0', fontSize: 11, marginBottom: 2 }}>{s.name}</div>
            <div style={{ color, fontWeight: 600, fontSize: 12 }}>
              {s.pct_chg > 0 ? '+' : ''}{s.pct_chg.toFixed(2)}%
            </div>
            <div style={{ display: 'flex', justifyContent: 'center', gap: 6, marginTop: 2 }}>
              {['1min', '5min'].map(w => {
                const v = s.windows[w];
                return (
                  <span key={w} style={{ fontSize: 9, color: pctColor(v) }}>
                    {w}:{v != null ? `${v > 0 ? '+' : ''}${v.toFixed(2)}` : '-'}
                  </span>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function LargecapAlertFeed({ alerts }: { alerts: LargecapAlertEvent[] }) {
  if (alerts.length === 0) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {alerts.map((a, i) => (
        <div key={`${a.ts_code}-${i}`} style={{
          padding: '10px 14px', borderRadius: 12,
          background: 'rgba(255,191,117,0.04)',
          border: '1px solid rgba(255,191,117,0.20)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <RiseOutlined style={{ color: '#ffbf75', fontSize: 14 }} />
            <span style={{ color: '#e6f1fa', fontWeight: 600, fontSize: 13 }}>{a.name}</span>
            <span style={{ color: '#93a9bc', fontSize: 10 }}>{a.ts_code}</span>
            <Tag color="orange" style={{ margin: 0, fontSize: 11 }}>
              {a.price_chg_pct > 0 ? '+' : ''}{a.price_chg_pct.toFixed(2)}%
            </Tag>
            <span style={{ color: '#556677', fontSize: 10, marginLeft: 'auto' }}>{a.time}</span>
          </div>
          <div style={{ display: 'flex', gap: 16, fontSize: 11 }}>
            <span style={{ color: '#93a9bc' }}>
              现价 <span style={{ color: '#e6f1fa', fontWeight: 600 }}>{a.price_now.toFixed(2)}</span>
              <span style={{ color: '#556677' }}> / 昨同 {a.price_yesterday.toFixed(2)}</span>
            </span>
            <span style={{ color: '#93a9bc' }}>
              量比 <span style={{
                color: a.vol_ratio >= 2 ? '#ef4444' : a.vol_ratio >= 1.5 ? '#f97316' : '#ffbf75',
                fontWeight: 600,
              }}>{a.vol_ratio.toFixed(1)}x</span>
            </span>
            <span style={{ color: '#556677' }}>
              流通 {a.circ_mv_yi.toFixed(0)}亿
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function MonitorPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['monitor-snapshot'],
    queryFn: () => api.monitorSnapshot(),
    refetchInterval: 3000,
    staleTime: 2000,
  });

  const hasData = data && data.history_len > 0;

  return (
    <div style={{ padding: 18, height: '100%', display: 'flex', flexDirection: 'column', gap: 12, overflow: 'auto' }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '10px 16px',
        background: 'linear-gradient(135deg, rgba(16,34,49,0.6), rgba(10,22,33,0.8))',
        borderRadius: 14, border: '1px solid rgba(148,186,215,0.10)',
      }}>
        <span style={{ color: '#6bc7ff', fontWeight: 700, fontSize: 15 }}>盘中监控</span>
        {data && (
          <Badge
            status={data.anomaly_count > 0 ? 'error' : 'success'}
            text={
              <span style={{ color: data.anomaly_count > 0 ? '#f87171' : '#22c55e', fontSize: 12 }}>
                {data.anomaly_count > 0 ? `${data.anomaly_count} 条异动` : '盘面平静'}
              </span>
            }
          />
        )}
        <span style={{ color: '#556677', fontSize: 10, marginLeft: 'auto' }}>
          {hasData ? `${data.history_len} 个采样点 · 3秒刷新` : isLoading ? '加载中...' : '等待行情数据'}
        </span>
      </div>

      {!hasData && !isLoading && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <span style={{ color: '#556677' }}>
              等待 rt_k 行情快照 · 仅交易时段生效
            </span>
          }
        />
      )}

      {hasData && (
        <>
          {/* Index Cards */}
          <IndexCards data={data} />

          {/* Anomaly Feed */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              <WarningOutlined style={{ color: '#f59e0b' }} />
              <span style={{ color: '#b8cfe0', fontSize: 13, fontWeight: 600 }}>异动信号</span>
              <span style={{ color: '#556677', fontSize: 10 }}>
                最近1小时 · 含板块归因
              </span>
            </div>
            <AnomalyFeed anomalies={data.anomalies} />
          </div>

          {/* Largecap Volume-Price Surge */}
          {data.largecap_alerts && data.largecap_alerts.length > 0 && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                <RiseOutlined style={{ color: '#ffbf75' }} />
                <span style={{ color: '#b8cfe0', fontSize: 13, fontWeight: 600 }}>大盘股量价齐升</span>
                <span style={{ color: '#556677', fontSize: 10 }}>
                  流通市值&gt;1000亿 · 相对昨日同时刻 · 全天保持
                </span>
                <Tag color="orange" style={{ margin: 0, marginLeft: 4, fontSize: 10 }}>
                  {data.largecap_alert_count}
                </Tag>
              </div>
              <LargecapAlertFeed alerts={data.largecap_alerts} />
            </div>
          )}

          {/* Sector Heatmap */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              <span style={{ color: '#b8cfe0', fontSize: 13, fontWeight: 600 }}>板块全景</span>
              <span style={{ color: '#556677', fontSize: 10 }}>
                一级行业实时涨跌 · 含1分钟/5分钟变动
              </span>
            </div>
            <SectorHeatmap sectors={data.sectors} />
          </div>
        </>
      )}
    </div>
  );
}
