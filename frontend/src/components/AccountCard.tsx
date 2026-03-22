import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  DollarOutlined,
  PieChartOutlined,
  FundOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { Popconfirm, message } from 'antd';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';

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
  const qc = useQueryClient();
  const { data: acct } = useQuery({
    queryKey: ['account'],
    queryFn: api.getAccount,
    refetchInterval: 5000,
  });
  const { data: posData } = useQuery({
    queryKey: ['positions'],
    queryFn: api.getPositions,
    refetchInterval: 5000,
  });
  const resetMut = useMutation({
    mutationFn: () => api.resetAccount(),
    onSuccess: () => {
      message.success('账户已重置');
      qc.invalidateQueries();
    },
    onError: (e: Error) => message.error(e.message),
  });

  const a = acct ?? { total_asset: 0, cash: 0, frozen: 0, market_value: 0, total_pnl: 0, today_pnl: 0, updated_at: '' };
  const posCount = posData?.count ?? 0;
  const up = a.today_pnl >= 0;
  const pnlPct = a.total_asset > 0 ? (a.today_pnl / a.total_asset) * 100 : 0;

  const cards: StatItem[] = [
    {
      icon: <DollarOutlined />,
      iconBg: '#1d4ed8',
      label: '总资产',
      value: `¥${a.total_asset.toLocaleString()}`,
      sub: `可用 ¥${a.cash.toLocaleString()}`,
    },
    {
      icon: <PieChartOutlined />,
      iconBg: '#7c3aed',
      label: '持仓市值',
      value: `¥${a.market_value.toLocaleString()}`,
      sub: `${posCount} 只持仓`,
    },
    {
      icon: up ? <ArrowUpOutlined /> : <ArrowDownOutlined />,
      iconBg: up ? '#15803d' : '#b91c1c',
      label: '今日盈亏',
      value: `${up ? '+' : ''}¥${a.today_pnl.toLocaleString()}`,
      sub: `${up ? '+' : ''}${pnlPct.toFixed(2)}%`,
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
          style={{ padding: '8px 14px', gap: 10, position: 'relative' }}
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
          {i === 0 && (
            <Popconfirm
              title="确认重置模拟账户? 所有持仓和订单将被清空"
              onConfirm={() => resetMut.mutate()}
              okText="确认重置"
              cancelText="取消"
            >
              <ReloadOutlined
                style={{
                  position: 'absolute', top: 6, right: 8,
                  fontSize: 11, color: 'var(--color-t3)', cursor: 'pointer',
                }}
              />
            </Popconfirm>
          )}
        </div>
      ))}
    </div>
  );
}
