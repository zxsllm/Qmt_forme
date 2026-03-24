import { useState } from 'react';
import { Button, Radio, Space } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import Panel from '../components/Panel';
import OrderTable from '../components/OrderTable';
import OrderSubmitForm from '../components/OrderSubmitForm';

export default function OrdersPage() {
  const [showForm, setShowForm] = useState(false);
  const [filter, setFilter] = useState<string>('all');
  void filter;

  return (
    <div className="flex flex-col h-full" style={{ padding: 18, gap: 12 }}>
      <div className="flex items-center justify-between">
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
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setShowForm(true)}>
          新建订单
        </Button>
      </div>
      <Panel className="flex-1" noPadding>
        <OrderTable />
      </Panel>
      <OrderSubmitForm open={showForm} onClose={() => setShowForm(false)} />
    </div>
  );
}
