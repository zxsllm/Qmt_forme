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
// Trading types (match backend Pydantic models)
// ---------------------------------------------------------------------------

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
};
