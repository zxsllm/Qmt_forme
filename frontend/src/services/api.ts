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

export interface DataDiagnosis {
  reason: string;
  detail: string;
  action: string;
  repairable: boolean;
}

export interface DataHealthCheck {
  name: string;
  label: string;
  actual_date: string;
  expected_date: string;
  status: 'ok' | 'stale' | 'missing' | 'unknown';
  severity: 'critical' | 'important' | 'minor';
  note: string;
  diagnosis: DataDiagnosis | null;
  gap_days: number;
}

export interface DataHealthReport {
  timestamp: string;
  phase: string;
  phase_label: string;
  is_trade_date: boolean;
  today: string;
  expected_daily_date: string;
  expected_sentiment_date: string;
  overall: 'healthy' | 'warning' | 'degraded' | 'critical';
  groups: Record<string, DataHealthCheck[]>;
  group_labels: Record<string, string>;
  repair: { triggered: boolean; tables: string[]; trade_date?: string; message?: string } | null;
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

  indexWeekly: (code: string, start = '', end = '') =>
    fetchJson<ApiList<IndexBar>>(
      `/api/v1/index/${code}/weekly?start=${start}&end=${end}`,
    ),

  indexMonthly: (code: string, start = '', end = '') =>
    fetchJson<ApiList<IndexBar>>(
      `/api/v1/index/${code}/monthly?start=${start}&end=${end}`,
    ),

  indexValuation: (code: string, start = '', end = '', days = 60) =>
    fetchJson<ApiList<Record<string, unknown>>>(
      `/api/v1/index/${code}/valuation?start=${start}&end=${end}&days=${days}`,
    ),

  searchIndex: (q: string) =>
    fetchJson<ApiList<Record<string, unknown>>>(`/api/v1/index/search?q=${encodeURIComponent(q)}`),

  swClassify: (level = '') =>
    fetchJson<ApiList<SwClassify>>(`/api/v1/classify/sw?level=${level}`),

  // Stock search (include_index=true to also search indices)
  searchStocks: (q: string, includeIndex = false) =>
    fetchJson<ApiList<StockSearchResult>>(
      `/api/v1/stock/search?q=${encodeURIComponent(q)}&include_index=${includeIndex}`,
    ),

  // 8 new data APIs (Phase 4.9)
  getShareFloat: (tsCode: string, start = '', end = '') =>
    fetchJson<ApiList<Record<string, unknown>>>(
      `/api/v1/stock/${tsCode}/share-float?start=${start}&end=${end}`,
    ),

  getHolderTrade: (tsCode: string, start = '', end = '') =>
    fetchJson<ApiList<Record<string, unknown>>>(
      `/api/v1/stock/${tsCode}/holdertrade?start=${start}&end=${end}`,
    ),

  getMargin: (start = '', end = '', days = 30) =>
    fetchJson<ApiList<Record<string, unknown>>>(
      `/api/v1/market/margin?start=${start}&end=${end}&days=${days}`,
    ),

  getStPredict: () =>
    fetchJson<{ count: number; data: StPredictItem[]; report_year?: number }>('/api/v1/market/st-predict'),

  indexSectorResonance: (indexCode = '000001.SH', days = 20, level = 'L1') =>
    fetchJson<SectorResonanceResponse>(`/api/v1/monitor/index-sector-resonance?index_code=${indexCode}&days=${days}&level=${level}`),

  monitorSnapshot: () =>
    fetchJson<MonitorSnapshot>('/api/v1/monitor/snapshot'),

  getTopInst: (tradeDate = '', tsCode = '') =>
    fetchJson<ApiList<Record<string, unknown>>>(
      `/api/v1/market/top-inst?trade_date=${tradeDate}&ts_code=${tsCode}`,
    ),

  getTop10Holders: (tsCode: string, periods = 4) =>
    fetchJson<ApiList<Record<string, unknown>>>(
      `/api/v1/stock/${tsCode}/top10-holders?periods=${periods}`,
    ),

  getHolderNumber: (tsCode: string, start = '', end = '') =>
    fetchJson<ApiList<Record<string, unknown>>>(
      `/api/v1/stock/${tsCode}/holder-number?start=${start}&end=${end}`,
    ),

  getUpcomingShareFloat: (days = 30) =>
    fetchJson<ApiList<Record<string, unknown>>>(
      `/api/v1/market/share-float-upcoming?days=${days}`,
    ),

