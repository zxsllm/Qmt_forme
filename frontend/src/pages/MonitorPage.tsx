import { useState, useEffect, useRef, useMemo } from 'react';
import { Tag, Empty, Badge, Tooltip, notification } from 'antd';
import {
  WarningOutlined, ThunderboltOutlined, RiseOutlined,
  ClockCircleOutlined, QuestionCircleOutlined, PlayCircleOutlined,
  PauseCircleOutlined, CheckCircleOutlined, AimOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  api, type MonitorSnapshot, type MonitorAnomalyEvent, type MonitorSectorRow,
  type LargecapAlertEvent, type MonitorStatGroup, type MonitorLargecapStats,
} from '../services/api';

// ═══════════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════════

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

type PageMode = 'live' | 'replay' | 'empty';

function resolveMode(data: MonitorSnapshot | undefined, isLoading: boolean): PageMode {
  if (!data || isLoading) return 'empty';
  if (data.live_ready) return 'live';
  if (data.anomaly_count > 0 || data.largecap_alert_count > 0 || data.history_len > 0) return 'replay';
  return 'empty';
}

const LEVEL_COLOR: Record<string, string> = {
  high: '#ef4444', medium: '#ffbf75', low: '#556677',
};
const LEVEL_LABEL: Record<string, string> = {
  high: '高', medium: '中', low: '低',
};
const PATTERN_LABEL: Record<string, string> = {
  weight_pull: '权重拉升', theme_burst: '主题脉冲', risk_off: '风险回撤',
  broad_risk_on: '情绪扩散', weight_drag: '权重拖累', mixed: '混合',
};

function fmtAge(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}秒前`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}分钟前`;
  return `${(seconds / 3600).toFixed(1)}小时前`;
}

