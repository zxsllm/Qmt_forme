import { Table, Tag, Empty } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useQuery } from '@tanstack/react-query';
import { api, type SimOrder } from '../services/api';
import Panel from '../components/Panel';

const columns: ColumnsType<SimOrder> = [
  {
    title: '时间', dataIndex: 'updated_at', width: 160,
    render: (v: string) => v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '',
  },
  { title: '代码', dataIndex: 'ts_code', width: 110 },
  {
    title: '方向', dataIndex: 'side', width: 70,
    render: (v: string) => (
      <Tag color={v === 'BUY' ? 'red' : 'green'} variant="filled">{v === 'BUY' ? '买入' : '卖出'}</Tag>
    ),
  },
  {
    title: '成交价', dataIndex: 'filled_price', width: 90, align: 'right',
    render: (v: number) => v > 0 ? v.toFixed(2) : '-',
  },
  { title: '成交量', dataIndex: 'filled_qty', width: 80, align: 'right' },
  {
    title: '手续费', dataIndex: 'fee', width: 80, align: 'right',
    render: (v: number) => v > 0 ? v.toFixed(2) : '-',
  },
  {
    title: '状态', dataIndex: 'status', width: 90,
    render: (v: string) => {
      const map: Record<string, { c: string; t: string }> = {
        FILLED: { c: 'green', t: '已成交' },
        CANCELED: { c: 'default', t: '已撤单' },
        REJECTED: { c: 'red', t: '已拒绝' },
      };
      const s = map[v] || { c: 'default', t: v };
      return <Tag color={s.c} variant="filled">{s.t}</Tag>;
    },
  },
];

export default function HistoryPage() {
  const { data } = useQuery({
    queryKey: ['orders', 'history'],
    queryFn: () => api.listOrders(),
    refetchInterval: 5000,
    select: (res) => ({
      ...res,
      data: res.data.filter((o) => ['FILLED', 'CANCELED', 'REJECTED'].includes(o.status)),
    }),
  });

  return (
    <div className="flex flex-col h-full bg-bg-base" style={{ padding: 16, gap: 10 }}>
      <Panel title="历史成交" className="flex-1" noPadding>
        <Table
          columns={columns}
          dataSource={data?.data ?? []}
          rowKey="order_id"
          size="small"
          pagination={{ pageSize: 50 }}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无历史记录" /> }}
        />
      </Panel>
    </div>
  );
}