  getRecentHolderTrade: (days = 7, tradeType = '') =>
    fetchJson<ApiList<Record<string, unknown>>>(
      `/api/v1/market/holdertrade-recent?days=${days}&trade_type=${tradeType}`,
    ),

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

  getRiskAlerts: () =>
    fetchJson<RiskAlertsResponse>('/api/v1/risk/alerts'),

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

  sectorStocks: (industry: string) =>
    fetchJson<ApiList<SectorStockRow>>(`/api/v1/sector/${encodeURIComponent(industry)}/stocks`),

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

  stockIrmQa: (tsCode: string, limit = 20) =>
    fetchJson<ApiList<IrmQaItem>>(`/api/v1/stock/${tsCode}/irm_qa?limit=${limit}`),

  stockWeekly: (code: string, start = '', end = '') =>
    fetchJson<ApiList<DailyBar>>(`/api/v1/stock/${code}/weekly?start=${start}&end=${end}`),

  stockMonthly: (code: string, start = '', end = '') =>
    fetchJson<ApiList<DailyBar>>(`/api/v1/stock/${code}/monthly?start=${start}&end=${end}`),

  stockMinutes: (code: string, start = '', end = '') =>
    fetchJson<ApiList<MinuteBar>>(`/api/v1/stock/${code}/minutes?start=${start}&end=${end}`),

  // ── Classified News / Anns ────────────────────────────────
  classifiedNews: (params: { scope?: string; time_slot?: string; sentiment?: string; start_date?: string; end_date?: string; limit?: number } = {}) =>
    fetchJson<ApiList<ClassifiedNewsItem>>(
      `/api/v1/market/news/classified?scope=${params.scope || ''}&time_slot=${params.time_slot || ''}&sentiment=${params.sentiment || ''}&start_date=${params.start_date || ''}&end_date=${params.end_date || ''}&limit=${params.limit || 50}`,
    ),

  classifiedAnns: (params: { ann_type?: string; sentiment?: string; start_date?: string; end_date?: string; limit?: number } = {}) =>
    fetchJson<ApiList<ClassifiedAnnItem>>(
      `/api/v1/market/anns/classified?ann_type=${params.ann_type || ''}&sentiment=${params.sentiment || ''}&limit=${params.limit || 50}`,
    ),

  newsStats: (params: { start_date?: string; end_date?: string } = {}) =>
    fetchJson<{ data: NewsStatRow[] }>(
      `/api/v1/market/news/stats?start_date=${params.start_date || ''}&end_date=${params.end_date || ''}`,
    ),

  // ── Sentiment ─────────────────────────────────────────────
  limitBoard: (params: { trade_date?: string; limit_type?: string } = {}) =>
    fetchJson<{ count: number; data: LimitBoardItem[]; trade_date: string }>(
      `/api/v1/sentiment/limit-board?trade_date=${params.trade_date || ''}&limit_type=${params.limit_type || ''}`,
    ),

  limitStep: (trade_date = '') =>
    fetchJson<{ count: number; data: LimitStepItem[]; trade_date: string }>(
      `/api/v1/sentiment/limit-step?trade_date=${trade_date}`,
    ),

  dragonTiger: (trade_date = '', limit = 30) =>
    fetchJson<{ count: number; data: DragonTigerItem[]; trade_date: string }>(
      `/api/v1/sentiment/dragon-tiger?trade_date=${trade_date}&limit=${limit}`,
    ),

  dragonTigerSeats: (ts_code: string, trade_date: string) =>
    fetchJson<{ buy_seats: SeatItem[]; sell_seats: SeatItem[] }>(
      `/api/v1/sentiment/dragon-tiger-seats?ts_code=${ts_code}&trade_date=${trade_date}`,
    ),

  hotList: (trade_date = '', limit = 30) =>
    fetchJson<{ count: number; data: HotListItem[]; trade_date: string }>(
      `/api/v1/sentiment/hot-list?trade_date=${trade_date}&limit=${limit}`,
    ),

  // ── Fundamental ─────────────────────────────────────────────
  fundamentalIndustries: () =>
    fetchJson<{ data: IndustryItem[] }>('/api/v1/fundamental/industries'),

  fundamentalConcepts: () =>
    fetchJson<{ data: ConceptItem[] }>('/api/v1/fundamental/concepts'),

