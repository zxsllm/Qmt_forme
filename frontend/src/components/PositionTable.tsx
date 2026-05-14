import { Table, Tag, Button, Popconfirm, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type SimPosition } from '../services/api';

interface Props {
  strategy?: string;
}

export default function PositionTable({ strategy = 'default' }: Props) {
  const qc = useQueryClient();

  const { data } = useQuery({
    queryKey: ['positions', strategy],
    queryFn: () => api.getPositions(strategy),
    refetchInterval: 5000,
  });

  const closeMut = useMutation({
    mutationFn: (pos: SimPosition) =>
      api.submitOrder({
        ts_code: pos.ts_code,
        side: 'SELL',
        order_type: 'MARKET',
        qty: pos.qty,
      }, strategy),
    onSuccess: () => {
      message.success('平仓订单已提交');
      qc.invalidateQueries({ queryKey: ['positions', strategy] });
      qc.invalidateQueries({ queryKey: ['orders', strategy] });
      qc.invalidateQueries({ queryKey: ['account', strategy] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const closeAllMut = useMutation({
    mutationFn: async () => {
      const positions = data?.data ?? [];
      for (const pos of positions) {
        await api.submitOrder({
          ts_code: pos.ts_code,
          side: 'SELL',
          order_type: 'MARKET',
          qty: pos.qty,
        }, strategy);
      }
    },
    onSuccess: () => {
      message.success('全部清仓订单已提交');
      qc.invalidateQueries({ queryKey: ['positions', strategy] });
      qc.invalidateQueries({ queryKey: ['orders', strategy] });
      qc.invalidateQueries({ queryKey: ['account', strategy] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const positions = data?.data ?? [];

  const sellAnchorTag = (anchor?: string) => {
    if (!anchor) return null;
    const map: Record<string, { c: string; t: string }> = {
      next_open: { c: 'blue', t: 'T+1 开盘' },
      today_close: { c: 'orange', t: '当日收盘' },
      intraday_at: { c: 'purple', t: '盘中定时' },
    };
    const s = map[anchor] ?? { c: 'default', t: anchor };
    return <Tag color={s.c} variant="filled" style={{ fontSize: 11, margin: 0 }}>{s.t}</Tag>;
  };

  const pickRoleTag = (role?: string) => {
    if (!role) return null;
    const map: Record<string, string> = {
      long1: '龙1',
      shadow: '影子',
      follower_cb: 'CB跟风',
      follower_cb_rebuy: 'CB买回',
    };
    return (
      <Tag color="cyan" variant="filled" style={{ fontSize: 11, margin: 0 }}>
        {map[role] ?? role}
      </Tag>
    );
  };

  const columns: ColumnsType<SimPosition> = [
    {
      title: 'Lot', dataIndex: 'lot_id', width: 80,
      render: (v?: string) => v ? (
        <span style={{ color: '#93a9bc', fontSize: 11, fontFamily: 'monospace' }}>{v.slice(0, 8)}</span>
      ) : '-',
    },
    { title: '代码', dataIndex: 'ts_code', width: 100 },
    {
      title: '角色', dataIndex: 'pick_role', width: 80,
      render: (v?: string) => pickRoleTag(v),
    },
    { title: '持仓', dataIndex: 'qty', width: 70, align: 'right' },
    {
      title: '成本', dataIndex: 'avg_cost', width: 80, align: 'right',
      render: (v: number) => v.toFixed(2),
    },
    {
      title: '现价', dataIndex: 'market_price', width: 80, align: 'right',
      render: (v: number) => v.toFixed(2),
    },
    {
      title: '浮动盈亏', dataIndex: 'unrealized_pnl', width: 90, align: 'right',
      render: (v: number) => (
        <span style={{ color: v >= 0 ? 'var(--color-down)' : 'var(--color-up)' }}>
          {v >= 0 ? '+' : ''}{v.toFixed(2)}
        </span>
      ),
    },
    {
      title: '已实现', dataIndex: 'realized_pnl', width: 80, align: 'right',
      render: (v: number) => (
        <Tag color={v >= 0 ? 'green' : 'red'} variant="filled" style={{ fontSize: 11, margin: 0 }}>
          {v >= 0 ? '+' : ''}{v.toFixed(2)}
        </Tag>
      ),
    },
    {
      title: '出场方式', dataIndex: 'sell_anchor', width: 110,
      render: (v?: string) => sellAnchorTag(v),
    },
    {
      title: '出场日期', dataIndex: 'sell_anchor_date', width: 100,
      render: (v?: string) => v ? <span style={{ fontSize: 11, color: '#93a9bc' }}>{v}</span> : '-',
    },
    {
      title: '操作', width: 70, align: 'center', fixed: 'right',
      render: (_: unknown, record: SimPosition) =>
        record.qty > 0 ? (
          <Popconfirm
            title={`确认平仓 ${record.ts_code} 全部 ${record.qty} 股?`}
            onConfirm={() => closeMut.mutate(record)}
            okText="确认"
            cancelText="取消"
          >
            <Button size="small" danger style={{ fontSize: 11, height: 22 }}>
              平仓
            </Button>
          </Popconfirm>
        ) : null,
    },
  ];

  return (
    <div className="flex flex-col h-full">
      {positions.length > 0 && (
        <div style={{ padding: '4px 12px', textAlign: 'right' }}>
          <Popconfirm
            title={`确认清仓全部 ${positions.length} 只股票?`}
            onConfirm={() => closeAllMut.mutate()}
            okText="确认清仓"
            cancelText="取消"
          >
            <Button size="small" danger style={{ fontSize: 11, height: 22 }}>
              全部清仓
            </Button>
          </Popconfirm>
        </div>
      )}
      <Table
        columns={columns}
        dataSource={positions}
        rowKey={(record) => record.lot_id || record.ts_code}
        size="small"
        pagination={false}
        scroll={{ x: 'max-content' }}
      />
    </div>
  );
}
