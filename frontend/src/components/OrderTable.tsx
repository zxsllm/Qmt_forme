import { Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { mockOrders, type Order } from '../services/mockData';

const statusMap: Record<string, { color: string; text: string }> = {
  pending: { color: 'blue', text: '待成交' },
  partial: { color: 'orange', text: '部分成交' },
  filled: { color: 'green', text: '已成交' },
  canceled: { color: 'default', text: '已撤单' },
};

const columns: ColumnsType<Order> = [
  { title: '时间', dataIndex: 'time', width: 80 },
  { title: '代码', dataIndex: 'ts_code', width: 100 },
  { title: '名称', dataIndex: 'name', width: 80 },
  {
    title: '方向',
    dataIndex: 'direction',
    width: 60,
    render: (v: string) => (
      <Tag color={v === 'BUY' ? 'red' : 'green'} variant="filled" style={{ fontSize: 11, margin: 0 }}>
        {v === 'BUY' ? '买入' : '卖出'}
      </Tag>
    ),
  },
  { title: '价格', dataIndex: 'price', width: 80, align: 'right', render: (v: number) => v.toFixed(2) },
  { title: '委托', dataIndex: 'qty', width: 60, align: 'right' },
  { title: '成交', dataIndex: 'filled', width: 60, align: 'right' },
  {
    title: '状态',
    dataIndex: 'status',
    width: 90,
    render: (v: string) => {
      const s = statusMap[v] || { color: 'default', text: v };
      return <Tag color={s.color} variant="filled" style={{ fontSize: 11, margin: 0 }}>{s.text}</Tag>;
    },
  },
];

export default function OrderTable() {
  return (
    <Table
      columns={columns}
      dataSource={mockOrders}
      rowKey="id"
      size="small"
      pagination={false}
    />
  );
}
