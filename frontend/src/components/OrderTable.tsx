import { Table, Tag, Button } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type SimOrder } from '../services/api';

const statusMap: Record<string, { color: string; text: string }> = {
  PENDING: { color: 'blue', text: '待成交' },
  SUBMITTED: { color: 'blue', text: '已提交' },
  PARTIAL_FILLED: { color: 'orange', text: '部分成交' },
  FILLED: { color: 'green', text: '已成交' },
  CANCELED: { color: 'default', text: '已撤单' },
  REJECTED: { color: 'red', text: '已拒绝' },
};

export default function OrderTable() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ['orders'],
    queryFn: () => api.listOrders(),
    refetchInterval: 3000,
  });

  const cancelMut = useMutation({
    mutationFn: (id: string) => api.cancelOrder(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['orders'] }),
  });

  const columns: ColumnsType<SimOrder> = [
    {
      title: '时间', dataIndex: 'created_at', width: 80,
      render: (v: string) => v ? new Date(v).toLocaleTimeString('zh-CN', { hour12: false }) : '',
    },
    { title: '代码', dataIndex: 'ts_code', width: 100 },
    {
      title: '方向', dataIndex: 'side', width: 60,
      render: (v: string) => (
        <Tag color={v === 'BUY' ? 'red' : 'green'} variant="filled" style={{ fontSize: 11, margin: 0 }}>
          {v === 'BUY' ? '买入' : '卖出'}
        </Tag>
      ),
    },
    {
      title: '价格', dataIndex: 'price', width: 80, align: 'right',
      render: (v: number | null) => v != null ? v.toFixed(2) : 'MKT',
    },
    { title: '委托', dataIndex: 'qty', width: 60, align: 'right' },
    { title: '成交', dataIndex: 'filled_qty', width: 60, align: 'right' },
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: (v: string) => {
        const s = statusMap[v] || { color: 'default', text: v };
        return <Tag color={s.color} variant="filled" style={{ fontSize: 11, margin: 0 }}>{s.text}</Tag>;
      },
    },
    {
      title: '操作', width: 60, align: 'center',
      render: (_: unknown, record: SimOrder) => {
        const canCancel = ['PENDING', 'SUBMITTED', 'PARTIAL_FILLED'].includes(record.status);
        return canCancel ? (
          <Button size="small" danger onClick={() => cancelMut.mutate(record.order_id)}
                  style={{ fontSize: 11, height: 22 }}>
            撤单
          </Button>
        ) : null;
      },
    },
  ];

  return (
    <Table
      columns={columns}
      dataSource={data?.data ?? []}
      rowKey="order_id"
      size="small"
      pagination={false}
    />
  );
}
