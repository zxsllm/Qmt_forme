const BASE = 'http://localhost:8000';

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(`${BASE}${url}`);
  if (!res.ok) throw new Error(`API ${res.status}: ${url}`);
  return res.json();
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `API ${res.status}`);
  }
  return res.json();
}

async function deleteJson<T>(url: string): Promise<T> {
  const res = await fetch(`${BASE}${url}`, { method: 'DELETE' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `API ${res.status}`);
  }
  return res.json();
}

export interface DailyBar {
  ts_code: string;
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  vol: number;
  amount: number;
  pct_chg: number | null;
  pe: number | null;
  pb: number | null;
  total_mv: number | null;
  turnover_rate: number | null;
}

export interface SnapshotRow {
  ts_code: string;
  name: string;
  industry: string;
  close: number;
  pct_chg: number;
  vol: number;
  amount: number;
  pe: number | null;
  pb: number | null;
  total_mv: number | null;
  turnover_rate: number | null;
}

export interface IndexBar {
  ts_code: string;
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  pct_chg: number;
  vol: number;
}

export interface SwClassify {
  index_code: string;
  industry_name: string;
  level: string;
  parent_code: string;
}

interface ApiList<T> {
  count: number;
  data: T[];
}

// ---------------------------------------------------------------------------
// Strategy runner / Audit / Feed types
// ---------------------------------------------------------------------------

export interface RunningStrategyInfo {
  name: string;
  description: string;
  params: Record<string, unknown>;
  codes: string[];
  total_codes: number;
  signals_today: number;
  total_signals: number;
  started_at: string;
}

export interface StrategyRunnerStatus {
  listening: boolean;
  strategies: RunningStrategyInfo[];
}

export interface AuditEvent {
  action: string;
  order_id: string | null;
  ts_code: string;
  detail: string;
  timestamp: string;
}

export interface FeedStatus {
  running: boolean;
  trading_time: boolean;
  watch_codes: number;
  codes: string[];
}

// ---------------------------------------------------------------------------
// Trading types (match backend Pydantic models)
// ---------------------------------------------------------------------------

export interface StockSearchResult {
  ts_code: string;
  name: string;
  industry: string;
  list_status: string;
}

export interface SimOrder {
  order_id: string;
  signal_id: string;
  ts_code: string;
  side: 'BUY' | 'SELL';
  order_type: 'MARKET' | 'LIMIT';
  price: number | null;
  qty: number;
  filled_qty: number;
  filled_price: number;
  status: string;
  fee: number;
  slippage: number;
  reject_reason: string;
  created_at: string;
  updated_at: string;
}

export interface SimPosition {
  ts_code: string;
  qty: number;
  avg_cost: number;
  market_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
}

export interface SimAccount {
  total_asset: number;
  cash: number;
  frozen: number;
  market_value: number;
  total_pnl: number;
  today_pnl: number;
  updated_at: string;
}

export interface RiskStatus {
  kill_switch: { active: boolean; reason: string; activated_at: string | null };
  realtime_halted: boolean;
  halt_reason: string;
  daily_buy_count: number;
}

export interface SubmitOrderBody {
  ts_code: string;
  side: 'BUY' | 'SELL';
  order_type?: 'MARKET' | 'LIMIT';
  price?: number;
  qty?: number;
  reason?: string;
}

// ---------------------------------------------------------------------------
// API object
// ---------------------------------------------------------------------------

