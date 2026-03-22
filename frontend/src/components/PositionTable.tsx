import { Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useQuery } from '@tanstack/react-query';
import { api, type SimPosition } from '../services/api';

const columns: ColumnsType<SimPosition> = [
  { title: '代码', dataIndex: 'ts_code', width: 100 },
  { title: '持仓', dataIndex: 'qty', width: 70, align: 'right' },
  {
    title: '成本',
    dataIndex: 'avg_cost',
    width: 80,
    align: 'right',
    render: (v: number) => v.toFixed(2),
  },
  {
    title: '现价',
    dataIndex: 'market_price',
    width: 80,
    align: 'right',
    render: (v: number) => v.toFixed(2),
  },
  {
    title: '浮动盈亏',
    dataIndex: 'unrealized_pnl',
    width: 90,
    align: 'right',
    render: (v: number) => (
      <span style={{ color: v >= 0 ? 'var(--color-down)' : 'var(--color-up)' }}>
        {v >= 0 ? '+' : ''}{v.toFixed(2)}
      </span>
    ),
  },
  {
    title: '已实现',
    dataIndex: 'realized_pnl',
    width: 80,
    align: 'right',
    render: (v: number) => (
      <Tag color={v >= 0 ? 'green' : 'red'} variant="filled" style={{ fontSize: 11, margin: 0 }}>
        {v >= 0 ? '+' : ''}{v.toFixed(2)}
      </Tag>
    ),
  },
];

export default function PositionTable() {
  const { data } = useQuery({
    queryKey: ['positions'],
    queryFn: api.getPositions,
    refetchInterval: 5000,
  });

  return (
    <Table
      columns={columns}
      dataSource={data?.data ?? []}
      rowKey="ts_code"
      size="small"
      pagination={false}
    />
  );
}
