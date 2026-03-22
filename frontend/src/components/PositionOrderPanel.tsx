import { Tabs } from 'antd';
import Panel from './Panel';
import PositionTable from './PositionTable';
import OrderTable from './OrderTable';

export default function PositionOrderPanel({ className = '' }: { className?: string }) {
  return (
    <Panel className={className} noPadding>
      <Tabs
        size="small"
        defaultActiveKey="positions"
        tabBarStyle={{ margin: '0 16px', height: 36 }}
        items={[
          { key: 'positions', label: '持仓', children: <PositionTable /> },
          { key: 'orders', label: '委托', children: <OrderTable /> },
        ]}
      />
    </Panel>
  );
}
