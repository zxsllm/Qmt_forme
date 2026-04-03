import { useState } from 'react';
import { Tabs, Button, Radio, Space, Table, Tag, Empty } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { api, type SimOrder } from '../services/api';
import Panel from '../components/Panel';
import AccountCard from '../components/AccountCard';
import PositionTable from '../components/PositionTable';
import OrderTable from '../components/OrderTable';
import OrderSubmitForm from '../components/OrderSubmitForm';
import LogPanel from '../components/LogPanel';

const historyColumns: ColumnsType<SimOrder> = [
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

export default function TradingPage() {
  const [showForm, setShowForm] = useState(false);
  const [filter, setFilter] = useState<string>('all');
  void filter;

  const { data: historyData } = useQuery({
    queryKey: ['orders', 'history'],
    queryFn: () => api.listOrders(),
    refetchInterval: 5000,
    select: (res) => ({
      ...res,
      data: res.data.filter((o) => ['FILLED', 'CANCELED', 'REJECTED'].includes(o.status)),
    }),
  });

  return (
    <div className="flex flex-col h-full" style={{ padding: 18, gap: 12 }}>
      <AccountCard />
      <Panel className="flex-1" noPadding>
        <Tabs
          defaultActiveKey="positions"
          style={{ height: '100%', padding: '0 10px' }}
          tabBarExtraContent={
            <Button
              type="primary"
              size="small"
              icon={<PlusOutlined />}
              onClick={() => setShowForm(true)}
              style={{ marginRight: 8 }}
            >
              新建订单
            </Button>
          }
          items={[
            {
              key: 'positions',
              label: '持仓',
              children: <PositionTable />,
            },
            {
              key: 'orders',
              label: '活跃订单',
              children: (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <Space>
                    <Radio.Group
                      value={filter}
                      onChange={(e) => setFilter(e.target.value)}
                      buttonStyle="solid"
                      size="small"
                    >
                      <Radio.Button value="all">全部</Radio.Button>
                      <Radio.Button value="active">活跃</Radio.Button>
                      <Radio.Button value="filled">已成交</Radio.Button>
                      <Radio.Button value="canceled">已撤/拒</Radio.Button>
                    </Radio.Group>
                  </Space>
                  <OrderTable />
                </div>
              ),
            },
            {
              key: 'history',
              label: '历史成交',
              children: (
                <Table
                  columns={historyColumns}
                  dataSource={historyData?.data ?? []}
                  rowKey="order_id"
                  size="small"
                  pagination={{ pageSize: 50 }}
                  locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无历史记录" /> }}
                />
              ),
            },
            {
              key: 'audit',
              label: '审计日志',
              children: <LogPanel style={{ height: '100%' }} />,
            },
          ]}
        />
      </Panel>
      <OrderSubmitForm open={showForm} onClose={() => setShowForm(false)} />
    </div>
  );
}
