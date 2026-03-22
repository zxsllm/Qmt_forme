export interface Position {
  ts_code: string;
  name: string;
  qty: number;
  avg_cost: number;
  last_price: number;
  pnl: number;
  pnl_pct: number;
}

export interface Order {
  id: string;
  ts_code: string;
  name: string;
  direction: 'BUY' | 'SELL';
  price: number;
  qty: number;
  filled: number;
  status: 'pending' | 'partial' | 'filled' | 'canceled';
  time: string;
}

export interface TradePlan {
  ts_code: string;
  name: string;
  direction: 'BUY' | 'SELL';
  target_price: number;
  qty: number;
  reason: string;
  status: 'waiting' | 'triggered' | 'done';
}

export interface AccountSummary {
  total_assets: number;
  available_cash: number;
  market_value: number;
  total_pnl: number;
  daily_pnl: number;
  daily_pnl_pct: number;
}

export interface RiskRule {
  name: string;
  status: 'normal' | 'warning' | 'triggered';
  value: string;
  threshold: string;
}

export interface Strategy {
  id: string;
  name: string;
  enabled: boolean;
  pnl_today: number;
  signals: number;
  description: string;
}

export const mockPositions: Position[] = [
  { ts_code: '000001.SZ', name: '平安银行', qty: 5000, avg_cost: 10.85, last_price: 10.77, pnl: -400, pnl_pct: -0.74 },
  { ts_code: '600519.SH', name: '贵州茅台', qty: 100, avg_cost: 1680, last_price: 1725, pnl: 4500, pnl_pct: 2.68 },
  { ts_code: '300750.SZ', name: '宁德时代', qty: 200, avg_cost: 215, last_price: 228.5, pnl: 2700, pnl_pct: 6.28 },
  { ts_code: '002594.SZ', name: '比亚迪', qty: 300, avg_cost: 285, last_price: 278, pnl: -2100, pnl_pct: -2.46 },
];

export const mockOrders: Order[] = [
  { id: 'ORD001', ts_code: '000001.SZ', name: '平安银行', direction: 'BUY', price: 10.70, qty: 2000, filled: 2000, status: 'filled', time: '09:35:12' },
  { id: 'ORD002', ts_code: '600519.SH', name: '贵州茅台', direction: 'SELL', price: 1730, qty: 50, filled: 30, status: 'partial', time: '10:15:03' },
  { id: 'ORD003', ts_code: '300750.SZ', name: '宁德时代', direction: 'BUY', price: 225, qty: 100, filled: 0, status: 'pending', time: '13:01:45' },
];

export const mockTradePlans: TradePlan[] = [
  { ts_code: '000001.SZ', name: '平安银行', direction: 'BUY', target_price: 10.50, qty: 3000, reason: '回调至支撑位', status: 'waiting' },
  { ts_code: '601318.SH', name: '中国平安', direction: 'BUY', target_price: 48.00, qty: 500, reason: 'PE低于历史25%分位', status: 'waiting' },
  { ts_code: '300750.SZ', name: '宁德时代', direction: 'SELL', target_price: 240, qty: 100, reason: '止盈', status: 'waiting' },
];

export const mockAccount: AccountSummary = {
  total_assets: 1_285_600,
  available_cash: 542_300,
  market_value: 743_300,
  total_pnl: 35_600,
  daily_pnl: 4_700,
  daily_pnl_pct: 0.37,
};

export const mockRiskRules: RiskRule[] = [
  { name: '单票持仓上限', status: 'normal', value: '18%', threshold: '≤25%' },
  { name: '当日最大回撤', status: 'normal', value: '-0.8%', threshold: '≤-3%' },
  { name: '当日成交次数', status: 'warning', value: '45', threshold: '≤50' },
  { name: '单票亏损止损', status: 'normal', value: '-2.46%', threshold: '≤-5%' },
  { name: 'Kill Switch', status: 'normal', value: 'OFF', threshold: '手动' },
];

export const mockStrategies: Strategy[] = [
  { id: 'stg-001', name: '均线突破策略', enabled: true, pnl_today: 1200, signals: 3, description: '5日均线上穿20日均线买入' },
  { id: 'stg-002', name: 'PE价值选股', enabled: true, pnl_today: -300, signals: 1, description: 'PE低于行业25%分位买入' },
  { id: 'stg-003', name: '涨停板打板', enabled: false, pnl_today: 0, signals: 0, description: '首板打板策略 (已禁用)' },
];

export const mockLogs = [
  { time: '14:32:05', level: 'info', msg: '策略[均线突破]触发买入信号: 000001.SZ @ 10.77' },
  { time: '14:30:00', level: 'info', msg: '分钟数据更新: 5481只股票 14:30 bar 已接收' },
  { time: '14:15:22', level: 'warn', msg: '风控提醒: 当日成交次数已达45次, 接近上限50' },
  { time: '13:01:45', level: 'info', msg: '订单提交: BUY 300750.SZ 100股 @ 225.00' },
  { time: '10:15:03', level: 'info', msg: '订单部分成交: SELL 600519.SH 30/50股 @ 1730.00' },
  { time: '09:35:12', level: 'info', msg: '订单成交: BUY 000001.SZ 2000股 @ 10.70' },
  { time: '09:30:00', level: 'info', msg: '交易日开始, 3个策略运行中' },
  { time: '09:25:00', level: 'info', msg: '行情连接就绪, 数据源: Tushare Pro' },
];
