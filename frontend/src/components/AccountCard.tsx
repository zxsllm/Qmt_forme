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
      iconBg: 'linear-gradient(135deg, #2481bd, #3b61d6)',
      label: '总资产',
      value: `¥${a.total_asset.toLocaleString()}`,
      sub: `可用 ¥${a.cash.toLocaleString()}`,
    },
    {
      icon: <PieChartOutlined />,
      iconBg: 'linear-gradient(135deg, #7c3aed, #b48cff)',
      label: '持仓市值',
      value: `¥${a.market_value.toLocaleString()}`,
      sub: `${posCount} 只持仓`,
    },
    {
      icon: up ? <ArrowUpOutlined /> : <ArrowDownOutlined />,
      iconBg: up ? 'linear-gradient(135deg, #15803d, #4ade80)' : 'linear-gradient(135deg, #b91c1c, #ff6f91)',
      label: '今日盈亏',
      value: `${up ? '+' : ''}¥${a.today_pnl.toLocaleString()}`,
      sub: `${up ? '+' : ''}${pnlPct.toFixed(2)}%`,
      valueColor: up ? '#4ade80' : '#ff6f91',
      subColor: up ? '#4ade80' : '#ff6f91',
    },
    {
      icon: <FundOutlined />,
      iconBg: 'linear-gradient(135deg, #b45309, #ffbf75)',
      label: '累计盈亏',
      value: `${a.total_pnl >= 0 ? '+' : ''}¥${a.total_pnl.toLocaleString()}`,
      sub: '持仓收益',
      valueColor: a.total_pnl >= 0 ? '#4ade80' : '#ff6f91',
      subColor: a.total_pnl >= 0 ? '#4ade80' : '#ff6f91',
    },
  ];

  return (
    <div className="grid grid-cols-4" style={{ gap: 12 }}>
      {cards.map((c, i) => (
        <div
          key={i}
          className="flex items-center"
          style={{
            padding: '10px 16px',
            gap: 12,
            position: 'relative',
            background: 'linear-gradient(180deg, rgba(23,42,59,0.88), rgba(8,17,25,0.92))',
            border: '1px solid rgba(148,186,215,0.18)',
            borderRadius: 16,
            boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.04), 0 12px 32px rgba(0,0,0,0.28)',
            backdropFilter: 'blur(10px)',
          }}
        >
          <div
            className="flex items-center justify-center shrink-0"
            style={{
              width: 30,
              height: 30,
              borderRadius: 10,
              background: c.iconBg,
              fontSize: 14,
              color: '#fff',
            }}
          >
            {c.icon}
          </div>
          <div className="min-w-0 flex flex-col" style={{ gap: 2 }}>
            <div style={{ fontSize: 11, color: '#93a9bc', letterSpacing: '0.04em' }} className="truncate">
              {c.label}
            </div>
            <div
              className="font-semibold truncate"
              style={{ fontSize: 14, color: c.valueColor || '#e6f1fa', lineHeight: 1.25 }}
            >
              {c.value}
            </div>
            <div
              className="truncate"
              style={{ fontSize: 10, color: c.subColor || '#64748b', marginTop: 1 }}
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
                  position: 'absolute', top: 8, right: 10,
                  fontSize: 11, color: '#64748b', cursor: 'pointer',
                }}
              />
            </Popconfirm>
          )}
        </div>
      ))}
    </div>
  );
}
