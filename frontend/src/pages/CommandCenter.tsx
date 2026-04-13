import { useState, useMemo } from 'react';
import {
  Tag, Empty, DatePicker, Spin, Tooltip, Switch, Modal, Progress,
  Alert, Badge,
} from 'antd';
import {
  AimOutlined, FireOutlined, ThunderboltOutlined,
  SafetyCertificateOutlined,
  ExclamationCircleOutlined, CheckCircleOutlined,
  StopOutlined, CaretUpOutlined, CaretDownOutlined,
  MinusOutlined, HeatMapOutlined, WarningOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import dayjs, { type Dayjs } from 'dayjs';
import {
  api,
  type PlanDataResp,
  type ReviewDataResp,
  type SignalRankedItem,
} from '../services/api';
import Panel from '../components/Panel';

// ── Helpers ───────────────────────────────────────────────────
function fmtDate(d: Dayjs): string { return d.format('YYYYMMDD'); }

function pctColor(v: number | null | undefined): string {
  if (v == null) return '#93a9bc';
  return v > 0 ? '#ff6f91' : v < 0 ? '#22c55e' : '#93a9bc';
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '-';
  return `${v > 0 ? '+' : ''}${v.toFixed(2)}%`;
}

const INDEX_NAMES: Record<string, string> = {
  '000001.SH': '上证', '399001.SZ': '深成', '399006.SZ': '创业板',
  '000300.SH': '沪深300', '000905.SH': '中证500', '000688.SH': '科创50', '899050.BJ': '北证50',
};

const TEMP_COLOR: Record<string, string> = {
  '极热': '#ef4444', '偏热': '#f97316', '中性': '#6bc7ff', '偏冷': '#22c55e', '冰点': '#16a34a',
};

const TEMP_EMOJI: Record<string, string> = {
  '极热': 'H5', '偏热': 'H3', '中性': 'M', '偏冷': 'C3', '冰点': 'C5',
};

const DIRECTION_COLOR: Record<string, string> = {
  '看多': '#22c55e', '偏多': '#22c55e',
  '震荡': '#ffbf75',
  '偏空': '#ff6f91', '看空': '#ff6f91',
};

interface StrategyConclusion {
  direction?: string;
  confidence?: number;
  focus_sectors?: string[];
  risk_warnings?: string[];
}

/** Parse strategy_conclusion: may be JSON string, object, or plain text */
function parseStrategyConclusion(raw: string | null | undefined): StrategyConclusion | null {
  if (!raw) return null;
  if (typeof raw === 'object') return raw as unknown as StrategyConclusion;
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed === 'object' && parsed !== null) return parsed as StrategyConclusion;
  } catch { /* plain text fallback handled by caller */ }
  return null;
}

// ── Styles ────────────────────────────────────────────────────
const GLASS_CARD: React.CSSProperties = {
  background: 'linear-gradient(180deg, rgba(23,42,59,0.88), rgba(8,17,25,0.92))',
  border: '1px solid rgba(148,186,215,0.18)',
  boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.04), 0 18px 48px rgba(0,0,0,0.34)',
  backdropFilter: 'blur(10px)',
  borderRadius: 22,
};

const SUB_CARD: React.CSSProperties = {
  background: 'rgba(255,255,255,0.03)',
  border: '1px solid rgba(148,186,215,0.10)',
  borderRadius: 14,
  padding: '10px 14px',
};

