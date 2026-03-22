import { Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { mockTradePlans, type TradePlan } from '../services/mockData';

const columns: ColumnsType<TradePlan> = [
  { title: '代码', dataIndex: 'ts_code', width: 100 },
  { title: '名称', dataIndex: 'name', width: 80 },
  {
    title: '方向',
    dataIndex: 'direction',
    width: 60,
    render: (v: string) => (
      <Tag color={v === 'BUY' ? 'red' : 'green'} variant="filled" style={{ fontSize: 11, margin: 0 }}>
        {v === 'BUY' ? '买' : '卖'}
      </Tag>
    ),
  },
  { title: '目标价', dataIndex: 'target_price', width: 80, align: 'right', render: (v: number) => v.toFixed(2) },
  { title: '数量', dataIndex: 'qty', width: 60, align: 'right' },
  { title: '原因', dataIndex: 'reason', ellipsis: true },
  {
    title: '状态',
    dataIndex: 'status',
    width: 80,
    render: (v: string) => {
      const map: Record<string, { c: string; t: string }> = {
        waiting: { c: 'blue', t: '等待' },
        triggered: { c: 'orange', t: '触发' },
        done: { c: 'green', t: '完成' },
      };
      const s = map[v] || { c: 'default', t: v };
      return <Tag color={s.c} variant="filled" style={{ fontSize: 11, margin: 0 }}>{s.t}</Tag>;
    },
  },
];

export default function TradePlanTable() {
  return (
    <Table
      columns={columns}
      dataSource={mockTradePlans}
      rowKey="ts_code"
      size="small"
      pagination={false}
    />
  );
}