// Local-calendar-day YYYY-MM-DD (avoid UTC truncation edge cases around midnight).
function localDateKey(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

// Whole-day difference between two YYYY-MM-DD strings, counted on the local
// calendar (ignores clock time). Positive when *a* is later than *b*.
function diffLocalDays(a: string, b: string): number {
  const [ay, am, ad] = a.split('-').map(Number);
  const [by, bm, bd] = b.split('-').map(Number);
  if (!ay || !am || !ad || !by || !bm || !bd) return NaN;
  const da = new Date(ay, am - 1, ad).getTime();
  const db = new Date(by, bm - 1, bd).getTime();
  return Math.round((da - db) / (24 * 3600 * 1000));
}

// ═══════════════════════════════════════════════════════════════
// StatusBadge — header 三态指示器
// ═══════════════════════════════════════════════════════════════

function StatusBadge({ mode, data }: { mode: PageMode; data: MonitorSnapshot | undefined }) {
  if (mode === 'live') {
    const anomalyCount = data?.anomaly_count ?? 0;
    return (
      <Badge
        status={anomalyCount > 0 ? 'error' : 'processing'}
        text={
          <span style={{ color: anomalyCount > 0 ? '#f87171' : '#22c55e', fontSize: 12 }}>
            {anomalyCount > 0 ? `${anomalyCount} 条异动` : '盘面平静'}
          </span>
        }
      />
    );
  }
  if (mode === 'replay') {
    return (
      <Badge
        status="warning"
        text={<span style={{ color: '#ffbf75', fontSize: 12 }}>回放</span>}
      />
    );
  }
  return (
    <Badge
      status="default"
      text={<span style={{ color: '#556677', fontSize: 12 }}>无数据</span>}
    />
  );
}

// ═══════════════════════════════════════════════════════════════
// IndexCards
// ═══════════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════════
// AnomalyFeed — enriched with P1 fields
// ═══════════════════════════════════════════════════════════════

function AnomalyFeed({ anomalies, sortByScore }: { anomalies: MonitorAnomalyEvent[]; sortByScore?: boolean }) {
  const sorted = useMemo(() => {
    if (!sortByScore) return anomalies;
    return [...anomalies].sort((a, b) => (b.event_score ?? 0) - (a.event_score ?? 0));
  }, [anomalies, sortByScore]);

  if (sorted.length === 0) {
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
      {sorted.map((ev, i) => {
        const isUp = ev.delta_pct > 0;
        const levelColor = LEVEL_COLOR[ev.level] ?? '#556677';
        const borderColor = ev.level === 'high'
          ? `rgba(239,68,68,0.35)`
          : isUp ? 'rgba(239,68,68,0.20)' : 'rgba(34,197,94,0.20)';
        const bgColor = ev.level === 'high'
          ? `rgba(239,68,68,0.06)`
          : isUp ? 'rgba(239,68,68,0.03)' : 'rgba(34,197,94,0.03)';
        const hasHits = ev.hit_count > 0;

        return (
          <div key={`${ev.ts}-${i}`} style={{
            padding: '10px 14px', borderRadius: 12,
            background: bgColor, border: `1px solid ${borderColor}`,
            borderLeft: `3px solid ${levelColor}`,
          }}>
            {/* Row 1: header */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <ThunderboltOutlined style={{ color: isUp ? '#ef4444' : '#22c55e', fontSize: 14 }} />
              <span style={{ color: '#e6f1fa', fontWeight: 600, fontSize: 13 }}>
                {ev.index_name}
              </span>
              <Tag color={isUp ? 'red' : 'green'} style={{ margin: 0, fontSize: 11 }}>
                {fmtPct(ev.delta_pct)} / {ev.window}
              </Tag>
              {/* Pattern badge */}
              <Tag style={{
                margin: 0, fontSize: 10, border: `1px solid ${levelColor}33`,
                background: `${levelColor}18`, color: levelColor,
              }}>
                {PATTERN_LABEL[ev.pattern] ?? ev.pattern}
              </Tag>
              {/* Score pill */}
              <span style={{
                fontSize: 10, fontWeight: 700, color: levelColor,
                background: `${levelColor}15`, borderRadius: 999,
                padding: '1px 6px', marginLeft: 2,
              }}>
                {ev.event_score}分
              </span>
              <Tooltip title={`检测时刻 ${ev.detected_at ?? ev.time} · 比较分钟 ${ev.trigger_minute ?? ev.time.slice(0, 5)}`}>
                <span style={{ color: '#556677', fontSize: 10, marginLeft: 'auto', cursor: 'help' }}>
                  {ev.detected_at ?? ev.time}
                </span>
              </Tooltip>
            </div>

            {/* Row 2: summary + action_hint */}
            <div style={{ fontSize: 12, color: '#93a9bc', marginBottom: 4, lineHeight: 1.5 }}>
              {ev.summary}
            </div>
            <div style={{
              fontSize: 11, color: levelColor, fontWeight: 500,
              padding: '3px 8px', borderRadius: 8,
              background: `${levelColor}0a`, display: 'inline-block', marginBottom: 6,
            }}>
              {ev.action_hint}
            </div>

            {/* Row 3: hits */}
            {hasHits && (
              <div style={{ display: 'flex', gap: 8, marginBottom: 6, fontSize: 11 }}>
                {ev.watchlist_hits.length > 0 && (
                  <span style={{ color: '#6bc7ff' }}>
                    <AimOutlined style={{ marginRight: 3 }} />
                    观察池 {ev.watchlist_hits.length} 只
                    <Tooltip title={ev.watchlist_hits.join(', ')}>
                      <QuestionCircleOutlined style={{ marginLeft: 3, fontSize: 10, cursor: 'pointer' }} />
                    </Tooltip>
                  </span>
                )}
                {ev.position_hits.length > 0 && (
                  <span style={{ color: '#ffbf75' }}>
                    <ExclamationCircleOutlined style={{ marginRight: 3 }} />
                    持仓 {ev.position_hits.length} 只
                    <Tooltip title={ev.position_hits.join(', ')}>
                      <QuestionCircleOutlined style={{ marginLeft: 3, fontSize: 10, cursor: 'pointer' }} />
                    </Tooltip>
                  </span>
                )}
              </div>
            )}

            {/* Row 4: sectors */}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {ev.top_sectors.slice(0, 6).map((s, j) => (
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

// ═══════════════════════════════════════════════════════════════
// SectorHeatmap
// ═══════════════════════════════════════════════════════════════

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

// ═══════════════════════════════════════════════════════════════
// LargecapAlertFeed — enhanced with P1-5 fields
// ═══════════════════════════════════════════════════════════════

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
            {a.in_watchlist && (
              <Tag style={{ margin: 0, fontSize: 10, color: '#6bc7ff', border: '1px solid rgba(107,199,255,0.3)', background: 'rgba(107,199,255,0.08)' }}>
                <AimOutlined /> 观察池
              </Tag>
            )}
            {a.in_position && (
              <Tag style={{ margin: 0, fontSize: 10, color: '#ffbf75', border: '1px solid rgba(255,191,117,0.3)', background: 'rgba(255,191,117,0.08)' }}>
                <ExclamationCircleOutlined /> 持仓
              </Tag>
            )}
            <Tooltip title={`检测时刻 ${a.detected_at ?? a.time} · 比较分钟 ${a.trigger_minute ?? a.time.slice(0, 5)} · 同一轮快照批量扫描，可能多只同秒触发`}>
              <span style={{ color: '#556677', fontSize: 10, marginLeft: 'auto', cursor: 'help' }}>
                {a.detected_at ?? a.time}
                <span style={{ color: '#444', marginLeft: 4 }}>({a.trigger_minute ?? a.time.slice(0, 5)})</span>
              </span>
            </Tooltip>
          </div>
          <div style={{ display: 'flex', gap: 16, fontSize: 11, flexWrap: 'wrap' }}>
            <Tooltip title="触发价 = rt_k 快照触发时刻价格，非分钟线收盘价">
              <span style={{ color: '#93a9bc', cursor: 'help' }}>
                触发价 <span style={{ color: '#e6f1fa', fontWeight: 600 }}>{a.price_now.toFixed(2)}</span>
              </span>
            </Tooltip>
            <Tooltip title="昨日同 HH:MM 分钟线价格（非昨收）">
              <span style={{ color: '#556677', cursor: 'help' }}>
                昨同分时 {a.price_yesterday.toFixed(2)}
              </span>
            </Tooltip>
            <Tooltip title="昨同比量 = 今日截至触发时累计成交量 / 昨日同分钟累计成交量（非标准量比）">
              <span style={{ color: '#93a9bc', cursor: 'help' }}>
                昨同比量 <span style={{
                  color: a.vol_ratio >= 2 ? '#ef4444' : a.vol_ratio >= 1.5 ? '#f97316' : '#ffbf75',
                  fontWeight: 600,
                }}>{a.vol_ratio.toFixed(1)}x</span>
              </span>
            </Tooltip>
            <span style={{ color: '#556677' }}>
              流通 {a.circ_mv_yi.toFixed(0)}亿
            </span>
            {a.sector && (
              <span style={{ color: a.sector_strong ? '#22c55e' : '#556677' }}>
                {a.sector}{a.sector_strong ? ' (板块同步走强)' : ''}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// ReplayPanel — 非交易时段回放态
// ═══════════════════════════════════════════════════════════════

function ReplayPanel({ data }: { data: MonitorSnapshot }) {
  const [showAll, setShowAll] = useState(false);
  const eventDate = data.event_date ?? '';
  const displayDate = eventDate ? eventDate.replace(/-/g, '').replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3') : '';
  const anomalyList = showAll ? data.anomalies : data.anomalies.slice(0, 5);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Summary bar */}
      <div style={{
        padding: '14px 18px', borderRadius: 14,
        background: 'linear-gradient(135deg, rgba(16,34,49,0.6), rgba(10,22,33,0.8))',
        border: '1px solid rgba(148,186,215,0.10)',
        display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap',
      }}>
        <PlayCircleOutlined style={{ color: '#ffbf75', fontSize: 18 }} />
        <div>
          <div style={{ color: '#e6f1fa', fontSize: 13, fontWeight: 600 }}>
            回放模式 · 非交易时段
          </div>
          <div style={{ color: '#556677', fontSize: 11, marginTop: 2 }}>
            展示{displayDate ? ` ${displayDate} ` : '今日'}已触发的异动和快照，
            开盘后自动切换为实时监控
          </div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 20, flexWrap: 'wrap' }}>
          <MiniStat label="异动" value={`${data.anomaly_count}`} color={data.anomaly_count > 0 ? '#f87171' : '#22c55e'} />
          <MiniStat label="大盘股预警" value={`${data.largecap_alert_count}`} color={data.largecap_alert_count > 0 ? '#ffbf75' : '#556677'} />
          <MiniStat label="最后快照" value={data.last_tick_time ?? '无'} color="#6bc7ff" />
          {data.snapshot_age_s != null && (
            <MiniStat label="快照年龄" value={fmtAge(data.snapshot_age_s)} color="#556677" />
          )}
        </div>
      </div>

      {data.indices.length > 0 && (
        <>
          <SectionTitle icon={<PauseCircleOutlined style={{ color: '#6bc7ff' }} />} title="收盘快照" subtitle="最后一次 tick 的指数状态" />
          <IndexCards data={data} />
        </>
      )}

      {data.anomaly_count > 0 && (
        <>
          <SectionTitle
            icon={<WarningOutlined style={{ color: '#f59e0b' }} />}
            title="今日异动回放"
            subtitle={`共 ${data.anomaly_count} 条 · 重要优先`}
          />
          <AnomalyFeed anomalies={anomalyList} sortByScore />
          {data.anomalies.length > 5 && (
            <div
              style={{ fontSize: 11, color: '#6bc7ff', cursor: 'pointer', userSelect: 'none', textAlign: 'center' }}
              onClick={() => setShowAll(!showAll)}
            >
              {showAll ? `▲ 收起` : `▼ 展开全部 ${data.anomalies.length} 条`}
            </div>
          )}
        </>
      )}

      {data.largecap_alert_count > 0 && (
        <>
          <SectionTitle
            icon={<RiseOutlined style={{ color: '#ffbf75' }} />}
            title="大盘股量价齐升"
            subtitle={`${data.largecap_alert_count} 只触发`}
          />
          <LargecapAlertFeed alerts={data.largecap_alerts} />
        </>
      )}

      {data.sectors.length > 0 && (
        <>
          <SectionTitle icon={<span style={{ color: '#b48cff' }}>◆</span>} title="板块收盘快照" subtitle="最后 tick 的行业涨跌" />
          <SectorHeatmap sectors={data.sectors} />
        </>
      )}

      {data.anomaly_count === 0 && data.largecap_alert_count === 0 && data.indices.length === 0 && (
        <div style={{ padding: '30px 16px', textAlign: 'center' }}>
          <CheckCircleOutlined style={{ color: '#22c55e', fontSize: 28 }} />
          <div style={{ color: '#93a9bc', fontSize: 13, marginTop: 10 }}>今日盘面平静，未触发任何异动</div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// Shared tiny components
// ═══════════════════════════════════════════════════════════════

function MiniStat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 10, color: '#556677' }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 600, color }}>{value}</div>
    </div>
  );
}

function SectionTitle({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle?: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
      {icon}
      <span style={{ color: '#b8cfe0', fontSize: 13, fontWeight: 600 }}>{title}</span>
      {subtitle && <span style={{ color: '#556677', fontSize: 10 }}>{subtitle}</span>}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// P1-6: Toast notifications for high-value anomalies
// ═══════════════════════════════════════════════════════════════

function useAnomalyToast(data: MonitorSnapshot | undefined, mode: PageMode) {
  const seenRef = useRef<Set<string>>(new Set());
  const lastDateRef = useRef<string>('');

  useEffect(() => {
    if (mode !== 'live' || !data) return;
    // Clear seen set on day change to avoid stale dedup
    const eventDate = data.event_date ?? '';
    if (seenRef.current.size > 0 && lastDateRef.current && lastDateRef.current !== eventDate) {
      seenRef.current.clear();
    }
    lastDateRef.current = eventDate;
    for (const ev of data.anomalies) {
      // Use ts (epoch float) as key — globally unique, no cross-day collision
      const key = `${eventDate}:${ev.ts}:${ev.index_code}:${ev.window}`;
      if (seenRef.current.has(key)) continue;
      seenRef.current.add(key);

      // Only toast high-level or events hitting watchlist/positions
      if (ev.level !== 'high' && ev.hit_count === 0) continue;

      const isUp = ev.delta_pct > 0;
      notification.open({
        message: (
          <span style={{ color: '#e6f1fa', fontSize: 13 }}>
            <ThunderboltOutlined style={{ color: isUp ? '#ef4444' : '#22c55e', marginRight: 6 }} />
            {ev.summary}
          </span>
        ),
        description: (
          <span style={{ color: '#93a9bc', fontSize: 12 }}>
            {ev.action_hint}
            {ev.hit_count > 0 && ` · 命中 ${ev.hit_count} 只`}
          </span>
        ),
        placement: 'topRight',
        duration: 8,
        style: {
          background: 'linear-gradient(135deg, rgba(16,34,49,0.95), rgba(10,22,33,0.98))',
          border: `1px solid ${LEVEL_COLOR[ev.level] ?? '#556677'}40`,
          borderRadius: 14,
          backdropFilter: 'blur(10px)',
        },
      });
    }
  }, [data?.anomalies, mode]);
}

// ═══════════════════════════════════════════════════════════════
// P2-5: Timeline — historical events from DB
// ═══════════════════════════════════════════════════════════════

function EventTimeline() {
  const navigate = useNavigate();
  const [sortMode, setSortMode] = useState<'time' | 'score'>('score');
  const { data, isLoading } = useQuery({
    queryKey: ['monitor-events'],
    queryFn: () => api.monitorEvents({ limit: 50 }),
    staleTime: 60_000,
  });

  if (isLoading) return <div style={{ color: '#556677', fontSize: 12 }}>加载历史事件...</div>;
  if (!data?.events?.length) return <div style={{ color: '#556677', fontSize: 12 }}>暂无历史事件数据</div>;

  const events = [...data.events].sort((a, b) =>
    sortMode === 'score' ? (b.event_score - a.event_score) : (b.event_ts - a.event_ts),
  );

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ color: '#93a9bc', fontSize: 12 }}>{data.trade_date} · {data.total} 条</span>
        <Tooltip title={sortMode === 'score' ? '按综合评分排序：基于涨跌幅度、板块共振、观察池/持仓命中数加权计算' : '按触发时间倒序，最新事件在前'}>
          <span
            style={{ fontSize: 10, color: '#6bc7ff', cursor: 'pointer', userSelect: 'none' }}
            onClick={() => setSortMode(sortMode === 'score' ? 'time' : 'score')}
          >
            {sortMode === 'score' ? '重要优先' : '最新优先'}
          </span>
        </Tooltip>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {events.map((ev) => {
          const isUp = ev.delta_pct > 0;
          const lc = LEVEL_COLOR[ev.level] ?? '#556677';
          return (
            <div key={ev.id} style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '6px 12px',
              borderRadius: 10, background: 'rgba(16,34,49,0.5)',
              border: `1px solid ${lc}20`, borderLeft: `3px solid ${lc}`,
              fontSize: 12,
            }}>
              <span style={{ color: '#556677', width: 56, flexShrink: 0 }}>{ev.event_time}</span>
              <span style={{ color: '#e6f1fa', fontWeight: 600, width: 65, flexShrink: 0 }}>{ev.index_name}</span>
              <Tag color={isUp ? 'red' : 'green'} style={{ margin: 0, fontSize: 10 }}>
                {fmtPct(ev.delta_pct)}/{ev.window}
              </Tag>
              <Tag style={{ margin: 0, fontSize: 10, color: lc, border: `1px solid ${lc}33`, background: `${lc}15` }}>
                {PATTERN_LABEL[ev.pattern] ?? ev.pattern}
              </Tag>
              <Tooltip title="综合评分：基于幅度、板块共振、观察池/持仓命中数加权计算">
                <span style={{ color: lc, fontWeight: 700, fontSize: 11, flexShrink: 0 }}>
                  评分 {ev.event_score}
                </span>
              </Tooltip>
              {(() => {
                const parseCount = (j: string | null): number => {
                  if (!j) return 0;
                  try { const arr = JSON.parse(j); return Array.isArray(arr) ? arr.length : 0; }
                  catch { return 0; }
                };
                const w = parseCount(ev.watchlist_hits_json);
                const p = parseCount(ev.position_hits_json);
                return (
                  <>
                    {w > 0 && <span style={{ color: '#6bc7ff', fontSize: 10, flexShrink: 0 }}>观察池 {w}</span>}
                    {p > 0 && <span style={{ color: '#b48cff', fontSize: 10, flexShrink: 0 }}>持仓 {p}</span>}
                  </>
                );
              })()}
              {/* 收盘结果 — 三态 + 方向验证 */}
              {(() => {
                if (ev.ret_eod != null) {
                  const sameSign = (ev.delta_pct > 0 && ev.ret_eod > 0)
                    || (ev.delta_pct < 0 && ev.ret_eod < 0);
                  // flat (0) on either side → no verdict, fall back to neutral display
                  if (ev.delta_pct === 0 || ev.ret_eod === 0) {
                    return (
                      <span style={{ color: pctColor(ev.ret_eod), fontSize: 10, minWidth: 160, textAlign: 'right' }}>
                        收盘 {ev.ret_eod > 0 ? '+' : ''}{ev.ret_eod.toFixed(2)}%
                      </span>
                    );
                  }
                  if (sameSign) {
                    return (
                      <Tooltip title="异动方向与收盘方向一致 → 验证成功">
                        <span style={{ color: '#ff6f91', fontSize: 10, minWidth: 160, textAlign: 'right', fontWeight: 600 }}>
                          验证成功 · 收盘 {ev.ret_eod > 0 ? '+' : ''}{ev.ret_eod.toFixed(2)}%
                        </span>
                      </Tooltip>
                    );
                  }
                  return (
                    <Tooltip title="异动方向与收盘方向相反 → 验证失败">
                      <span style={{ color: '#22c55e', fontSize: 10, minWidth: 160, textAlign: 'right', fontWeight: 600 }}>
                        验证失败 · 反向 +{Math.abs(ev.ret_eod).toFixed(2)}%
                      </span>
                    </Tooltip>
                  );
                }
                const now = new Date();
                const today = localDateKey(now);
                const isToday = ev.event_date === today;
                const nowMin = now.getHours() * 60 + now.getMinutes();
                const closed = !isToday || nowMin >= 15 * 60;
                const dayGap = diffLocalDays(today, ev.event_date);
                const olderThanOneDay = !isNaN(dayGap) && dayGap >= 2;
                let label: string;
                let tip: string;
                if (!closed) { label = '盘中'; tip = '当日收盘后回填'; }
                else if (olderThanOneDay) { label = '无结果'; tip = '回填已完成但未得到有效收盘结果（可能缺指数收盘或触发价为 0）'; }
                else { label = '待回填'; tip = '收盘后等待 backfill 补齐；查询时会自动兜底一次'; }
                return (
                  <Tooltip title={tip}>
                    <span style={{ color: '#556677', fontSize: 10, minWidth: 160, textAlign: 'right' }}>
                      收盘结果 {label}
                    </span>
                  </Tooltip>
                );
              })()}
              {/* P2-7: navigation */}
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                <Tooltip title="跳转决策中枢">
                  <span
                    style={{ color: '#6bc7ff', cursor: 'pointer', fontSize: 10 }}
                    onClick={() => navigate('/command')}
                  >去决策中枢 →</span>
                </Tooltip>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// LargecapTimeline — 大盘股异动时间线
// ═══════════════════════════════════════════════════════════════

function LargecapTimeline() {
  const [sortMode, setSortMode] = useState<'time' | 'score'>('time');
  const { data, isLoading } = useQuery({
    queryKey: ['monitor-largecap'],
    queryFn: () => api.monitorLargecap({ limit: 50 }),
    staleTime: 60_000,
  });

  if (isLoading) return <div style={{ color: '#556677', fontSize: 12 }}>加载大盘股异动...</div>;
  if (!data?.alerts?.length) return <div style={{ color: '#556677', fontSize: 12 }}>暂无大盘股异动数据</div>;

  const alerts = [...data.alerts].sort((a, b) =>
    sortMode === 'score' ? (b.price_chg_pct ?? 0) - (a.price_chg_pct ?? 0) : b.event_ts - a.event_ts,
  );

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ color: '#93a9bc', fontSize: 12 }}>{data.trade_date} · {data.total} 只</span>
        <Tooltip title={sortMode === 'score' ? '按涨幅排序，涨幅最大的在前' : '按触发时间倒序，最新事件在前'}>
          <span
            style={{ fontSize: 10, color: '#6bc7ff', cursor: 'pointer', userSelect: 'none' }}
            onClick={() => setSortMode(sortMode === 'score' ? 'time' : 'score')}
          >
            {sortMode === 'score' ? '涨幅优先' : '最新优先'}
          </span>
        </Tooltip>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {alerts.map((a) => {
          const chg = a.price_chg_pct ?? 0;
          return (
            <div key={a.id} style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '6px 12px',
              borderRadius: 10, background: 'rgba(16,34,49,0.5)',
              border: '1px solid rgba(255,191,117,0.12)', borderLeft: '3px solid #ffbf75',
              fontSize: 12,
            }}>
              <span style={{ color: '#556677', width: 56, flexShrink: 0 }}>{a.event_time}</span>
              <span style={{ color: '#e6f1fa', fontWeight: 600, width: 72, flexShrink: 0 }}>{a.name}</span>
              <Tag color={chg >= 0 ? 'red' : 'green'} style={{ margin: 0, fontSize: 10 }}>
                {chg >= 0 ? '+' : ''}{chg.toFixed(2)}%
              </Tag>
              <Tooltip title="当前成交量 ÷ 昨日同一时刻累计成交量">
                <span style={{ color: '#93a9bc', fontSize: 10, cursor: 'help' }}>
                  昨同比量 {a.vol_ratio != null ? `${a.vol_ratio.toFixed(1)}x` : '-'}
                </span>
              </Tooltip>
              {a.sector && (
                <span style={{ color: '#b48cff', fontSize: 10 }}>{a.sector}</span>
              )}
              {(a.in_watchlist || a.in_position) && (
                <span style={{ display: 'inline-flex', gap: 4 }}>
                  {a.in_watchlist && (
                    <Tag color="blue" style={{ margin: 0, fontSize: 9, fontWeight: 600 }}>
                      <AimOutlined style={{ marginRight: 2 }} />观察池
                    </Tag>
                  )}
                  {a.in_position && (
                    <Tag color="orange" style={{ margin: 0, fontSize: 9, fontWeight: 600 }}>
                      <ExclamationCircleOutlined style={{ marginRight: 2 }} />持仓
                    </Tag>
                  )}
                </span>
              )}
              {/* 主行直接并排所有可用结果窗口；Tooltip 只做补充说明 */}
              {(a.ret_15m != null || a.ret_30m != null || a.ret_eod != null) && (() => {
                const items: { label: string; value: number }[] = [];
                if (a.ret_15m != null) items.push({ label: '15m', value: a.ret_15m });
                if (a.ret_30m != null) items.push({ label: '30m', value: a.ret_30m });
                if (a.ret_eod != null) items.push({ label: '收盘', value: a.ret_eod });
                return (
                  <Tooltip title="入场价 = 下一分钟开盘价；分别显示 15m / 30m / 收盘结果">
                    <div style={{
                      marginLeft: 'auto',
                      display: 'flex', gap: 10, justifyContent: 'flex-end',
                      minWidth: 220, fontSize: 10, cursor: 'help',
                    }}>
                      {items.map((it) => (
                        <span key={it.label} style={{ display: 'inline-flex', gap: 3, alignItems: 'baseline' }}>
                          <span style={{ color: '#556677' }}>{it.label}</span>
                          <span style={{ color: pctColor(it.value), fontWeight: 600 }}>
                            {it.value > 0 ? '+' : ''}{it.value.toFixed(2)}%
                          </span>
                        </span>
                      ))}
                    </div>
                  </Tooltip>
                );
              })()}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// P2-6: Stats Panel — verification dashboard
// ═══════════════════════════════════════════════════════════════

function StatsPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ['monitor-event-stats'],
    queryFn: () => api.monitorEventStats(1),
    staleTime: 300_000,
  });

  if (isLoading) return <div style={{ color: '#556677', fontSize: 12 }}>加载统计数据...</div>;
  if (!data) return <div style={{ color: '#556677', fontSize: 12 }}>暂无统计数据</div>;

  const evtCount = data.total_event_count ?? 0;
  const lc = data.largecap_stats as (MonitorLargecapStats & { count?: number }) | Record<string, never>;
  const lcCount = ('count' in lc) ? (lc.count ?? 0) : 0;
  const hasEnoughEvents = evtCount >= 10;

  // ── Use backend-provided summaries ──
  const idxSum = data.index_summary;
  const evtAvgEod = idxSum?.avg_ret_eod ?? null;
  const evtWr = idxSum?.win_rate ?? null;
  const lcWr30 = 'win_rate_30m' in lc ? lc.win_rate_30m : null;
  const lcAvg30 = 'avg_ret_30m' in lc ? lc.avg_ret_30m : null;
  const lcAvgEod = 'avg_ret_eod' in lc ? lc.avg_ret_eod : null;
  const lcWrEod = 'win_rate_eod' in lc ? lc.win_rate_eod : null;
  const indexAvail = data.window_availability?.index;

  function conclusionText(avgRet: number | null, winRate: number | null, count: number): string {
    if (count === 0) return '暂无数据';
    if (winRate == null || avgRet == null) return '收益数据尚未回填';
    if (winRate >= 55 && avgRet > 0) return '信号整体有效，方向一致率较高';
    if (winRate >= 45) return '信号表现中性，尚需更多样本验证';
    return '信号效果偏弱，需观察改进';
  }

  // ── Actionable advice — 像交易提示，不是报告结论 ──
  function indexAdvice(avgRet: number | null, winRate: number | null, count: number): string | undefined {
    if (count === 0) return undefined;
    if (count < 10) return '样本偏少，暂不作为独立判断依据';
    if (winRate == null || avgRet == null) return '收盘数据尚未回填，暂不下结论';
    if (winRate >= 55 && avgRet > 0) return '指数异动可继续观察，优先关注命中观察池/持仓的信号';
    if (winRate >= 45) return '指数异动方向性尚可，仅作背景参考';
    return '指数异动方向性较弱，暂不建议依赖';
  }

  function largecapAdvice(
    avg30: number | null, wr30: number | null,
    avgEod: number | null, wrEod: number | null, count: number
  ): string | undefined {
    if (count === 0) return undefined;
    if (count < 10) return '样本偏少，暂不作为独立判断依据';
    if (wr30 == null || avg30 == null) return '分钟级数据尚未回填，暂不下结论';
    const eodOk = (wrEod != null && wrEod >= 50) || (avgEod != null && avgEod > 0);
    if (wr30 >= 55 && avg30 > 0 && eodOk) return '若叠加板块共振/观察池命中，可优先复核';
    if (wr30 >= 55 && avg30 > 0) return '短线脉冲存在，但持续性不足，仅做盘中提示';
    if (wr30 >= 45) return '仅适合作为盘中异动提示，不宜直接追涨';
    return '裸异动方向性不足，谨慎追涨';
  }

  // ── 基于页面统计自动生成"保留 / 谨慎"两列 ──
  function buildRuleTips(d: NonNullable<typeof data>): { keep: string[]; caution: string[]; insufficient: boolean } {
    const keep: string[] = [];
    const caution: string[] = [];
    const evtOk = evtCount >= 10;
    const lcOk = lcCount >= 10;
    const insufficient = !evtOk && !lcOk;
    if (insufficient) return { keep, caution, insufficient };

    // 指数异动 — 整体
    if (evtOk && evtWr != null && evtWr >= 55 && (evtAvgEod ?? 0) > 0) {
      keep.push('指数异动作为趋势确认信号');
    } else if (evtOk && evtWr != null && evtWr < 45) {
      caution.push('指数异动直接作为入场依据');
    }

    // 命中观察池/持仓 vs 未命中
    const hit = d.hit_comparison?.hit;
    const noHit = d.hit_comparison?.no_hit;
    if (evtOk && hit && noHit && hit.count >= 3 && (hit.win_rate ?? 0) > (noHit.win_rate ?? 0) + 5) {
      keep.push('命中观察池/持仓的指数异动');
    }

    // 情绪扩散类
    const broad = d.by_pattern?.find(r => r.pattern === 'broad_risk_on');
    if (broad && broad.count >= 3 && (broad.win_rate ?? 0) >= 55) {
      keep.push('指数异动中的情绪扩散类');
    }

    // 高评分
    const highBand = d.by_score_band?.find(r => r.band?.startsWith('80') || r.band?.startsWith('≥'));
    if (highBand && highBand.count >= 3 && (highBand.win_rate ?? 0) >= 55) {
      keep.push('高评分指数异动');
    }

    // 大盘股 — 整体 & 板块共振
    if (lcOk) {
      if ((lcWr30 ?? 0) < 45) {
        caution.push('大盘股裸异动直接追涨');
      }
      if ((lcWr30 ?? 100) < 50 && (lcWrEod ?? 100) < 50) {
        caution.push('大盘股 30m 与收盘方向同时偏弱');
      }
      const ss = d.largecap_by_sector_strong?.sector_strong;
      const sw = d.largecap_by_sector_strong?.sector_weak;
      if (ss && sw && ss.count >= 3 && (ss.win_rate_30m ?? 0) > (sw.win_rate_30m ?? 0) + 5) {
        keep.push('大盘股叠加板块共振');
      }
    }

    return { keep, caution, insufficient };
  }

  const UNKNOWN_LABEL = '未分类';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ color: '#556677', fontSize: 11 }}>
        统计区间 (默认最近 1 天): {data.date_range[0]} ~ {data.date_range[1]}
      </div>

      {/* ═══ Layer 1: Today's Conclusion ═══ */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {/* Index anomaly summary — 主窗口=收盘结果；15m/30m 暂不可用 */}
        <SummaryCard
          title="指数异动验证"
          subtitle="触发后到当日收盘的方向验证"
          count={evtCount}
          avgRet={evtAvgEod}
          winRate={evtWr}
          retLabel="平均收盘结果"
          winRateLabel="胜率(收盘)"
          unavailable={
            (indexAvail?.ret_15m === 'unavailable' || indexAvail?.ret_30m === 'unavailable')
              ? '15m/30m 暂不可用（无分钟级指数数据源）'
              : undefined
          }
          conclusion={conclusionText(evtAvgEod, evtWr, evtCount)}
          advice={indexAdvice(evtAvgEod, evtWr, evtCount)}
        />
        {/* Largecap summary — 主窗口=30m；副窗口=收盘结果 */}
        <SummaryCard
          title="大盘股异动验证"
          subtitle="下一分钟开盘买入；30m 为主窗口，收盘结果为副窗口"
          count={lcCount}
          avgRet={lcAvg30}
          winRate={lcWr30}
          retLabel="平均30m结果"
          winRateLabel="胜率(30m)"
          extraMetrics={[
            { label: '平均收盘结果', value: lcAvgEod, kind: 'pct' },
            { label: '胜率(收盘)', value: lcWrEod, kind: 'rate' },
          ]}
          conclusion={conclusionText(lcAvg30, lcWr30, lcCount)}
          advice={largecapAdvice(lcAvg30, lcWr30, lcAvgEod, lcWrEod, lcCount)}
        />
      </div>

      {/* ═══ 当前规则建议（基于最近样本自动摘要） ═══ */}
      {(() => {
        const tips = buildRuleTips(data);
        const hasAny = tips.keep.length > 0 || tips.caution.length > 0 || tips.insufficient;
        if (!hasAny) return null;
        return (
          <div style={{
            padding: '10px 14px', borderRadius: 18,
            background: 'linear-gradient(180deg, rgba(23,42,59,0.55), rgba(8,17,25,0.7))',
            border: '1px solid rgba(148,186,215,0.12)',
            display: 'flex', flexDirection: 'column', gap: 8,
          }}>
            <div style={{ color: '#e6f1fa', fontSize: 12, fontWeight: 600 }}>
              当前规则建议
              <span style={{ color: '#556677', fontSize: 10, fontWeight: 400, marginLeft: 8 }}>
                基于最近样本自动摘要，不代表最终结论
              </span>
            </div>
            {tips.insufficient ? (
              <div style={{ color: '#ffbf75', fontSize: 11 }}>
                样本不足，当前仅供观察，不建议调整规则
              </div>
            ) : (
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                <div style={{ flex: '1 1 260px', minWidth: 240 }}>
                  <div style={{ color: '#7ce1f2', fontSize: 11, fontWeight: 600, marginBottom: 4 }}>
                    建议保留
                  </div>
                  {tips.keep.length === 0 ? (
                    <div style={{ color: '#556677', fontSize: 11 }}>暂无达标的强信号条件</div>
                  ) : (
                    <ul style={{ margin: 0, paddingLeft: 16, color: '#e6f1fa', fontSize: 11, lineHeight: 1.7 }}>
                      {tips.keep.map(t => <li key={t}>{t}</li>)}
                    </ul>
                  )}
                </div>
                <div style={{ flex: '1 1 260px', minWidth: 240 }}>
                  <div style={{ color: '#ffbf75', fontSize: 11, fontWeight: 600, marginBottom: 4 }}>
                    建议谨慎
                  </div>
                  {tips.caution.length === 0 ? (
                    <div style={{ color: '#556677', fontSize: 11 }}>暂无明显需要谨慎的条件</div>
                  ) : (
                    <ul style={{ margin: 0, paddingLeft: 16, color: '#e6f1fa', fontSize: 11, lineHeight: 1.7 }}>
                      {tips.caution.map(t => <li key={t}>{t}</li>)}
                    </ul>
                  )}
                </div>
              </div>
            )}
          </div>
        );
      })()}

      {/* ═══ Layer 2: Which conditions work better (index) ═══ */}
      <div style={{ color: '#93a9bc', fontSize: 13, fontWeight: 600, marginTop: 4 }}>
        指数异动 — 哪些条件更有效
        <span style={{ color: '#556677', fontSize: 10, fontWeight: 400, marginLeft: 8 }}>触发后到收盘的结果</span>
      </div>
      {!hasEnoughEvents ? (
        <div style={{ color: '#556677', fontSize: 12, padding: '8px 0' }}>
          样本不足 ({evtCount} 条，需 ≥10)，暂不做分组结论
        </div>
      ) : (<>
        <StatsTable
          title="哪种异动类型更有效"
          hint="看哪类信号收盘后更容易被市场确认"
          retHeader="平均收盘结果"
          rows={data.by_pattern.map(r => ({
            label: r.pattern === 'unknown' ? UNKNOWN_LABEL : (PATTERN_LABEL[r.pattern] ?? r.pattern), ...r,
            _retVal: r.avg_ret_eod,
          }))}
          minSample={3}
        />
        <StatsTable
          title="高等级信号是否更强"
          hint="看高等级提醒是否真的更值得信"
          retHeader="平均收盘结果"
          rows={data.by_level.map(r => ({
            label: r.level === 'unknown' ? UNKNOWN_LABEL : (LEVEL_LABEL[r.level] ?? r.level), ...r,
            _retVal: r.avg_ret_eod,
          }))}
          minSample={3}
        />
        <StatsTable
          title="高评分是否真的更有效"
          hint="看系统评分高的信号，后续是否更强"
          retHeader="平均收盘结果"
          rows={data.by_score_band.map(r => ({ label: r.band, ...r, _retVal: r.avg_ret_eod }))}
          minSample={3}
        />
        {Object.keys(data.hit_comparison).length > 0 && (
          <StatsTable
            title="命中观察池/持仓后是否更好"
            hint="看和自己交易对象有关的信号，是否更有价值"
            retHeader="平均收盘结果"
            rows={Object.entries(data.hit_comparison).map(([k, v]) => ({
              label: k === 'hit' ? '命中观察池/持仓' : '未命中', ...v, _retVal: v.avg_ret_eod,
            }))}
            minSample={0}
          />
        )}
      </>)}

      {/* ═══ Layer 3: Largecap section ═══ */}
      {lcCount > 0 && (<>
        <div style={{ color: '#ffbf75', fontSize: 13, fontWeight: 600, marginTop: 8, borderTop: '1px solid rgba(148,186,215,0.08)', paddingTop: 12 }}>
          大盘股异动 — 验证明细
          <span style={{ color: '#556677', fontSize: 10, fontWeight: 400, marginLeft: 8 }}>下一分钟开盘买入后 15/30 分钟的结果</span>
        </div>
        <div style={{ color: '#93a9bc', fontSize: 10, marginTop: -4 }}>
          主要用于发现异动对象，是否可交易仍需结合后续强弱判断；提示器 ≠ 直接买点
        </div>
        {/* Overall stats bar */}
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 12 }}>
          {(() => {
            const s = lc as MonitorLargecapStats;
            const fmt = (v: number | null) => v != null ? `${v > 0 ? '+' : ''}${v.toFixed(3)}%` : '-';
            const wrColor = (v: number | null) => v != null && v >= 50 ? '#22c55e' : '#f87171';
            return (<>
              <span style={{ color: '#93a9bc' }}>样本: <b style={{ color: '#e6f1fa' }}>{s.count}</b></span>
              <span style={{ color: '#93a9bc' }}>15m结果: <b style={{ color: pctColor(s.avg_ret_15m) }}>{fmt(s.avg_ret_15m)}</b></span>
              <span style={{ color: '#93a9bc' }}>30m结果: <b style={{ color: pctColor(s.avg_ret_30m) }}>{fmt(s.avg_ret_30m)}</b></span>
              <span style={{ color: '#93a9bc' }}>收盘结果: <b style={{ color: pctColor(s.avg_ret_eod) }}>{fmt(s.avg_ret_eod)}</b></span>
              <span style={{ color: '#93a9bc' }}>胜率(30m): <b style={{ color: wrColor(s.win_rate_30m) }}>{s.win_rate_30m != null ? `${s.win_rate_30m.toFixed(1)}%` : '-'}</b></span>
              <span style={{ color: '#93a9bc' }}>胜率(收盘): <b style={{ color: wrColor(s.win_rate_eod) }}>{s.win_rate_eod != null ? `${s.win_rate_eod.toFixed(1)}%` : '-'}</b></span>
              <span style={{ color: '#556677' }}>观察池命中 {s.watchlist_hits} · 持仓命中 {s.position_hits} · 板块共振 {s.sector_strong_count}</span>
            </>);
          })()}
        </div>
        {/* Hit vs non-hit */}
        {Object.keys(data.largecap_by_hit ?? {}).length > 0 && (
          <LargecapBreakdownTable
            title="命中观察池/持仓后是否更好"
            hint="看和自己交易对象有关的大盘股异动，是否更有价值"
            rows={Object.entries(data.largecap_by_hit).map(([k, v]) => ({
              label: k === 'hit' ? '命中观察池/持仓' : '未命中', ...v,
            }))}
          />
        )}
        {/* Sector strong vs weak */}
        {Object.keys(data.largecap_by_sector_strong ?? {}).length > 0 && (
          <LargecapBreakdownTable
            title="板块共振后是否更好"
            hint="看所在板块同步走强时，异动是否更容易持续"
            rows={Object.entries(data.largecap_by_sector_strong!).map(([k, v]) => ({
              label: k === 'sector_strong' ? '板块共振' : '非板块共振', ...v,
            }))}
          />
        )}
        {/* By time slot */}
        {(data.largecap_by_time_slot ?? []).length > 0 && (
          <LargecapBreakdownTable
            title="哪个时间段效果更好"
            hint="看盘中哪个时段的异动更值得关注"
            rows={data.largecap_by_time_slot.map(r => ({ label: r.slot, ...r }))}
          />
        )}
      </>)}
    </div>
  );
}

function SummaryCard({ title, subtitle, count, avgRet, winRate, retLabel,
  winRateLabel = '胜率', extraMetrics = [], unavailable, conclusion, advice }: {
  title: string; subtitle: string; count: number;
  avgRet: number | null; winRate: number | null;
  retLabel: string; winRateLabel?: string;
  extraMetrics?: { label: string; value: number | null; kind: 'pct' | 'rate' }[];
  unavailable?: string;
  conclusion: string;
  advice?: string;
}) {
  const wrColor = winRate != null && winRate >= 50 ? '#22c55e' : '#f87171';
  const fmtMetric = (v: number | null, kind: 'pct' | 'rate') =>
    v == null ? '-' : kind === 'rate' ? `${v.toFixed(1)}%` : `${v > 0 ? '+' : ''}${v.toFixed(3)}%`;
  return (
    <div style={{
      flex: '1 1 240px', padding: '12px 16px', borderRadius: 14,
      background: 'linear-gradient(180deg, rgba(23,42,59,0.7), rgba(8,17,25,0.8))',
      border: '1px solid rgba(148,186,215,0.12)',
    }}>
      <div style={{ color: '#e6f1fa', fontSize: 13, fontWeight: 600 }}>{title}</div>
      <div style={{ color: '#556677', fontSize: 10, marginBottom: 8 }}>{subtitle}</div>
      <div style={{ display: 'flex', gap: 16, fontSize: 12, flexWrap: 'wrap' }}>
        <span style={{ color: '#93a9bc' }}>样本 <b style={{ color: '#e6f1fa' }}>{count}</b></span>
        <span style={{ color: '#93a9bc' }}>{retLabel} <b style={{ color: pctColor(avgRet) }}>
          {fmtMetric(avgRet, 'pct')}
        </b></span>
        <span style={{ color: '#93a9bc' }}>{winRateLabel} <b style={{ color: wrColor }}>
          {fmtMetric(winRate, 'rate')}
        </b></span>
        {extraMetrics.map((m) => {
          const color = m.kind === 'rate'
            ? (m.value != null && m.value >= 50 ? '#22c55e' : '#f87171')
            : pctColor(m.value);
          return (
            <span key={m.label} style={{ color: '#93a9bc' }}>
              {m.label} <b style={{ color }}>{fmtMetric(m.value, m.kind)}</b>
            </span>
          );
        })}
      </div>
      {unavailable && (
        <Tooltip title="当前没有可靠分钟级结果，不在此卡片伪造数据">
          <div style={{ color: '#ffbf75', fontSize: 10, marginTop: 6, cursor: 'help' }}>
            {unavailable}
          </div>
        </Tooltip>
      )}
      <div style={{ color: '#93a9bc', fontSize: 11, marginTop: 6 }}>{conclusion}</div>
      {advice && (
        <div style={{
          marginTop: 6, padding: '6px 10px', borderRadius: 14,
          background: 'rgba(107,199,255,0.06)',
          border: '1px solid rgba(107,199,255,0.18)',
          color: '#7ce1f2', fontSize: 11, lineHeight: 1.5,
        }}>
          <span style={{ color: '#6bc7ff', fontWeight: 600, marginRight: 4 }}>建议</span>
          {advice}
        </div>
      )}
    </div>
  );
}

function StatsTable({ title, hint, retHeader, rows, minSample = 0 }: {
  title: string; hint?: string; retHeader: string;
  rows: (MonitorStatGroup & { label: string; _retVal?: number | null })[];
  minSample?: number;
}) {
  const filtered = minSample > 0 ? rows.filter(r => r.count >= minSample) : rows;
  if (!filtered.length) return null;
  const hdr: React.CSSProperties = { fontSize: 10, color: '#556677', textAlign: 'right', padding: '3px 6px' };
  const cell: React.CSSProperties = { fontSize: 11, textAlign: 'right', padding: '3px 6px' };

  return (
    <div>
      <div style={{ color: '#93a9bc', fontSize: 12, fontWeight: 600, marginBottom: hint ? 2 : 4 }}>{title}</div>
      {hint && <div style={{ color: '#556677', fontSize: 10, marginBottom: 4 }}>{hint}</div>}
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid rgba(148,186,215,0.1)' }}>
            <th style={{ ...hdr, textAlign: 'left' }}>类别</th>
            <th style={hdr}>样本</th>
            <th style={hdr}>{retHeader}</th>
            <th style={hdr}>
              <Tooltip title="信号方向和实际结果一致的比例">胜率</Tooltip>
            </th>
          </tr>
        </thead>
        <tbody>
          {filtered.map(r => {
            const ret = r._retVal ?? r.avg_ret_eod ?? r.avg_ret_15m ?? null;
            const lowSample = minSample > 0 && r.count < 5;
            const dimStyle = lowSample ? 0.55 : 1;
            return (
            <tr key={r.label} style={{ borderBottom: '1px solid rgba(148,186,215,0.05)' }}>
              <td style={{ ...cell, textAlign: 'left', color: '#e6f1fa' }}>
                {r.label}
                {lowSample && <span style={{ color: '#556677', fontSize: 9, marginLeft: 4 }}>仅供参考(样本&lt;5)</span>}
              </td>
              <td style={{ ...cell, color: '#93a9bc', opacity: dimStyle }}>{r.count}</td>
              <td style={{ ...cell, color: pctColor(ret), opacity: dimStyle }}>{ret != null ? `${ret > 0 ? '+' : ''}${ret.toFixed(3)}%` : '-'}</td>
              <td style={{ ...cell, color: r.win_rate != null && r.win_rate >= 50 ? '#22c55e' : '#f87171', opacity: dimStyle }}>
                {r.win_rate != null ? `${r.win_rate.toFixed(1)}%` : '-'}
              </td>
            </tr>);
          })}
        </tbody>
      </table>
    </div>
  );
}

function LargecapBreakdownTable({ title, hint, rows, minSample = 3 }: {
  title: string; hint?: string;
  rows: { label: string; count: number;
    avg_ret_15m: number | null; avg_ret_30m: number | null;
    avg_ret_eod?: number | null;
    win_rate_30m?: number | null; win_rate_eod?: number | null;
    win_rate: number | null;
  }[];
  minSample?: number;
}) {
  const filtered = minSample > 0 ? rows.filter(r => r.count >= minSample) : rows;
  if (!filtered.length) return null;
  const hdr: React.CSSProperties = { fontSize: 10, color: '#556677', textAlign: 'right', padding: '3px 6px' };
  const cell: React.CSSProperties = { fontSize: 11, textAlign: 'right', padding: '3px 6px' };
  const fmtPct3 = (v: number | null | undefined) => v != null ? `${v > 0 ? '+' : ''}${v.toFixed(3)}%` : '-';
  const wrC = (v: number | null | undefined) => v != null && v >= 50 ? '#22c55e' : '#f87171';
  return (
    <div>
      <div style={{ color: '#93a9bc', fontSize: 12, fontWeight: 600, marginBottom: hint ? 2 : 4 }}>{title}</div>
      {hint && <div style={{ color: '#556677', fontSize: 10, marginBottom: 4 }}>{hint}</div>}
      <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
        <colgroup>
          <col style={{ width: '22%' }} />
          <col style={{ width: '10%' }} />
          <col style={{ width: '14%' }} />
          <col style={{ width: '14%' }} />
          <col style={{ width: '14%' }} />
          <col style={{ width: '13%' }} />
          <col style={{ width: '13%' }} />
        </colgroup>
        <thead>
          <tr style={{ borderBottom: '1px solid rgba(148,186,215,0.1)' }}>
            <th style={{ ...hdr, textAlign: 'left' }}>类别</th>
            <th style={hdr}>样本</th>
            <th style={hdr}>15m结果</th>
            <th style={hdr}>30m结果</th>
            <th style={hdr}>收盘结果</th>
            <th style={hdr}>胜率(30m)</th>
            <th style={hdr}>胜率(收盘)</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map(r => {
            const lowSample = r.count < 5;
            const dimStyle = lowSample ? 0.55 : 1;
            const wr30 = r.win_rate_30m ?? r.win_rate;
            return (
            <tr key={r.label} style={{ borderBottom: '1px solid rgba(148,186,215,0.05)' }}>
              <td style={{ ...cell, textAlign: 'left', color: '#e6f1fa' }}>
                {r.label}
                {lowSample && <span style={{ color: '#556677', fontSize: 9, marginLeft: 4 }}>仅供参考(样本&lt;5)</span>}
              </td>
              <td style={{ ...cell, color: '#93a9bc', opacity: dimStyle }}>{r.count}</td>
              <td style={{ ...cell, color: pctColor(r.avg_ret_15m), opacity: dimStyle }}>{fmtPct3(r.avg_ret_15m)}</td>
              <td style={{ ...cell, color: pctColor(r.avg_ret_30m), opacity: dimStyle }}>{fmtPct3(r.avg_ret_30m)}</td>
              <td style={{ ...cell, color: pctColor(r.avg_ret_eod ?? null), opacity: dimStyle }}>{fmtPct3(r.avg_ret_eod)}</td>
              <td style={{ ...cell, color: wrC(wr30), opacity: dimStyle }}>
                {wr30 != null ? `${wr30.toFixed(1)}%` : '-'}
              </td>
              <td style={{ ...cell, color: wrC(r.win_rate_eod), opacity: dimStyle }}>
                {r.win_rate_eod != null ? `${r.win_rate_eod.toFixed(1)}%` : '-'}
              </td>
            </tr>);
          })}
        </tbody>
      </table>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// OutcomePanel — P3 后效分析
// ═══════════════════════════════════════════════════════════════

const PATH_LABEL_CN: Record<string, { label: string; hint: string; color: string }> = {
  follow_through: { label: '持续走强', hint: '可能是真买入', color: '#22c55e' },
  spike_fade:     { label: '冲高回落', hint: '可能是诱多/出货', color: '#f97316' },
  dip_recover:    { label: '先杀后拉', hint: '可能是洗盘', color: '#6bc7ff' },
  flat_noise:     { label: '无效噪声', hint: '信号无明显方向', color: '#556677' },
  trend_down:     { label: '持续走弱', hint: '弱信号/出货倾向', color: '#ef4444' },
};

function OutcomePanel() {
  const [days, setDays] = useState(1);
  const [sliceBy, setSliceBy] = useState('path_label');
  const [sliceSource, setSliceSource] = useState<'largecap' | 'events'>('largecap');

  const { data: baselineData } = useQuery({
    queryKey: ['outcome-baseline', days],
    queryFn: () => api.outcomeBaseline(days, 'all'),
    staleTime: 60000,
  });

  const { data: sliceData } = useQuery({
    queryKey: ['outcome-slices', sliceBy, days, sliceSource],
    queryFn: () => api.outcomeSlices(sliceBy, days, sliceSource),
    staleTime: 60000,
  });

  const { data: distData } = useQuery({
    queryKey: ['outcome-distribution', days],
    queryFn: () => api.outcomeDistribution(days),
    staleTime: 60000,
  });

  const lc = baselineData?.baseline?.largecap;
  const ev = baselineData?.baseline?.events;
  const slices = sliceData?.slices ?? [];
  const lcDist = distData?.largecap ?? {};

  const daysOptions = [1, 7, 14];
  const sliceOptions: { key: string; label: string; source: 'largecap' | 'events' }[] = [
    { key: 'path_label', label: '路径标签', source: 'largecap' },
    { key: 'sector_strong', label: '板块强弱', source: 'largecap' },
    { key: 'hit_type', label: '命中类型', source: 'largecap' },
    { key: 'time_slot', label: '时间段', source: 'largecap' },
    { key: 'sector', label: '行业', source: 'largecap' },
    { key: 'pattern', label: '异动模式', source: 'events' },
    { key: 'level', label: '级别', source: 'events' },
    { key: 'score_band', label: '评分区间', source: 'events' },
  ];

  const cellS: React.CSSProperties = { fontSize: 11, textAlign: 'right', padding: '3px 6px' };
  const hdrS: React.CSSProperties = { fontSize: 10, color: '#556677', textAlign: 'right', padding: '3px 6px' };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ color: '#93a9bc', fontSize: 12 }}>回看:</span>
        {daysOptions.map(d => (
          <span
            key={d}
            style={{
              fontSize: 11, cursor: 'pointer', userSelect: 'none',
              color: days === d ? '#6bc7ff' : '#556677',
              fontWeight: days === d ? 600 : 400,
              padding: '2px 8px', borderRadius: 999,
              background: days === d ? 'rgba(107,199,255,0.1)' : 'transparent',
            }}
            onClick={() => setDays(d)}
          >{d}天</span>
        ))}
        {baselineData?.date_range && (
          <span style={{ fontSize: 10, color: '#445566', marginLeft: 'auto' }}>
            {baselineData.date_range[0]} ~ {baselineData.date_range[1]}
          </span>
        )}
      </div>

      {/* Baseline Summary */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {lc && lc.sample_count > 0 && (
          <BaselineCard
            title="大盘股预警 — 下一分钟开盘买入基线"
            subtitle={`${lc.sample_count} 样本 · 入场价=触发后下一分钟 open · 30m 为主窗口，收盘结果为副窗口`}
            metrics={[
              { label: '平均15m结果', value: lc.avg_ret_15m, fmt: 'pct' },
              { label: '平均30m结果', value: lc.avg_ret_30m, fmt: 'pct' },
              { label: '中位30m结果', value: lc.median_ret_30m, fmt: 'pct' },
              { label: '胜率(30m)', value: lc.win_rate_30m, fmt: 'rate' },
              { label: '平均收盘结果', value: lc.avg_ret_eod, fmt: 'pct' },
              { label: '中位收盘结果', value: lc.median_ret_eod, fmt: 'pct' },
              { label: '胜率(收盘)', value: lc.win_rate_eod, fmt: 'rate' },
              { label: '盈亏比', value: lc.profit_loss_ratio, fmt: 'ratio' },
              { label: '最大回撤(30m)', value: lc.worst_drawdown_30m, fmt: 'pct' },
              { label: '均上冲(30m)', value: lc.avg_max_up_30m, fmt: 'pct' },
              { label: '均下探(30m)', value: lc.avg_max_down_30m, fmt: 'pct' },
            ]}
          />
        )}
        {ev && ev.sample_count > 0 && (
          <BaselineCard
            title="指数异动 — 信号后效 (非买入基线)"
            subtitle={`${ev.sample_count} 样本 · 触发快照价→当日收盘 · 不可直接交易 · 15m/30m 暂不可用`}
            metrics={[
              { label: '平均15m结果', value: null, fmt: 'pct', unavailable: true },
              { label: '平均30m结果', value: null, fmt: 'pct', unavailable: true },
              { label: '平均收盘结果', value: ev.avg_ret_eod, fmt: 'pct' },
              { label: '中位收盘结果', value: ev.median_ret_eod, fmt: 'pct' },
              { label: '胜率(收盘)', value: ev.win_rate_eod, fmt: 'rate' },
              { label: '盈亏比', value: ev.profit_loss_ratio, fmt: 'ratio' },
            ]}
          />
        )}
      </div>

      {/* Path Label Distribution */}
      {Object.keys(lcDist).length > 0 && (
        <div>
          <div style={{ color: '#93a9bc', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>路径标签分布 (大盘股)</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {Object.entries(lcDist).map(([label, count]) => {
              const total = Object.values(lcDist).reduce((a, b) => a + b, 0);
              const pct = total > 0 ? ((count / total) * 100).toFixed(1) : '0';
              const info = PATH_LABEL_CN[label] ?? { label, hint: '', color: '#556677' };
              return (
                <Tooltip key={label} title={info.hint}>
                  <div style={{
                    padding: '4px 10px', borderRadius: 14,
                    background: 'rgba(6,14,22,0.82)',
                    border: `1px solid ${info.color}33`,
                    display: 'flex', gap: 6, alignItems: 'center',
                  }}>
                    <span style={{ color: info.color, fontSize: 12, fontWeight: 600 }}>{info.label}</span>
                    <span style={{ color: '#93a9bc', fontSize: 11 }}>{count}</span>
                    <span style={{ color: '#556677', fontSize: 10 }}>({pct}%)</span>
                  </div>
                </Tooltip>
              );
            })}
          </div>
        </div>
      )}

      {/* Slice Controls */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <span style={{ color: '#93a9bc', fontSize: 12, fontWeight: 600 }}>分组切片:</span>
          {sliceOptions.map(opt => (
            <span
              key={opt.key}
              style={{
                fontSize: 11, cursor: 'pointer', userSelect: 'none',
                color: sliceBy === opt.key ? '#6bc7ff' : '#556677',
                fontWeight: sliceBy === opt.key ? 600 : 400,
                padding: '1px 6px', borderRadius: 999,
                background: sliceBy === opt.key ? 'rgba(107,199,255,0.08)' : 'transparent',
              }}
              onClick={() => { setSliceBy(opt.key); setSliceSource(opt.source); }}
            >{opt.label}</span>
          ))}
        </div>

        {/* Slice Table */}
        {slices.length > 0 && (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid rgba(148,186,215,0.1)' }}>
                <th style={{ ...hdrS, textAlign: 'left' }}>分组</th>
                <th style={hdrS}>样本</th>
                {sliceSource === 'largecap' ? (<>
                  <th style={hdrS}>
                    <Tooltip title="下一分钟开盘买入，持有 30 分钟后卖出的平均收益">30m结果</Tooltip>
                  </th>
                  <th style={hdrS}>
                    <Tooltip title="下一分钟开盘买入，持有到当日收盘的平均收益">收盘结果</Tooltip>
                  </th>
                  <th style={hdrS}>
                    <Tooltip title="30 分钟后盈利的比例">胜率(30m)</Tooltip>
                  </th>
                  <th style={hdrS}>
                    <Tooltip title="持有到收盘盈利的比例">胜率(收盘)</Tooltip>
                  </th>
                  <th style={hdrS}>
                    <Tooltip title="平均盈利 / 平均亏损（按 30m 口径）">盈亏比</Tooltip>
                  </th>
                  <th style={hdrS}>
                    <Tooltip title="30 分钟内平均最大上冲">均上冲</Tooltip>
                  </th>
                  <th style={hdrS}>
                    <Tooltip title="30 分钟内平均最大回撤">均下探</Tooltip>
                  </th>
                </>) : (<>
                  <th style={hdrS}>
                    <Tooltip title="事件触发价到当日收盘价的收益">收盘结果</Tooltip>
                  </th>
                  <th style={hdrS}>中位收盘结果</th>
                  <th style={hdrS}>胜率(收盘)</th>
                  <th style={hdrS}>盈亏比</th>
                  <th style={hdrS}>均分</th>
                </>)}
              </tr>
            </thead>
            <tbody>
              {slices.map(s => (
                <tr key={s.group} style={{ borderBottom: '1px solid rgba(148,186,215,0.05)' }}>
                  <td style={{ ...cellS, textAlign: 'left', color: '#e6f1fa' }}>
                    {sliceBy === 'path_label' && PATH_LABEL_CN[s.group]
                      ? <Tooltip title={PATH_LABEL_CN[s.group].hint}>
                          <span style={{ color: PATH_LABEL_CN[s.group].color }}>{PATH_LABEL_CN[s.group].label}</span>
                        </Tooltip>
                      : s.group}
                  </td>
                  <td style={{ ...cellS, color: '#93a9bc' }}>{s.count}</td>
                  {sliceSource === 'largecap' ? (<>
                    <td style={{ ...cellS, color: pctColor(s.avg_ret_30m ?? null) }}>
                      {s.avg_ret_30m != null ? `${s.avg_ret_30m > 0 ? '+' : ''}${s.avg_ret_30m.toFixed(3)}` : '-'}
                    </td>
                    <td style={{ ...cellS, color: pctColor(s.avg_ret_eod ?? null) }}>
                      {s.avg_ret_eod != null ? `${s.avg_ret_eod > 0 ? '+' : ''}${s.avg_ret_eod.toFixed(3)}` : '-'}
                    </td>
                    <td style={{ ...cellS, color: (s.win_rate_30m ?? 0) >= 50 ? '#22c55e' : '#f87171' }}>
                      {s.win_rate_30m != null ? `${s.win_rate_30m.toFixed(1)}%` : '-'}
                    </td>
                    <td style={{ ...cellS, color: (s.win_rate_eod ?? 0) >= 50 ? '#22c55e' : '#f87171' }}>
                      {s.win_rate_eod != null ? `${s.win_rate_eod.toFixed(1)}%` : '-'}
                    </td>
                    <td style={{ ...cellS, color: (s.profit_loss_ratio ?? 0) >= 1 ? '#22c55e' : '#f87171' }}>
                      {s.profit_loss_ratio != null ? s.profit_loss_ratio.toFixed(2) : '-'}
                    </td>
                    <td style={{ ...cellS, color: pctColor(s.avg_max_up_30m ?? null) }}>
                      {s.avg_max_up_30m != null ? `+${s.avg_max_up_30m.toFixed(3)}` : '-'}
                    </td>
                    <td style={{ ...cellS, color: pctColor(s.avg_max_down_30m ?? null) }}>
                      {s.avg_max_down_30m != null ? `${s.avg_max_down_30m.toFixed(3)}` : '-'}
                    </td>
                  </>) : (<>
                    <td style={{ ...cellS, color: pctColor(s.avg_ret_eod ?? null) }}>
                      {s.avg_ret_eod != null ? `${s.avg_ret_eod > 0 ? '+' : ''}${s.avg_ret_eod.toFixed(3)}` : '-'}
                    </td>
                    <td style={{ ...cellS, color: pctColor(s.median_ret_eod ?? null) }}>
                      {s.median_ret_eod != null ? `${s.median_ret_eod > 0 ? '+' : ''}${s.median_ret_eod.toFixed(3)}` : '-'}
                    </td>
                    <td style={{ ...cellS, color: (s.win_rate_eod ?? 0) >= 50 ? '#22c55e' : '#f87171' }}>
                      {s.win_rate_eod != null ? `${s.win_rate_eod.toFixed(1)}%` : '-'}
                    </td>
                    <td style={{ ...cellS, color: (s.profit_loss_ratio ?? 0) >= 1 ? '#22c55e' : '#f87171' }}>
                      {s.profit_loss_ratio != null ? s.profit_loss_ratio.toFixed(2) : '-'}
                    </td>
                    <td style={{ ...cellS, color: '#93a9bc' }}>
                      {s.avg_score != null ? s.avg_score.toFixed(1) : '-'}
                    </td>
                  </>)}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {slices.length === 0 && (
          <div style={{ color: '#556677', fontSize: 11, padding: 8 }}>
            暂无后效数据 · 需要收盘后自动回填
          </div>
        )}
      </div>
    </div>
  );
}

function BaselineCard({ title, subtitle, metrics }: {
  title: string;
  subtitle: string;
  metrics: { label: string; value: number | null | undefined; fmt: 'pct' | 'rate' | 'ratio'; unavailable?: boolean }[];
}) {
  return (
    <div style={{
      flex: '1 1 300px', padding: 12, borderRadius: 18,
      background: 'rgba(6,14,22,0.82)',
      border: '1px solid rgba(148,186,215,0.12)',
    }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: '#e6f1fa', marginBottom: 2 }}>{title}</div>
      <div style={{ fontSize: 10, color: '#556677', marginBottom: 8 }}>{subtitle}</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {metrics.map(m => {
          if (m.unavailable) {
            return (
              <div key={m.label} style={{ minWidth: 80 }}>
                <div style={{ fontSize: 10, color: '#556677' }}>{m.label}</div>
                <Tooltip title="当前没有可靠分钟级结果">
                  <div style={{ fontSize: 11, fontWeight: 600, color: '#ffbf75', cursor: 'help' }}>暂不可用</div>
                </Tooltip>
              </div>
            );
          }
          let display = '-';
          let color = '#93a9bc';
          if (m.value != null) {
            if (m.fmt === 'pct') {
              display = `${m.value > 0 ? '+' : ''}${m.value.toFixed(3)}%`;
              color = pctColor(m.value);
            } else if (m.fmt === 'rate') {
              display = `${m.value.toFixed(1)}%`;
              color = m.value >= 50 ? '#22c55e' : '#f87171';
            } else {
              display = m.value.toFixed(2);
              color = m.value >= 1 ? '#22c55e' : '#f87171';
            }
          }
          return (
            <div key={m.label} style={{ minWidth: 80 }}>
              <div style={{ fontSize: 10, color: '#556677' }}>{m.label}</div>
              <div style={{ fontSize: 12, fontWeight: 600, color }}>{display}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// MonitorPage — main page
// ═══════════════════════════════════════════════════════════════

export default function MonitorPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['monitor-snapshot'],
    queryFn: () => api.monitorSnapshot(),
    refetchInterval: (query) => {
      const d = query.state.data;
      if (d?.live_ready) return 3000;
      if (d?.trading_time) return 5000;
      return 15000;
    },
    staleTime: 2000,
  });

  const mode = resolveMode(data, isLoading);
  const [sortByScore, setSortByScore] = useState(false);
  const [bottomTab, setBottomTab] = useState<'none' | 'index-timeline' | 'largecap-timeline' | 'stats' | 'outcomes'>('none');

  // P1-6: toast for high-value anomalies
  useAnomalyToast(data, mode);

  // Count high-level anomalies for header badge
  const highCount = useMemo(
    () => data?.anomalies.filter(a => a.level === 'high' || a.hit_count > 0).length ?? 0,
    [data?.anomalies],
  );

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
        <StatusBadge mode={mode} data={data} />

        {/* High-value badge */}
        {mode === 'live' && highCount > 0 && (
          <Badge count={highCount} style={{ backgroundColor: '#ef4444' }} title={`${highCount} 条高价值异动`} />
        )}

        {/* Context info */}
        {data && (data.watchlist_count > 0 || data.position_count > 0) && (
          <span style={{ fontSize: 10, color: '#556677' }}>
            {data.watchlist_count > 0 && `观察${data.watchlist_count}`}
            {data.watchlist_count > 0 && data.position_count > 0 && ' / '}
            {data.position_count > 0 && `持仓${data.position_count}`}
          </span>
        )}

        {/* Right side: meta info */}
        <span style={{ color: '#556677', fontSize: 10, marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          {mode === 'live' && (
            <>
              <ClockCircleOutlined />
              <span>{data!.last_tick_time}</span>
              <span>·</span>
              <span>{data!.history_len} 采样点</span>
              <span>·</span>
              <span style={{ color: '#22c55e' }}>3秒刷新</span>
            </>
          )}
          {mode === 'replay' && data?.last_tick_time && (
            <>
              <ClockCircleOutlined />
              <span>最后 {data.last_tick_time}</span>
              {data.snapshot_age_s != null && <span>· {fmtAge(data.snapshot_age_s)}</span>}
            </>
          )}
          {mode === 'empty' && (
            <span>{isLoading ? '加载中...' : data?.trading_time ? '等待首个 tick...' : '非交易时段'}</span>
          )}
          <Tooltip title="页面状态由后端 live_ready 字段驱动。交易时段且快照 < 30 秒 = 实时；有历史事件但不实时 = 回放；其他 = 无数据。">
            <QuestionCircleOutlined style={{ cursor: 'pointer' }} />
          </Tooltip>
        </span>
      </div>

      {/* Experiment mode banner */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '6px 14px', borderRadius: 10,
        background: 'rgba(255,191,117,0.08)',
        border: '1px solid rgba(255,191,117,0.18)',
      }}>
        <ExclamationCircleOutlined style={{ color: '#ffbf75', fontSize: 12 }} />
        <span style={{ color: '#ffbf75', fontSize: 11 }}>
          实验模式 — 盘中监控尚处于策略验证阶段，默认展示最近 1 天数据，长周期统计仅供参考
        </span>
      </div>

      {/* ── Live Mode ── */}
      {mode === 'live' && data && (
        <>
          <IndexCards data={data} />

          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
              <WarningOutlined style={{ color: '#f59e0b' }} />
              <span style={{ color: '#b8cfe0', fontSize: 13, fontWeight: 600 }}>异动信号</span>
              <span style={{ color: '#556677', fontSize: 10 }}>含板块归因 · 联动观察池/持仓</span>
              <Tooltip title={sortByScore ? '按综合评分排序：基于涨跌幅度、板块共振、观察池/持仓命中数加权计算' : '按触发时间倒序，最新事件在前'}>
                <span
                  style={{ fontSize: 10, color: sortByScore ? '#6bc7ff' : '#556677', cursor: 'pointer', marginLeft: 8, userSelect: 'none' }}
                  onClick={() => setSortByScore(!sortByScore)}
                >
                  {sortByScore ? '重要优先' : '最新优先'}
                </span>
              </Tooltip>
            </div>
            <AnomalyFeed anomalies={data.anomalies} sortByScore={sortByScore} />
          </div>

          {data.largecap_alerts && data.largecap_alerts.length > 0 && (
            <div>
              <SectionTitle
                icon={<RiseOutlined style={{ color: '#ffbf75' }} />}
                title="大盘股量价齐升"
                subtitle={`vs昨同分时 · 涨>=1% · 比量>=1.2 · ${data.largecap_alert_count} 只`}
              />
              <LargecapAlertFeed alerts={data.largecap_alerts} />
            </div>
          )}

          <div>
            <SectionTitle
              icon={<span style={{ color: '#b48cff' }}>◆</span>}
              title="板块全景"
              subtitle="一级行业实时涨跌 · 含1分钟/5分钟变动"
            />
            <SectorHeatmap sectors={data.sectors} />
          </div>
        </>
      )}

      {/* ── Replay Mode ── */}
      {mode === 'replay' && data && (
        <ReplayPanel data={data} />
      )}

      {/* ── Empty Mode ── */}
      {mode === 'empty' && !isLoading && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <span style={{ color: '#556677' }}>
              {data?.trading_time
                ? '等待 rt_k 行情快照 · 首个 tick 到达后自动渲染'
                : '非交易时段 · 无历史异动 · 开盘后自动启动监控'}
            </span>
          }
        />
      )}

      {/* ── Bottom Tabs: Timeline + Stats ── */}
      <div style={{
        display: 'flex', gap: 12, marginTop: 8,
        borderTop: '1px solid rgba(148,186,215,0.08)', paddingTop: 10,
      }}>
        {([['index-timeline', '指数异动'], ['largecap-timeline', '大盘股异动'], ['stats', '验证统计'], ['outcomes', '后效分析']] as const).map(([tab, label]) => (
          <span
            key={tab}
            style={{
              fontSize: 12, cursor: 'pointer', userSelect: 'none',
              color: bottomTab === tab ? '#6bc7ff' : '#556677',
              fontWeight: bottomTab === tab ? 600 : 400,
              borderBottom: bottomTab === tab ? '2px solid #6bc7ff' : '2px solid transparent',
              paddingBottom: 4,
            }}
            onClick={() => setBottomTab(bottomTab === tab ? 'none' : tab)}
          >
            {label}
          </span>
        ))}
      </div>

      {bottomTab === 'index-timeline' && (
        <div style={{
          padding: 14, borderRadius: 14,
          background: 'linear-gradient(180deg, rgba(23,42,59,0.88), rgba(8,17,25,0.92))',
          border: '1px solid rgba(148,186,215,0.10)',
        }}>
          <EventTimeline />
        </div>
      )}

      {bottomTab === 'largecap-timeline' && (
        <div style={{
          padding: 14, borderRadius: 14,
          background: 'linear-gradient(180deg, rgba(23,42,59,0.88), rgba(8,17,25,0.92))',
          border: '1px solid rgba(148,186,215,0.10)',
        }}>
          <LargecapTimeline />
        </div>
      )}

      {bottomTab === 'stats' && (
        <div style={{
          padding: 14, borderRadius: 14,
          background: 'linear-gradient(180deg, rgba(23,42,59,0.88), rgba(8,17,25,0.92))',
          border: '1px solid rgba(148,186,215,0.10)',
        }}>
          <StatsPanel />
        </div>
      )}

      {bottomTab === 'outcomes' && (
        <div style={{
          padding: 14, borderRadius: 14,
          background: 'linear-gradient(180deg, rgba(23,42,59,0.88), rgba(8,17,25,0.92))',
          border: '1px solid rgba(148,186,215,0.10)',
        }}>
          <OutcomePanel />
        </div>
      )}
    </div>
  );
}