// ═══════════════════════════════════════════════════════════════
// ActionBanner — "今日作战指令" hero banner
// ═══════════════════════════════════════════════════════════════
function ActionBanner({
  planData,
  reviewData,
  tradeDate,
  rtIndices,
}: {
  planData: PlanDataResp | undefined;
  reviewData: ReviewDataResp | undefined;
  tradeDate: string;
  rtIndices: Array<{ ts_code: string; close: number; pct_chg: number; name?: string }> | undefined;
}) {
  const tempData = reviewData?.temperature?.data;
  const temperature = tempData?.temperature
    ?? planData?.yesterday_review?.temperature
    ?? null;

  // 盘中优先用实时指数，否则 fallback 到 review 里的收盘数据
  const mainCodes = ['000001.SH', '399001.SZ', '399006.SZ'];
  const rtMain = rtIndices?.filter(i => mainCodes.includes(i.ts_code));
  const hasRt = rtMain && rtMain.length > 0;
  const fallbackIndices = reviewData?.index_summary ?? planData?.global_indices ?? [];
  const mainIndices = hasRt
    ? rtMain!
    : fallbackIndices.filter(i => mainCodes.includes(i.ts_code));

  // Direction priority: 今日早盘计划 > 昨日复盘结论
  const yp = planData?.yesterday_plan;
  const sc = useMemo(
    () => parseStrategyConclusion(planData?.yesterday_review?.strategy_conclusion),
    [planData?.yesterday_review?.strategy_conclusion],
  );
  const direction = yp?.predicted_direction ?? sc?.direction ?? null;
  const confidence = yp?.confidence_score ?? sc?.confidence ?? null;

  // Build action sentence
  const watchStocks = useMemo(() => {
    const pm = planData?.premarket;
    if (!pm) return [];
    const list = pm.watchlist ?? pm.dragon_stocks ?? [];
    return Array.isArray(list) ? list : [];
  }, [planData]);

  const actionText = useMemo(() => {
    const parts: string[] = [];
    if (direction) {
      const dirMap: Record<string, string> = {
        '看多': '积极做多', '偏多': '偏多操作，轻仓试探',
        '震荡': '震荡市，高抛低吸为主', '偏空': '偏空防守，控制仓位',
        '看空': '空仓观望，严格止损',
      };
      parts.push(dirMap[direction] ?? `方向: ${direction}`);
    }
    if (temperature) {
      const tempMap: Record<string, string> = {
        '极热': '市场极热，注意追高风险', '偏热': '情绪偏热，可参与强势股',
        '中性': '情绪中性，精选个股', '偏冷': '情绪偏冷，降低预期',
        '冰点': '冰点行情，空仓等待',
      };
      parts.push(tempMap[temperature] ?? '');
    }
    if (watchStocks.length > 0) {
      parts.push(`关注 ${watchStocks.length} 只标的`);
    }
    return parts.filter(Boolean).join(' | ');
  }, [direction, temperature, watchStocks.length]);

  const directionIcon = direction === '看多' || direction === '偏多'
    ? <CaretUpOutlined style={{ color: '#22c55e' }} />
    : direction === '看空' || direction === '偏空'
    ? <CaretDownOutlined style={{ color: '#ff6f91' }} />
    : <MinusOutlined style={{ color: '#ffbf75' }} />;

  return (
    <div style={{
      ...GLASS_CARD,
      borderRadius: 18,
      padding: '14px 24px',
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
    }}>
      {/* Row 1: Action directive */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        {directionIcon}
        <span style={{
          fontSize: 18,
          fontWeight: 700,
          color: DIRECTION_COLOR[direction ?? ''] ?? '#6bc7ff',
          letterSpacing: 0.5,
        }}>
          {direction ?? '待分析'}
        </span>
        {confidence != null && (
          <span style={{ fontSize: 12, color: '#556575' }}>
            置信 {confidence}%
          </span>
        )}
        <span style={{
          fontSize: 13,
          color: '#c8d6e0',
          marginLeft: 8,
          flex: 1,
        }}>
          {actionText || '数据加载中...'}
        </span>
        <span style={{ fontSize: 12, color: '#556575' }}>
          {tradeDate.replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3')}
          {planData?.resolved_trade_date && planData.resolved_trade_date !== tradeDate && (
            <span style={{ color: '#ffbf75', marginLeft: 6 }}>
              (数据日期: {planData.resolved_trade_date.replace(/(\d{4})(\d{2})(\d{2})/, '$2-$3')})
            </span>
          )}
        </span>
      </div>

      {/* Row 2: Temperature + indices + stats */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <FireOutlined style={{ color: TEMP_COLOR[temperature ?? ''] ?? '#6bc7ff', fontSize: 14 }} />
          <span style={{ fontSize: 13, fontWeight: 600, color: TEMP_COLOR[temperature ?? ''] ?? '#6bc7ff' }}>
            {temperature ?? '--'}
          </span>
        </div>

        {hasRt && (
          <span style={{ fontSize: 10, color: '#22c55e', border: '1px solid rgba(34,197,94,0.3)', borderRadius: 6, padding: '0 4px' }}>
            实时
          </span>
        )}
        {mainIndices.map(idx => (
          <div key={idx.ts_code} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ color: '#556575', fontSize: 11 }}>{INDEX_NAMES[idx.ts_code] ?? idx.ts_code}</span>
            <span style={{ color: '#e6f1fa', fontSize: 12, fontWeight: 600 }}>
              {idx.close?.toFixed(0) ?? '-'}
            </span>
            <span style={{ color: pctColor(idx.pct_chg), fontSize: 11, fontWeight: 600 }}>
              {fmtPct(idx.pct_chg)}
            </span>
          </div>
        ))}

        {tempData && (
          <>
            <Tooltip title="涨停/跌停/炸板">
              <span style={{ fontSize: 11, color: '#93a9bc' }}>
                <span style={{ color: '#ff6f91' }}>{tempData.limit_up}</span>
                /<span style={{ color: '#22c55e' }}>{tempData.limit_down}</span>
                /<span style={{ color: '#ffbf75' }}>{tempData.broken}</span>
              </span>
            </Tooltip>
            <Tooltip title="封板率">
              <span style={{ fontSize: 11, color: '#93a9bc' }}>
                封板 <span style={{ color: '#6bc7ff' }}>{(tempData.seal_rate ?? 0).toFixed(0)}%</span>
              </span>
            </Tooltip>
          </>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// WatchlistCards — visual stock cards with entry/exit levels
// ═══════════════════════════════════════════════════════════════
function WatchlistCards({ planData }: { planData: PlanDataResp | undefined; }) {
  const watchStocks = useMemo(() => {
    const pm = planData?.premarket;
    if (!pm) return [];
    const list = pm.watchlist ?? pm.dragon_stocks ?? [];
    return Array.isArray(list) ? list : [];
  }, [planData]);

  const priceAnchors = planData?.price_anchors ?? [];
  const anchorMap = useMemo(() => {
    const m = new Map<string, typeof priceAnchors[0]>();
    for (const a of priceAnchors) m.set(a.ts_code, a);
    return m;
  }, [priceAnchors]);

  if (!planData) return <EmptyCard text="早盘计划加载中..." />;

  return (
    <Panel
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <AimOutlined style={{ color: '#6bc7ff' }} />
          今日观察标的
          {watchStocks.length > 0 && (
            <Badge count={watchStocks.length} style={{ backgroundColor: 'rgba(107,199,255,0.2)', color: '#6bc7ff', fontSize: 10, boxShadow: 'none' }} />
          )}
        </span>
      }
      style={{ ...GLASS_CARD, flex: 1 }}
    >
      {watchStocks.length === 0 ? (
        <Empty description="暂无观察标的" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {watchStocks.map((stock, idx) => {
            const anchor = anchorMap.get(stock.ts_code);
            const support = anchor?.support_levels?.[0];
            const resistance = anchor?.resistance_levels?.[0];
            return (
              <div key={stock.ts_code} style={{
                ...SUB_CARD,
                padding: '12px 16px',
                borderLeft: `3px solid ${idx < 2 ? '#6bc7ff' : '#2f4354'}`,
                borderRadius: '4px 14px 14px 4px',
              }}>
                {/* Row 1: Name + Code + Tag */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: '#e6f1fa' }}>
                    {stock.name}
                  </span>
                  <span style={{ fontSize: 11, color: '#556575' }}>{stock.ts_code}</span>
                  {stock.tag && (
                    <Tag color="blue" style={{ fontSize: 10, borderRadius: 8, margin: 0 }}>{stock.tag}</Tag>
                  )}
                </div>

                {/* Row 2: Reason */}
                {stock.reason && (
                  <div style={{ fontSize: 12, color: '#93a9bc', marginBottom: 8, lineHeight: 1.5 }}>
                    {stock.reason}
                  </div>
                )}

                {/* Row 3: Price levels */}
                {anchor ? (
                  <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
                    {anchor.close != null && (
                      <div>
                        <div style={{ fontSize: 10, color: '#556575' }}>现价</div>
                        <div style={{ fontSize: 13, fontWeight: 600, color: '#e6f1fa' }}>{anchor.close.toFixed(2)}</div>
                      </div>
                    )}
                    {support != null ? (
                      <div>
                        <div style={{ fontSize: 10, color: '#556575' }}>支撑</div>
                        <div style={{ fontSize: 13, fontWeight: 600, color: '#22c55e' }}>{support.toFixed(2)}</div>
                      </div>
                    ) : anchor.period_low != null ? (
                      <div>
                        <div style={{ fontSize: 10, color: '#556575' }}>60日低</div>
                        <div style={{ fontSize: 13, fontWeight: 600, color: '#22c55e' }}>
                          {typeof anchor.period_low === 'object' ? (anchor.period_low as {price:number}).price.toFixed(2) : Number(anchor.period_low).toFixed(2)}
                        </div>
                      </div>
                    ) : null}
                    {resistance != null ? (
                      <div>
                        <div style={{ fontSize: 10, color: '#556575' }}>阻力</div>
                        <div style={{ fontSize: 13, fontWeight: 600, color: '#ff6f91' }}>{resistance.toFixed(2)}</div>
                      </div>
                    ) : anchor.period_high != null ? (
                      <div>
                        <div style={{ fontSize: 10, color: '#556575' }}>60日高</div>
                        <div style={{ fontSize: 13, fontWeight: 600, color: '#ff6f91' }}>
                          {typeof anchor.period_high === 'object' ? (anchor.period_high as {price:number}).price.toFixed(2) : Number(anchor.period_high).toFixed(2)}
                        </div>
                      </div>
                    ) : null}
                    {anchor.ma60 != null && (
                      <div>
                        <div style={{ fontSize: 10, color: '#556575' }}>{anchor.ma60 === anchor.close ? 'MA30' : 'MA60'}</div>
                        <div style={{ fontSize: 13, fontWeight: 600, color: '#b48cff' }}>{anchor.ma60.toFixed(2)}</div>
                      </div>
                    )}
                    {anchor.up_limit != null && (
                      <div>
                        <div style={{ fontSize: 10, color: '#556575' }}>涨停</div>
                        <div style={{ fontSize: 13, fontWeight: 600, color: '#ff6f91' }}>{anchor.up_limit.toFixed(2)}</div>
                      </div>
                    )}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      {/* Key Logic */}
      {planData.yesterday_plan?.key_logic && (
        <div style={{ ...SUB_CARD, marginTop: 12 }}>
          <div style={{ fontSize: 11, color: '#6bc7ff', fontWeight: 600, marginBottom: 4 }}>核心逻辑</div>
          <div style={{ fontSize: 12, color: '#93a9bc', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
            {planData.yesterday_plan.key_logic}
          </div>
        </div>
      )}
    </Panel>
  );
}

// ═══════════════════════════════════════════════════════════════
// ReviewCard — yesterday's review as visual highlights
// ═══════════════════════════════════════════════════════════════
function ReviewCard({ planData }: { planData: PlanDataResp | undefined; }) {
  const review = planData?.yesterday_review;
  const [expanded, setExpanded] = useState(false);

  const sc = useMemo(
    () => parseStrategyConclusion(review?.strategy_conclusion),
    [review?.strategy_conclusion],
  );

  if (!review) return <EmptyCard text="复盘数据加载中..." />;

  return (
    <Panel
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <CheckCircleOutlined style={{ color: '#b48cff' }} />
          昨日复盘
        </span>
      }
      style={{ ...GLASS_CARD, flex: 1 }}
    >
      {/* Key metrics - visual grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(80px, 1fr))', gap: 8, marginBottom: 12 }}>
        <MiniStat label="上证" value={fmtPct(review.sh_pct_chg)} color={pctColor(review.sh_pct_chg)} />
        <MiniStat label="温度" value={review.temperature ?? '-'} color={TEMP_COLOR[review.temperature ?? ''] ?? '#6bc7ff'} />
        <MiniStat label="成交额" value={review.total_amount ? `${(review.total_amount / 1e8).toFixed(0)}亿` : '-'} color="#6bc7ff" />
        <MiniStat label="涨/跌" value={`${review.up_count ?? '-'}/${review.down_count ?? '-'}`} color="#93a9bc" />
        <MiniStat label="涨停" value={`${review.limit_up_count ?? '-'}`} color="#ff6f91" />
        <MiniStat label="跌停" value={`${review.limit_down_count ?? '-'}`} color="#22c55e" />
      </div>

      {/* Strategy conclusion - compact */}
      {sc && (
        <div style={{ ...SUB_CARD, marginBottom: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            {sc.direction && (
              <span style={{
                fontSize: 14, fontWeight: 700,
                color: DIRECTION_COLOR[sc.direction] ?? '#6bc7ff',
              }}>
                {sc.direction}
              </span>
            )}
            {sc.confidence != null && (
              <span style={{ fontSize: 11, color: '#556575' }}>置信 {sc.confidence}%</span>
            )}
            {sc.focus_sectors?.map((s, i) => (
              <Tag key={i} color="blue" style={{ fontSize: 10, borderRadius: 8, margin: 0 }}>{s}</Tag>
            ))}
            {sc.risk_warnings?.map((w, i) => (
              <Tag key={i} color="orange" style={{ fontSize: 10, borderRadius: 8, margin: 0 }}>{w}</Tag>
            ))}
          </div>
        </div>
      )}

      {/* Market summary - collapsed by default */}
      {review.market_summary && (
        <div>
          <div
            style={{ fontSize: 11, color: '#6bc7ff', cursor: 'pointer', userSelect: 'none' }}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? '▼ 收起详细总结' : '▶ 展开详细总结'}
          </div>
          {expanded && (
            <div style={{ ...SUB_CARD, marginTop: 6, fontSize: 12, color: '#93a9bc', lineHeight: 1.6, whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto' }}>
              {review.market_summary}
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

// ═══════════════════════════════════════════════════════════════
// PlanVerificationCard — plan vs actual tracking
// ═══════════════════════════════════════════════════════════════
function PlanVerificationCard({ planData }: { planData: PlanDataResp | undefined; }) {
  const retrospect = planData?.retrospect;
  const yesterdayPlan = planData?.yesterday_plan;

  return (
    <Panel
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <SafetyCertificateOutlined style={{ color: '#7ce1f2' }} />
          计划执行验证
        </span>
      }
      style={{ ...GLASS_CARD, flex: 1 }}
    >
      {/* Accuracy tracking */}
      {retrospect?.stats && retrospect.stats.total_count > 0 ? (
        <div style={{ marginBottom: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
            <span style={{ fontSize: 11, color: '#93a9bc' }}>预测准确率</span>
            <span style={{ fontSize: 20, fontWeight: 700, color: '#6bc7ff' }}>
              {retrospect.stats.accuracy_rate != null ? `${retrospect.stats.accuracy_rate.toFixed(0)}%` : '-'}
            </span>
            <span style={{ fontSize: 11, color: '#556575' }}>
              ({retrospect.stats.correct_count}/{retrospect.stats.total_count})
            </span>
          </div>
          <Progress
            percent={retrospect.stats.accuracy_rate != null ? Math.round(retrospect.stats.accuracy_rate) : 0}
            strokeColor="#6bc7ff"
            trailColor="rgba(148,186,215,0.12)"
            showInfo={false}
            size="small"
          />
        </div>
      ) : (
        <div style={{ color: '#556575', fontSize: 12, marginBottom: 14 }}>暂无回溯数据</div>
      )}

      {/* Yesterday plan vs actual */}
      {yesterdayPlan && (
        <div style={{ ...SUB_CARD }}>
          <div style={{ fontSize: 11, color: '#93a9bc', marginBottom: 6 }}>昨日计划 vs 实际</div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <div>
              <span style={{ fontSize: 10, color: '#556575' }}>预测方向</span>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#6bc7ff' }}>
                {yesterdayPlan.predicted_direction ?? '-'}
              </div>
            </div>
            <div>
              <span style={{ fontSize: 10, color: '#556575' }}>实际结果</span>
              <div style={{
                fontSize: 13,
                fontWeight: 600,
                color: yesterdayPlan.actual_result === yesterdayPlan.predicted_direction ? '#22c55e' : '#ff6f91',
              }}>
                {yesterdayPlan.actual_result ?? '待验证'}
              </div>
            </div>
            <div>
              <span style={{ fontSize: 10, color: '#556575' }}>评分</span>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#ffbf75' }}>
                {yesterdayPlan.accuracy_score != null ? `${yesterdayPlan.accuracy_score.toFixed(0)}分` : '-'}
              </div>
            </div>
          </div>
          {yesterdayPlan.retrospect_note && (
            <div style={{ marginTop: 8, fontSize: 11, color: '#93a9bc', lineHeight: 1.5 }}>
              {yesterdayPlan.retrospect_note}
            </div>
          )}
        </div>
      )}

      {/* Recent retrospect history */}
      {retrospect?.recent_predictions && retrospect.recent_predictions.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 11, color: '#556575', marginBottom: 6 }}>近期验证记录</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {retrospect.recent_predictions.slice(0, 5).map(r => (
              <div key={r.trade_date} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11 }}>
                <span style={{ color: '#556575', width: 72 }}>
                  {r.trade_date.replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3')}
                </span>
                <span style={{ color: '#93a9bc', width: 40 }}>{r.predicted_direction}</span>
                <span style={{
                  color: r.actual_result === r.predicted_direction ? '#22c55e' : '#ff6f91',
                  width: 40,
                }}>
                  {r.actual_result}
                </span>
                {r.accuracy_score != null && (
                  <span style={{ color: '#ffbf75' }}>{r.accuracy_score.toFixed(0)}分</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}

// ═══════════════════════════════════════════════════════════════
// SignalRankCard — signal leaderboard with score bars
// ═══════════════════════════════════════════════════════════════
function SignalRankCard({ tradeDate }: { tradeDate: string }) {
  const [selectedSignal, setSelectedSignal] = useState<SignalRankedItem | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ['signal-ranked', tradeDate],
    queryFn: () => api.signalRanked(tradeDate, 20),
    staleTime: 120_000,
    retry: false,
    // graceful degradation if API not ready
    enabled: true,
  });

  return (
    <Panel
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <ThunderboltOutlined style={{ color: '#ffbf75' }} />
          信号排行榜
          {data?.scored_stocks != null && (
            <Badge count={data.scored_stocks.length} style={{ backgroundColor: 'rgba(107,199,255,0.2)', color: '#6bc7ff', fontSize: 10, boxShadow: 'none' }} />
          )}
        </span>
      }
      style={{ ...GLASS_CARD, flex: 1 }}
    >
      {isError ? (
        <div style={{ ...SUB_CARD, textAlign: 'center' }}>
          <WarningOutlined style={{ color: '#ffbf75', fontSize: 24, marginBottom: 8 }} />
          <div style={{ color: '#93a9bc', fontSize: 12 }}>评分引擎暂不可用</div>
          <div style={{ color: '#556575', fontSize: 11 }}>请稍后刷新重试</div>
        </div>
      ) : isLoading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
          <Spin />
        </div>
      ) : !data?.scored_stocks?.length ? (
        <Empty description="暂无信号" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {data.scored_stocks.slice(0, 20).map((item, idx) => (
            <div
              key={item.ts_code}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '6px 10px',
                borderRadius: 12,
                cursor: 'pointer',
                background: selectedSignal?.ts_code === item.ts_code
                  ? 'rgba(107,199,255,0.08)'
                  : 'transparent',
                transition: 'background 80ms ease',
              }}
              onClick={() => setSelectedSignal(selectedSignal?.ts_code === item.ts_code ? null : item)}
              onMouseEnter={e => {
                if (selectedSignal?.ts_code !== item.ts_code)
                  (e.currentTarget as HTMLDivElement).style.background = 'rgba(107,199,255,0.04)';
              }}
              onMouseLeave={e => {
                if (selectedSignal?.ts_code !== item.ts_code)
                  (e.currentTarget as HTMLDivElement).style.background = 'transparent';
              }}
            >
              <span style={{
                width: 20,
                fontSize: 11,
                fontWeight: 700,
                color: idx < 3 ? '#ffbf75' : '#556575',
                textAlign: 'center',
              }}>
                {idx + 1}
              </span>
              <span style={{ color: '#e6f1fa', fontSize: 12, width: 80, flexShrink: 0 }}>{item.name}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    height: 8,
                    borderRadius: 4,
                    background: 'rgba(148,186,215,0.08)',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      width: `${Math.min(item.total_score, 100)}%`,
                      height: '100%',
                      borderRadius: 4,
                      background: item.total_score >= 80
                        ? 'linear-gradient(90deg, #2481bd, #6bc7ff)'
                        : item.total_score >= 60
                        ? 'linear-gradient(90deg, #2481bd, #b48cff)'
                        : 'linear-gradient(90deg, #2f4354, #556575)',
                    }}
                  />
                </div>
              </div>
              <span style={{ color: '#6bc7ff', fontSize: 12, fontWeight: 600, width: 32, textAlign: 'right' }}>
                {item.total_score.toFixed(0)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Radar detail for selected signal */}
      {selectedSignal && (
        <div style={{ ...SUB_CARD, marginTop: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#e6f1fa', marginBottom: 8 }}>
            {selectedSignal.name} ({selectedSignal.ts_code}) - 四维评分
          </div>
          <RadarChart dimensions={{ sentiment: selectedSignal.sentiment_score, technical: selectedSignal.tech_score, fundamental: selectedSignal.fundamental_score, news: selectedSignal.news_score }} />
          {selectedSignal.signals.length > 0 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
              {selectedSignal.signals.map((s, i) => (
                <Tag key={i} color="blue" style={{ fontSize: 10, borderRadius: 8 }}>{s}</Tag>
              ))}
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

// ── Simple CSS radar chart (no chart library needed) ──────────
function RadarChart({ dimensions }: { dimensions: { sentiment: number; technical: number; fundamental: number; news: number } }) {
  const items = [
    { label: '情绪', value: dimensions.sentiment, color: '#ff6f91' },
    { label: '技术', value: dimensions.technical, color: '#6bc7ff' },
    { label: '基本面', value: dimensions.fundamental, color: '#b48cff' },
    { label: '舆情', value: dimensions.news, color: '#22c55e' },
  ];

  return (
    <div style={{ display: 'flex', gap: 12 }}>
      {items.map(item => (
        <div key={item.label} style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: 10, color: '#556575', marginBottom: 4 }}>{item.label}</div>
          <div style={{
            height: 6,
            borderRadius: 3,
            background: 'rgba(148,186,215,0.08)',
            overflow: 'hidden',
          }}>
            <div style={{
              width: `${Math.min(item.value, 100)}%`,
              height: '100%',
              borderRadius: 3,
              background: item.color,
              opacity: 0.8,
            }} />
          </div>
          <div style={{ fontSize: 11, color: item.color, fontWeight: 600, marginTop: 2 }}>
            {item.value.toFixed(0)}
          </div>
        </div>
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// SectorHeatCard — top/bottom sector ranking heatmap
// ═══════════════════════════════════════════════════════════════
function SectorHeatCard({ reviewData }: { reviewData: ReviewDataResp | undefined; }) {
  const ranking = reviewData?.sector_ranking;
  const topSectors = ranking?.top?.slice(0, 5) ?? [];
  const bottomSectors = ranking?.bottom?.slice(0, 5) ?? [];

  // Find max absolute pct_change for bar scaling
  const maxAbs = useMemo(() => {
    const all = [...topSectors, ...bottomSectors];
    if (all.length === 0) return 5;
    return Math.max(...all.map(s => Math.abs(s.pct_change ?? 0)), 1);
  }, [topSectors, bottomSectors]);

  return (
    <Panel
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <HeatMapOutlined style={{ color: '#ffbf75' }} />
          板块热度
          {ranking && (
            <span style={{ fontSize: 10, color: '#556575', fontWeight: 400 }}>
              共 {ranking.count} 板块
            </span>
          )}
        </span>
      }
      style={{ ...GLASS_CARD, flex: 1 }}
    >
      {!ranking ? (
        <Empty description="暂无板块数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Hot sectors */}
          <div>
            <div style={{ fontSize: 11, color: '#ff6f91', fontWeight: 600, marginBottom: 6 }}>
              HOT 领涨板块
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {topSectors.map((s, idx) => (
                <div key={s.ts_code || idx} style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '4px 8px', borderRadius: 10,
                }}>
                  <span style={{ width: 14, fontSize: 10, fontWeight: 700, color: idx < 3 ? '#ff6f91' : '#556575', textAlign: 'center' }}>
                    {idx + 1}
                  </span>
                  <span style={{ color: '#e6f1fa', fontSize: 12, width: 80, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.name}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ height: 6, borderRadius: 3, background: 'rgba(148,186,215,0.08)', overflow: 'hidden' }}>
                      <div style={{
                        width: `${Math.min(Math.abs(s.pct_change ?? 0) / maxAbs * 100, 100)}%`,
                        height: '100%', borderRadius: 3,
                        background: 'linear-gradient(90deg, #b54f61, #ff6f91)',
                      }} />
                    </div>
                  </div>
                  <span style={{ color: '#ff6f91', fontSize: 11, fontWeight: 600, width: 48, textAlign: 'right' }}>
                    {fmtPct(s.pct_change)}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Cold sectors */}
          <div>
            <div style={{ fontSize: 11, color: '#22c55e', fontWeight: 600, marginBottom: 6 }}>
              COLD 领跌板块
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {bottomSectors.map((s, idx) => (
                <div key={s.ts_code || idx} style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '4px 8px', borderRadius: 10,
                }}>
                  <span style={{ width: 14, fontSize: 10, fontWeight: 700, color: '#556575', textAlign: 'center' }}>
                    {idx + 1}
                  </span>
                  <span style={{ color: '#e6f1fa', fontSize: 12, width: 80, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.name}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ height: 6, borderRadius: 3, background: 'rgba(148,186,215,0.08)', overflow: 'hidden' }}>
                      <div style={{
                        width: `${Math.min(Math.abs(s.pct_change ?? 0) / maxAbs * 100, 100)}%`,
                        height: '100%', borderRadius: 3,
                        background: 'linear-gradient(90deg, #166534, #22c55e)',
                      }} />
                    </div>
                  </div>
                  <span style={{ color: '#22c55e', fontSize: 11, fontWeight: 600, width: 48, textAlign: 'right' }}>
                    {fmtPct(s.pct_change)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </Panel>
  );
}

// ═══════════════════════════════════════════════════════════════
// KillSwitchButton — compact kill switch for top bar
// ═══════════════════════════════════════════════════════════════
function KillSwitchButton() {
  const queryClient = useQueryClient();
  const [confirmKill, setConfirmKill] = useState(false);

  const { data: riskStatus } = useQuery({
    queryKey: ['risk-status'],
    queryFn: () => api.getRiskStatus(),
    refetchInterval: 15_000,
  });

  const killOn = useMutation({
    mutationFn: () => api.activateKillSwitch('Command Center manual'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['risk-status'] }),
  });

  const killOff = useMutation({
    mutationFn: () => api.deactivateKillSwitch(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['risk-status'] }),
  });

  const killActive = riskStatus?.kill_switch?.active ?? false;

  return (
    <>
      <Tooltip title={killActive ? `杀停已激活: ${riskStatus?.kill_switch?.reason ?? ''}` : '紧急停止开关'}>
        <Switch
          checked={killActive}
          onChange={(checked) => {
            if (checked) setConfirmKill(true);
            else killOff.mutate();
          }}
          checkedChildren={<StopOutlined />}
          unCheckedChildren={<StopOutlined />}
          style={{ background: killActive ? '#ef4444' : undefined }}
        />
      </Tooltip>
      <Modal
        title={
          <span style={{ color: '#ef4444' }}>
            <ExclamationCircleOutlined /> 确认激活紧急停止
          </span>
        }
        open={confirmKill}
        onOk={() => { killOn.mutate(); setConfirmKill(false); }}
        onCancel={() => setConfirmKill(false)}
        okText="激活"
        cancelText="取消"
        okButtonProps={{ danger: true }}
      >
        <p>激活后将立即停止所有交易操作。确认继续？</p>
      </Modal>
    </>
  );
}

// ── MiniStat — small label + value ────────────────────────────
function MiniStat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: '#556575' }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 600, color }}>{value}</div>
    </div>
  );
}

// ── EmptyCard placeholder ─────────────────────────────────────
function EmptyCard({ text }: { text: string }) {
  return (
    <Panel style={{ ...GLASS_CARD, flex: 1 }}>
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', padding: 40 }}>
        <Spin tip={text} />
      </div>
    </Panel>
  );
}

// ═══════════════════════════════════════════════════════════════
// TimeSeqHelp — 时序逻辑帮助弹窗
// ═══════════════════════════════════════════════════════════════
function TimeSeqHelp() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Tooltip title="时序逻辑说明">
        <QuestionCircleOutlined
          onClick={() => setOpen(true)}
          style={{
            color: '#556575',
            fontSize: 16,
            cursor: 'pointer',
            transition: 'color 80ms ease',
          }}
          onMouseEnter={e => (e.currentTarget.style.color = '#6bc7ff')}
          onMouseLeave={e => (e.currentTarget.style.color = '#556575')}
        />
      </Tooltip>
      <Modal
        title={<span style={{ color: '#e6f1fa' }}>决策中枢 · 数据说明</span>}
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        width={680}
      >
        <div style={{ color: '#c8d6e0', fontSize: 13, lineHeight: 1.8 }}>

          {/* Section 1 */}
          <div style={{ ...SUB_CARD, marginBottom: 14 }}>
            <div style={{ color: '#6bc7ff', fontWeight: 600, marginBottom: 6 }}>
              这个页面是做什么的？
            </div>
            <div style={{ color: '#93a9bc', fontSize: 12, lineHeight: 1.7 }}>
              决策中枢是你每天开盘前的<span style={{ color: '#e6f1fa' }}>作战准备台</span>。
              它把散落在复盘报告、早盘计划、技术分析、情绪数据里的信息
              <span style={{ color: '#e6f1fa' }}>汇总到一个屏幕</span>，
              帮你快速回答：<span style={{ color: '#ffbf75' }}>今天大盘什么方向？关注哪几只？在什么价位操作？有什么风险？</span>
            </div>
          </div>

          {/* Section 2 */}
          <div style={{ color: '#6bc7ff', fontWeight: 600, marginBottom: 8 }}>
            各面板的数据从哪来？
          </div>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', marginBottom: 16 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid rgba(148,186,215,0.18)' }}>
                <th style={{ textAlign: 'left', padding: '6px 8px', color: '#93a9bc', width: 100 }}>面板</th>
                <th style={{ textAlign: 'left', padding: '6px 8px', color: '#93a9bc' }}>数据来源</th>
                <th style={{ textAlign: 'left', padding: '6px 8px', color: '#93a9bc', width: 80 }}>更新频率</th>
              </tr>
            </thead>
            <tbody>
              {[
                ['顶栏方向', '每天 08:00 自动生成的早盘计划，AI 给出今日方向预测（偏多/震荡/偏空）和置信度', '每日一次'],
                ['温度/涨跌停', '收盘后从涨停池、跌停池、炸板池统计；盘中从实时行情快照估算', '盘中实时'],
                ['指数涨跌', '上证/深成/创业板的收盘数据', '每日一次'],
                ['观察标的', '早盘计划中 AI 推荐的 3-5 只重点关注股票', '每日一次'],
                ['支撑/阻力', '根据过去 60 个交易日的最高价和最低价计算的关键价格位。MA60 是 60 日均线', '每日一次'],
                ['昨日复盘', '前一个交易日收盘后 (16:00) 自动生成的复盘报告摘要，对应 reports/ 文件夹里的完整报告', '每日一次'],
                ['信号排行', '综合技术面(30%)、情绪面(25%)、基本面(25%)、消息面(20%) 四个维度对当日活跃股打分排名', '每日一次'],
                ['板块热度', '当日涨幅最大和跌幅最大的 5 个行业板块', '每日一次'],
                ['计划验证', '对比之前计划的预测方向 vs 实际涨跌结果，自动评分', '盘后自动'],
              ].map(([panel, source, freq]) => (
                <tr key={panel} style={{ borderBottom: '1px solid rgba(148,186,215,0.06)' }}>
                  <td style={{ padding: '6px 8px', color: '#e6f1fa', fontWeight: 500, verticalAlign: 'top' }}>{panel}</td>
                  <td style={{ padding: '6px 8px', color: '#93a9bc', lineHeight: 1.5 }}>{source}</td>
                  <td style={{ padding: '6px 8px', color: '#b48cff', verticalAlign: 'top' }}>{freq}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Section 3 */}
          <div style={{ color: '#6bc7ff', fontWeight: 600, marginBottom: 8 }}>
            不同时间打开看到的内容
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 14 }}>
            {[
              {
                title: '周末 / 节假日',
                color: '#93a9bc',
                lines: [
                  '所有数据自动显示上一个交易日的内容',
                  '顶栏会标注"数据日期: xx-xx"提醒你看的是哪天',
                  '例: 周日打开 → 看到的是周五的数据',
                ],
              },
              {
                title: '交易日早上 (开盘前)',
                color: '#6bc7ff',
                lines: [
                  '顶栏: 今日 AI 预测方向 + 温度（08:00 早盘计划生成后可看）',
                  '观察标的: 今天推荐关注的股票 + 支撑阻力价位',
                  '复盘: 昨天收盘后生成的复盘结论',
                  '信号排行: 暂无（今天还没交易，没有数据）',
                ],
              },
              {
                title: '交易日盘中 (09:30 ~ 15:00)',
                color: '#ffbf75',
                lines: [
                  '温度和涨跌停数据会实时更新',
                  '其他面板内容不变（计划是盘前定好的，不会盘中改）',
                  '需要盘中实时监控请去「盘中监控」页面',
                ],
              },
              {
                title: '交易日收盘后 (16:00 之后)',
                color: '#22c55e',
                lines: [
                  '复盘报告已自动生成，可以查看今天的总结',
                  '信号排行显示今日最终评分排名',
                  '计划验证自动完成（16:05），显示今日预测的准确度',
                ],
              },
            ].map(item => (
              <div key={item.title} style={{
                background: 'rgba(255,255,255,0.03)',
                borderRadius: 12,
                padding: '10px 14px',
                border: '1px solid rgba(148,186,215,0.08)',
              }}>
                <div style={{ color: item.color, fontSize: 13, fontWeight: 600, marginBottom: 4 }}>{item.title}</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {item.lines.map((line, i) => (
                    <div key={i} style={{ color: '#93a9bc', fontSize: 12, lineHeight: 1.5, paddingLeft: 8 }}>
                      {'· ' + line}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* Section 4 */}
          <div style={{ ...SUB_CARD }}>
            <div style={{ color: '#6bc7ff', fontWeight: 600, marginBottom: 4 }}>
              选择历史日期
            </div>
            <div style={{ color: '#93a9bc', fontSize: 12, lineHeight: 1.6 }}>
              用左边的日期选择器可以回看任意一天的决策数据。
              比如选 4 月 10 日，就能看到那天的早盘计划、信号排行、复盘结论。
              适合复盘过去某天的操作是否正确。
            </div>
          </div>
        </div>
      </Modal>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════
// CommandCenter — main page
// ═══════════════════════════════════════════════════════════════
export default function CommandCenter() {
  const [date, setDate] = useState<Dayjs>(dayjs());
  const tradeDate = fmtDate(date);

  const { data: planData, isLoading: planLoading } = useQuery({
    queryKey: ['plan-data', tradeDate],
    queryFn: () => api.planData(tradeDate),
    staleTime: 120_000,
    retry: 1,
  });

  const { data: reviewData } = useQuery({
    queryKey: ['review-data', tradeDate],
    queryFn: () => api.reviewData(tradeDate),
    staleTime: 120_000,
    retry: 1,
  });

  // 盘中实时指数（每 30 秒刷新，选择今天时启用）
  const isToday = tradeDate === fmtDate(dayjs());
  const { data: rtIndicesResp } = useQuery({
    queryKey: ['rt-indices'],
    queryFn: () => api.globalIndices(),
    enabled: isToday,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  return (
    <div
      style={{
        height: '100%',
        overflow: 'auto',
        padding: '16px 20px',
        display: 'flex',
        flexDirection: 'column',
        gap: 16,
      }}
    >
      {/* Top: Action Banner + DatePicker + Kill Switch */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'stretch' }}>
        <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
          <DatePicker
            value={date}
            onChange={v => v && setDate(v)}
            style={{ borderRadius: 14 }}
            allowClear={false}
          />
          <TimeSeqHelp />
          <KillSwitchButton />
        </div>
        <div style={{ flex: 1 }}>
          <ActionBanner planData={planData} reviewData={reviewData} tradeDate={tradeDate} rtIndices={isToday ? rtIndicesResp?.data : undefined} />
        </div>
      </div>

      {planLoading && (
        <Alert
          type="info"
          message="正在加载决策数据..."
          banner
          showIcon
          style={{ borderRadius: 14 }}
        />
      )}

      {/* Main content: 2-column layout */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '3fr 2fr',
          gap: 16,
          flex: 1,
          minHeight: 0,
        }}
      >
        {/* Left column (60%): Watchlist + Review */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minHeight: 0 }}>
          <WatchlistCards planData={planData} />
          <ReviewCard planData={planData} />
        </div>

        {/* Right column (40%): Signals + SectorHeat + PlanVerification */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minHeight: 0 }}>
          <SignalRankCard tradeDate={tradeDate} />
          <SectorHeatCard reviewData={reviewData} />
          <PlanVerificationCard planData={planData} />
        </div>
      </div>
    </div>
  );
}
