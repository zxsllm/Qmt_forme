import { useState } from 'react';
import { Table, Tag, Button, Empty } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useQuery } from '@tanstack/react-query';
import { api, type SimOrder } from '../services/api';
import OrderSubmitForm from './OrderSubmitForm';

const statusMap: Record<string, { color: string; text: string }> = {
  PENDING: { color: 'blue', text: '待成交' },
  SUBMITTED: { color: 'blue', text: '已提交' },
  PARTIAL_FILLED: { color: 'orange', text: '部分成交' },
};

const columns: ColumnsType<SimOrder> = [
  { title: '代码', dataIndex: 'ts_code', width: 100 },
  {
    title: '方向', dataIndex: 'side', width: 50,
    render: (v: string) => (
      <Tag color={v === 'BUY' ? 'red' : 'green'} variant="filled" style={{ fontSize: 11, margin: 0 }}>
        {v === 'BUY' ? '买' : '卖'}
      </Tag>
    ),
  },
  {
    title: '价格', dataIndex: 'price', width: 70, align: 'right',
    render: (v: number | null) => v != null ? v.toFixed(2) : 'MKT',
  },
  { title: '数量', dataIndex: 'qty', width: 60, align: 'right' },
  { title: '原因', dataIndex: 'reason', ellipsis: true, render: (v: string) => v || '-' },
  {
    title: '状态', dataIndex: 'status', width: 80,
    render: (v: string) => {
      const s = statusMap[v] || { color: 'default', text: v };
      return <Tag color={s.color} variant="filled" style={{ fontSize: 11, margin: 0 }}>{s.text}</Tag>;
    },
  },
];

export default function TradePlanTable() {
  const [showForm, setShowForm] = useState(false);

  const { data } = useQuery({
    queryKey: ['orders', 'active'],
    queryFn: () => api.listOrders(),
    refetchInterval: 3000,
    select: (res) => ({
      ...res,
      data: res.data.filter((o) =>
        ['PENDING', 'SUBMITTED', 'PARTIAL_FILLED'].includes(o.status),
      ),
    }),
  });

  return (
    <div className="flex flex-col h-full">
      <div style={{ padding: '6px 12px 4px', textAlign: 'right' }}>
        <Button
          type="primary"
          size="small"
          icon={<PlusOutlined />}
          onClick={() => setShowForm(true)}
          style={{ fontSize: 12 }}
        >
          新建订单
        </Button>
      </div>
      <Table
        columns={columns}
        dataSource={data?.data ?? []}
        rowKey="order_id"
        size="small"
        pagination={false}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无活跃订单" /> }}
      />
      <OrderSubmitForm open={showForm} onClose={() => setShowForm(false)} />
    </div>
  );
}
