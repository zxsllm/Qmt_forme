const BASE = '';

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(`${BASE}${url}`);
  if (!res.ok) throw new Error(`API ${res.status}: ${url}`);
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

export const api = {
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
};
