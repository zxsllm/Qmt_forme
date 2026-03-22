import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  DollarOutlined,
  PieChartOutlined,
  FundOutlined,
} from '@ant-design/icons';
import { mockAccount, mockPositions } from '../services/mockData';

interface StatItem {
  icon: React.ReactNode;
  iconBg: string;
  label: string;
  value: string;
  sub: string;
  valueColor?: string;
  subColor?: string;
}

export default function AccountCard() {
  const a = mockAccount;
  const up = a.daily_pnl >= 0;

  const cards: StatItem[] = [
    {
      icon: <DollarOutlined />,
      iconBg: '#1d4ed8',
      label: '总资产',
      value: `¥${a.total_assets.toLocaleString()}`,
      sub: `可用 ¥${a.available_cash.toLocaleString()}`,
    },
    {
      icon: <PieChartOutlined />,
      iconBg: '#7c3aed',
      label: '持仓市值',
      value: `¥${a.market_value.toLocaleString()}`,
      sub: `${mockPositions.length} 只持仓`,
    },
    {
      icon: up ? <ArrowUpOutlined /> : <ArrowDownOutlined />,
      iconBg: up ? '#15803d' : '#b91c1c',
      label: '今日盈亏',
      value: `${up ? '+' : ''}¥${a.daily_pnl.toLocaleString()}`,
      sub: `${up ? '+' : ''}${a.daily_pnl_pct.toFixed(2)}%`,
      valueColor: up ? 'var(--color-down)' : 'var(--color-up)',
      subColor: up ? 'var(--color-down)' : 'var(--color-up)',
    },
    {
      icon: <FundOutlined />,
      iconBg: '#b45309',
      label: '累计盈亏',
      value: `${a.total_pnl >= 0 ? '+' : ''}¥${a.total_pnl.toLocaleString()}`,
      sub: '持仓收益',
      valueColor: a.total_pnl >= 0 ? 'var(--color-down)' : 'var(--color-up)',
      subColor: a.total_pnl >= 0 ? 'var(--color-down)' : 'var(--color-up)',
    },
  ];

  return (
    <div className="grid grid-cols-4" style={{ gap: 10 }}>
      {cards.map((c, i) => (
        <div
          key={i}
          className="flex items-center bg-bg-panel rounded-panel"
          style={{ padding: '8px 14px', gap: 10 }}
        >
          <div
            className="flex items-center justify-center shrink-0"
            style={{
              width: 26,
              height: 26,
              borderRadius: 6,
              background: c.iconBg,
              fontSize: 13,
              color: '#fff',
              opacity: 0.85,
            }}
          >
            {c.icon}
          </div>
          <div className="min-w-0 flex flex-col" style={{ gap: 1 }}>
            <div className="text-t3 text-[10px] truncate">{c.label}</div>
            <div
              className="font-medium text-[13px] truncate"
              style={{ color: c.valueColor || 'var(--color-t1)', lineHeight: 1.25 }}
            >
              {c.value}
            </div>
            <div
              className="text-[10px] truncate"
              style={{ color: c.subColor || 'var(--color-t3)', marginTop: 1 }}
            >
              {c.sub}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