export const api = {
  // Data (Phase 1)
  stockDaily: (code: string, start = '', end = '') =>
    fetchJson<ApiList<DailyBar>>(
      `/api/v1/stock/${code}/daily?start=${start}&end=${end}`,
    ),

  marketSnapshot: (date: string) =>
    fetchJson<ApiList<SnapshotRow>>(`/api/v1/market/snapshot/${date}`),

  indexDaily: (code: string, start = '', end = '') =>
    fetchJson<ApiList<IndexBar>>(
      `/api/v1/index/${code}/daily?start=${start}&end=${end}`,
    ),

  swClassify: (level = '') =>
    fetchJson<ApiList<SwClassify>>(`/api/v1/classify/sw?level=${level}`),

  // Stock search
  searchStocks: (q: string) =>
    fetchJson<ApiList<StockSearchResult>>(`/api/v1/stock/search?q=${encodeURIComponent(q)}`),

  // Trading (Phase 3)
  submitOrder: (body: SubmitOrderBody) =>
    postJson<SimOrder>('/api/v1/orders', body),

  cancelOrder: (orderId: string) =>
    deleteJson<SimOrder>(`/api/v1/orders/${orderId}`),

  listOrders: (status?: string) =>
    fetchJson<ApiList<SimOrder>>(
      `/api/v1/orders${status ? `?status=${status}` : ''}`,
    ),

  getPositions: () =>
    fetchJson<ApiList<SimPosition>>('/api/v1/positions'),

  getAccount: () =>
    fetchJson<SimAccount>('/api/v1/account'),

  getRiskStatus: () =>
    fetchJson<RiskStatus>('/api/v1/risk/status'),

  activateKillSwitch: (reason = 'manual') =>
    postJson('/api/v1/risk/kill-switch', { reason }),

  deactivateKillSwitch: () =>
    deleteJson('/api/v1/risk/kill-switch'),

  resetAccount: () =>
    postJson<{ status: string; message: string }>('/api/v1/account/reset', {}),

  // Strategy runner
  getRunningStrategies: () =>
    fetchJson<StrategyRunnerStatus>('/api/v1/strategy/running'),

  startStrategy: (body: { strategy_name: string; params?: Record<string, unknown>; codes?: string[] }) =>
    postJson<RunningStrategyInfo>('/api/v1/strategy/start', body),

  stopStrategy: (name: string) =>
    postJson<{ status: string; name: string }>(`/api/v1/strategy/${name}/stop`, {}),

  // Audit log
  getAuditLog: () =>
    fetchJson<ApiList<AuditEvent>>('/api/v1/observability/audit'),

  // Feed scheduler
  getFeedStatus: () =>
    fetchJson<FeedStatus>('/api/v1/feed/status'),

  // ── Backtest ─────────────────────────────────────────────

  listStrategies: () =>
    fetchJson<StrategyInfo[]>('/api/v1/backtest/strategies'),

  runBacktest: (body: RunBacktestRequest) =>
    postJson<BacktestRunResult>('/api/v1/backtest/run', body),

  listBacktestRuns: (limit = 20) =>
    fetchJson<BacktestRunSummary[]>(`/api/v1/backtest/list?limit=${limit}`),

  getBacktestResult: (runId: string) =>
    fetchJson<BacktestRunResult>(`/api/v1/backtest/result/${runId}`),

  // ── P2-Plus: Rankings / News / K-line ────────────────────
  marketRankings: (type: 'gain' | 'lose' | 'turnover' = 'gain', limit = 10) =>
    fetchJson<ApiList<RankingRow>>(`/api/v1/market/rankings?type=${type}&limit=${limit}`),

  sectorRankings: (limit = 10) =>
    fetchJson<ApiList<SectorRankRow>>(`/api/v1/sector/rankings?limit=${limit}`),

  moneyFlow: (limit = 10) =>
    fetchJson<ApiList<MoneyFlowRow>>(`/api/v1/market/moneyflow?limit=${limit}`),

  globalIndices: () =>
    fetchJson<ApiList<GlobalIndexRow>>('/api/v1/market/global-indices'),

  marketNews: (limit = 50) =>
    fetchJson<ApiList<NewsItem>>(`/api/v1/market/news?limit=${limit}`),

  stockNews: (tsCode: string, limit = 20) =>
    fetchJson<ApiList<NewsItem>>(`/api/v1/stock/${tsCode}/news?limit=${limit}`),

  stockAnns: (tsCode: string, limit = 20) =>
    fetchJson<ApiList<AnnItem>>(`/api/v1/stock/${tsCode}/anns?limit=${limit}`),

  stockWeekly: (code: string, start = '', end = '') =>
    fetchJson<ApiList<DailyBar>>(`/api/v1/stock/${code}/weekly?start=${start}&end=${end}`),

  stockMonthly: (code: string, start = '', end = '') =>
    fetchJson<ApiList<DailyBar>>(`/api/v1/stock/${code}/monthly?start=${start}&end=${end}`),

  stockMinutes: (code: string, start = '', end = '') =>
    fetchJson<ApiList<MinuteBar>>(`/api/v1/stock/${code}/minutes?start=${start}&end=${end}`),
};

// ── P2-Plus types ────────────────────────────────────────

export interface RankingRow {
  ts_code: string;
  name: string;
  close: number;
  pct_chg: number;
  turnover_rate: number | null;
  amount: number | null;
  vol: number | null;
}

export interface SectorRankRow {
  industry: string;
  avg_pct_chg: number;
  stock_count: number;
}

export interface MoneyFlowRow {
  ts_code: string;
  name: string;
  net_mf_amount: number;
  buy_elg_amount: number | null;
  sell_elg_amount: number | null;
  buy_lg_amount: number | null;
  sell_lg_amount: number | null;
}

export interface GlobalIndexRow {
  ts_code: string;
  name: string;
  close: number;
  pct_chg: number;
  vol: number | null;
}

export interface NewsItem {
  id: number;
  datetime: string;
  content: string;
  channels: string | null;
  source: string | null;
}

export interface AnnItem {
  id: number;
  ts_code: string;
  ann_date: string;
  title: string;
  url: string | null;
}

export interface MinuteBar {
  ts_code: string;
  trade_time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  vol: number;
  amount: number;
}

// ── Backtest types ───────────────────────────────────────

export interface StrategyInfo {
  name: string;
  description: string;
  default_params: Record<string, unknown>;
}

export interface RunBacktestRequest {
  strategy_name: string;
  strategy_params: Record<string, unknown>;
  start_date: string;
  end_date: string;
  initial_capital: number;
  benchmark: string;
  universe: string[];
}

export interface BacktestStats {
  total_return: number;
  annual_return: number;
  max_drawdown: number;
  max_drawdown_amount: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  win_rate: number;
  profit_factor: number;
  total_trades: number;
  avg_holding_days: number;
  benchmark_return: number;
}

export interface EquityPoint {
  date: string;
  total_asset: number;
  cash: number;
  market_value: number;
  daily_return: number;
  benchmark_return: number;
}

export interface TradeRecord {
  trade_date: string;
  signal_date: string;
  ts_code: string;
  side: string;
  price: number;
  qty: number;
  amount: number;
  fee: number;
  slippage: number;
  reason: string;
}

export interface BacktestRunResult {
  run_id: string;
  config: RunBacktestRequest;
  stats: BacktestStats;
  equity_curve: EquityPoint[];
  trades: TradeRecord[];
  filtered_signals: unknown[];
  started_at: string;
  finished_at: string | null;
}

export interface BacktestRunSummary {
  run_id: string;
  strategy_name: string;
  status: string;
  stats: BacktestStats | null;
  started_at: string;
  finished_at: string | null;
}
