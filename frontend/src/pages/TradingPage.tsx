import { useState } from 'react';
import { Tabs, Button, Radio, Space } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import Panel from '../components/Panel';
import AccountCard from '../components/AccountCard';
import PositionTable from '../components/PositionTable';
import OrderTable from '../components/OrderTable';
import OrderSubmitForm from '../components/OrderSubmitForm';

export default function TradingPage() {
  const [showForm, setShowForm] = useState(false);
  const [filter, setFilter] = useState<string>('all');
  void filter;

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
          ]}
        />
      </Panel>
      <OrderSubmitForm open={showForm} onClose={() => setShowForm(false)} />
    </div>
  );
}