  industryProfile: (industry: string) =>
    fetchJson<{ count: number; data: IndustryStockRow[] }>(
      `/api/v1/fundamental/industry/${encodeURIComponent(industry)}`,
    ),

  conceptStocks: (code: string) =>
    fetchJson<{ count: number; data: ConceptStockRow[] }>(
      `/api/v1/fundamental/concept/${encodeURIComponent(code)}`,
    ),

  companyProfile: (tsCode: string) =>
    fetchJson<CompanyProfile>(`/api/v1/fundamental/company/${tsCode}`),

  eventCalendar: (start = '', end = '') =>
    fetchJson<EventCalendarData>(`/api/v1/fundamental/events?start=${start}&end=${end}`),

  // ── C-Step4: Sentiment analysis engine ──────────────────────
  marketTemperature: (tradeDate = '') =>
    fetchJson<MarketTemperatureResp>(`/api/v1/sentiment/temperature?trade_date=${tradeDate}`),

  boardLeaders: (tradeDate = '', concept = '') =>
    fetchJson<BoardLeaderResp>(`/api/v1/sentiment/leaders?trade_date=${tradeDate}&concept=${encodeURIComponent(concept)}`),

  continuationAnalysis: (tsCode: string) =>
    fetchJson<ContinuationResp>(`/api/v1/sentiment/continuation/${tsCode}`),

  hotMoneySignal: (tradeDate = '') =>
    fetchJson<HotMoneyResp>(`/api/v1/sentiment/hot-money?trade_date=${tradeDate}`),

  // ── C-Step5: Pre-market plan ──────────────────────────────
  premarketPlan: (date = '') =>
    fetchJson<PremarketPlanResp>(`/api/v1/premarket/plan?date=${date}`),

  // ── D-Step1: Technical signals ────────────────────────────
  techVolume: (tsCode: string, tradeDate = '') =>
    fetchJson<VolumeAnomalyResp>(`/api/v1/tech/${tsCode}/volume?trade_date=${tradeDate}`),

  techGaps: (tsCode: string, tradeDate = '') =>
    fetchJson<GapResp>(`/api/v1/tech/${tsCode}/gaps?trade_date=${tradeDate}`),

  techSupportResistance: (tsCode: string, days = 60) =>
    fetchJson<SupportResistanceResp>(`/api/v1/tech/${tsCode}/support-resistance?days=${days}`),

  // ── D-Step2: Risk auxiliary rules ─────────────────────────
  techRiskCheck: (tsCode: string, tradeDate = '') =>
    fetchJson<RiskCheckResp>(`/api/v1/tech/${tsCode}/risk-check?trade_date=${tradeDate}`),

  // ── Feed control ──────────────────────────────────────────
  startFeed: () =>
    postJson<{ status: string }>('/api/v1/feed/start', {}),

  stopFeed: () =>
    postJson<{ status: string }>('/api/v1/feed/stop', {}),

