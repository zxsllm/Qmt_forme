import { useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Layout, Menu } from 'antd';
import {
  LineChartOutlined,
  FundOutlined,
  UnorderedListOutlined,
  HistoryOutlined,
  SafetyCertificateOutlined,
  ExperimentOutlined,
  DashboardOutlined,
} from '@ant-design/icons';

const { Sider } = Layout;

const menuItems = [
  { key: '/', icon: <DashboardOutlined />, label: '控制台' },
  { key: '/kline', icon: <LineChartOutlined />, label: 'K线图表' },
  { key: '/positions', icon: <FundOutlined />, label: '持仓' },
  { key: '/orders', icon: <UnorderedListOutlined />, label: '订单' },
  { key: '/history', icon: <HistoryOutlined />, label: '历史' },
  { key: '/risk', icon: <SafetyCertificateOutlined />, label: '风控' },
  { key: '/strategy', icon: <ExperimentOutlined />, label: '策略' },
];

export default function MainLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <div className="flex h-full bg-bg-base">
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="dark"
        width={160}
        collapsedWidth={56}
        trigger={null}
        style={{ background: 'var(--color-bg-base)', borderRight: '1px solid var(--color-edge)' }}
      >
        <div
          className="flex items-center gap-2 cursor-pointer border-b border-edge"
          style={{ padding: '12px 20px' }}
          onClick={() => setCollapsed(!collapsed)}
        >
          <span className="text-accent font-bold text-[16px]">
            {collapsed ? 'AT' : 'AI Trade'}
          </span>
          {!collapsed && <span className="text-t4 text-[11px] ml-auto">v0.1</span>}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ background: 'transparent', borderRight: 'none' }}
        />
      </Sider>

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Outlet />
      </div>
    </div>
  );
}
