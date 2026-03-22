import { Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { mockPositions, type Position } from '../services/mockData';

const columns: ColumnsType<Position> = [
  { title: '代码', dataIndex: 'ts_code', width: 100 },
  { title: '名称', dataIndex: 'name', width: 80 },
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
    dataIndex: 'last_price',
    width: 80,
    align: 'right',
    render: (v: number) => v.toFixed(2),
  },
  {
    title: '盈亏',
    dataIndex: 'pnl',
    width: 90,
    align: 'right',
    render: (v: number) => (
      <span style={{ color: v >= 0 ? 'var(--color-down)' : 'var(--color-up)' }}>
        {v >= 0 ? '+' : ''}{v.toLocaleString()}
      </span>
    ),
  },
  {
    title: '盈亏%',
    dataIndex: 'pnl_pct',
    width: 80,
    align: 'right',
    render: (v: number) => (
      <Tag color={v >= 0 ? 'green' : 'red'} variant="filled" style={{ fontSize: 11, margin: 0 }}>
        {v >= 0 ? '+' : ''}{v.toFixed(2)}%
      </Tag>
    ),
  },
];

export default function PositionTable() {
  return (
    <Table
      columns={columns}
      dataSource={mockPositions}
      rowKey="ts_code"
      size="small"
      pagination={false}
    />
  );
}