  dataHealth: () =>
    fetchJson<DataHealthReport>('/api/v1/system/data-health'),
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

export interface SectorStockRow {
  ts_code: string;
  name: string;
  close: number | null;
  pct_chg: number | null;
  vol: number | null;
  amount: number | null;
  circ_mv: number | null;
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

export interface IrmQaItem {
  ts_code: string;
  name: string;
  trade_date: string;
  q: string;
  a: string;
  pub_time: string | null;
  industry?: string | null;
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

// ── Classified News / Anns types ─────────────────────────────

export interface ClassifiedNewsItem {
  id: number;
  datetime: string;
  content: string;
  channels: string | null;
  source: string | null;
  news_scope: string;
  time_slot: string;
  sentiment: string;
  related_codes: string | null;
  related_industries: string | null;
  keywords: string | null;
}

export interface ClassifiedAnnItem {
  id: number;
  ts_code: string;
  ann_date: string;
  title: string;
  url: string | null;
  ann_type: string;
  sentiment: string;
  keywords: string | null;
}

export interface NewsStatRow {
  scope: string;
  time_slot: string;
  sentiment: string;
  count: number;
}

// ── Sentiment types ──────────────────────────────────────────

export interface LimitBoardItem {
  ts_code: string;
  name: string;
  pct_chg: number | null;
  trade_date: string;
  limit_type: string;
  limit_amount: number | null;
  turnover_rate: number | null;
  tag: string | null;
  status: string | null;
  open_num: number | null;
  first_lu_time: string | null;
  last_lu_time: string | null;
}

export interface LimitStepItem {
  ts_code: string;
  name: string;
  trade_date: string;
  nums: string;
}

export interface DragonTigerItem {
  ts_code: string;
  name: string;
  trade_date: string;
  close: number | null;
  pct_change: number | null;
  turnover_rate: number | null;
  amount: number | null;
  l_sell: number | null;
  l_buy: number | null;
  l_amount: number | null;
  net_amount: number | null;
  net_rate: number | null;
  reason: string | null;
}

export interface SeatItem {
  exalter: string;
  buy: number | null;
  sell: number | null;
  net_buy: number | null;
  seat_type: string;
  hm_name: string | null;
}

export interface HotListItem {
  ts_code: string;
  ts_name: string;
  data_type: string | null;
  trade_date: string;
  pct_change: number | null;
  rank: number | null;
  current_price: number | null;
}

// ── Fundamental types ────────────────────────────────────────

export interface IndustryItem {
  industry: string;
  count: number;
}

export interface ConceptItem {
  code: string;
  name: string;
  count: number;
}

export interface IndustryStockRow {
  ts_code: string;
  name: string;
  industry: string;
  list_date: string | null;
  fina_period: string | null;
  roe: number | null;
  netprofit_margin: number | null;
  grossprofit_margin: number | null;
  netprofit_yoy: number | null;
  or_yoy: number | null;
  eps: number | null;
  bps: number | null;
  debt_to_assets: number | null;
  pe_ttm: number | null;
  pb: number | null;
  total_mv: number | null;
  circ_mv: number | null;
  turnover_rate: number | null;
}

export interface ConceptStockRow {
  ts_code: string;
  name: string;
  industry: string;
  roe: number | null;
  netprofit_yoy: number | null;
  or_yoy: number | null;
  eps: number | null;
  pe_ttm: number | null;
  pb: number | null;
  total_mv: number | null;
}

export interface CompanyProfile {
  basic: {
    ts_code: string;
    name: string;
    industry: string;
    area: string | null;
    market: string | null;
    list_date: string | null;
    fullname: string | null;
  };
  valuation: {
    trade_date?: string;
    pe_ttm?: number | null;
    pb?: number | null;
    total_mv?: number | null;
    circ_mv?: number | null;
    turnover_rate?: number | null;
  };
  fina_history: {
    end_date: string;
    roe: number | null;
    netprofit_margin: number | null;
    grossprofit_margin: number | null;
    netprofit_yoy: number | null;
    or_yoy: number | null;
    eps: number | null;
    bps: number | null;
    debt_to_assets: number | null;
    current_ratio: number | null;
    quick_ratio: number | null;
    roa: number | null;
    ocfps: number | null;
  }[];
  main_business: {
    end_date: string;
    bz_item: string;
    bz_sales: number | null;
    bz_profit: number | null;
    bz_cost: number | null;
  }[];
  forecasts: {
    ann_date: string;
    end_date: string;
    type: string | null;
    p_change_min: number | null;
    p_change_max: number | null;
    net_profit_min: number | null;
    net_profit_max: number | null;
    summary: string | null;
  }[];
  concepts: string[];
}

// ── C-Step4: Sentiment analysis types ────────────────────────

export interface MarketTemperatureData {
  limit_up: number;
  limit_down: number;
  broken: number;
  seal_rate: number;
  max_board: number;
  ladder: { level: number; count: number }[];
  hot_money: { active_seats: number; involved_stocks: number; total_buy: number | null; total_sell: number | null };
  temperature: string;
}
export interface MarketTemperatureResp { trade_date: string; data: MarketTemperatureData | null }

export interface BoardLeaderItem {
  ts_code: string; name: string; pct_chg: number | null;
  first_lu_time: string | null; last_lu_time: string | null;
  open_num: number | null; limit_amount: number | null;
  turnover_rate: number | null; tag: string | null;
  status: string | null; rank: number; label: string;
}
export interface BoardLeaderResp { trade_date: string; count: number; data: BoardLeaderItem[] }

export interface ContinuationResp {
  ts_code: string; current_streak: number; max_streak: number;
  broken_rate: number; total_limit_up_days: number; total_broken_days: number;
  recent_history: { trade_date: string; limit_type: string; pct_chg: number | null; open_num: number | null; first_lu_time: string | null }[];
  step_history: { trade_date: string; nums: number }[];
}

export interface HotMoneyItem {
  hm_name: string; stock_count: number;
  total_buy: number | null; total_sell: number | null; total_net: number | null;
  stocks: string[];
}
export interface HotMoneyResp { trade_date: string; data: HotMoneyItem[] }

// ── C-Step5: Pre-market plan types ───────────────────────────

export interface PremarketPlanResp {
  today: string; yesterday: string;
  market_summary: {
    limit_up?: number; limit_down?: number; broken?: number;
    seal_rate?: number; max_board?: number;
    hot_sectors?: { name: string; up_nums: number | null; cons_nums: number | null }[];
  };
  watchlist: { ts_code: string; name: string; reason: string; nums?: string; tag?: string; pct_chg?: number | null }[];
  risk_alerts: { ts_code: string; name: string; type: string; detail: string; tag?: string | null }[];
}

// ── D-Step1/2: Technical signal types ────────────────────────

export interface VolumeAnomalyResp {
  ts_code: string; trade_date?: string;
  data: { today_vol: number | null; avg_vol_20d: number | null; ratio: number | null; signal: string; today_close: number | null; today_pct_chg: number | null } | null;
}

export interface GapResp {
  ts_code: string;
  gaps: { trade_date: string; type: string; gap_low: number; gap_high: number; gap_pct: number; filled: boolean }[];
}

export interface SupportResistanceResp {
  ts_code: string;
  data: {
    current_close: number; position_pct: number;
    period_high: { price: number; date: string }; period_low: { price: number; date: string };
    resistance: number[]; support: number[];
    ma5: number | null; ma10: number | null; ma20: number | null;
  } | null;
}

export interface RiskCheckResp {
  ts_code: string; trade_date?: string;
  warnings: { rule: string; level: string; message: string }[];
  risk_level: string;
}

export interface EventCalendarData {
  disclosures: {
    ts_code: string;
    name: string;
    end_date: string;
    actual_date: string | null;
    pre_date: string | null;
  }[];
  forecasts: {
    ts_code: string;
    name: string;
    ann_date: string;
    end_date: string;
    type: string | null;
    p_change_min: number | null;
    p_change_max: number | null;
    summary: string | null;
  }[];
}

export interface StPredictItem {
  ts_code: string;
  name: string;
  profit: number | null;
  revenue: number | null;
  bps: number | null;
  net_profit_min: number | null;
  net_profit_max: number | null;
  forecast_ann_date: string | null;
  pre_date: string | null;
  predicted_st_date: string | null;
  disclosure_date: string;
  warn_count: number;
  reason: string;
}

export interface SectorResonanceItem {
  ts_code: string;
  name: string;
  correlation: number;
  cum_return: number;
  latest_pct: number;
  close: number | null;
  days_matched: number;
}

export interface SectorResonanceResponse {
  index_code: string;
  days: number;
  total_dates: number;
  sectors: SectorResonanceItem[];
}

export interface MonitorIndexRow {
  code: string;
  name: string;
  price: number;
  windows: Record<string, number | null>;
}

export interface MonitorSectorRow {
  name: string;
  pct_chg: number;
  windows: Record<string, number | null>;
}

export interface MonitorAnomalyEvent {
  ts: number;
  time: string;
  index_code: string;
  index_name: string;
  window: string;
  delta_pct: number;
  price_now: number;
  price_then: number;
  top_sectors: { name: string; delta: number; pct_now: number }[];
}

export interface MonitorSnapshot {
  ts: number;
  history_len: number;
  indices: MonitorIndexRow[];
  sectors: MonitorSectorRow[];
  anomalies: MonitorAnomalyEvent[];
  anomaly_count: number;
}

export interface RiskAlert {
  type: string;
  level: string;
  ts_code: string;
  name?: string;
  detail: string;
  time?: string;
  forecast_type?: string;
  pct_range?: string;
  bond_code?: string;
  bond_name?: string;
  stk_code?: string;
  is_call?: string;
  call_date?: string;
}

export interface RiskAlertsResponse {
  count: number;
  data: RiskAlert[];
  summary: {
    st: number;
    forecast: number;
    cb_call: number;
  };
}
