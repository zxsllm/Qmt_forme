import { useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Menu } from 'antd';
import {
  LineChartOutlined,
  FundOutlined,
  UnorderedListOutlined,
  HistoryOutlined,
  SafetyCertificateOutlined,
  ExperimentOutlined,
  DashboardOutlined,
} from '@ant-design/icons';
import SidebarNews from '../components/SidebarNews';

const menuItems = [
  { key: '/', icon: <DashboardOutlined />, label: '控制台' },
  { key: '/kline', icon: <LineChartOutlined />, label: 'K线图表' },
  { key: '/positions', icon: <FundOutlined />, label: '持仓' },
  { key: '/orders', icon: <UnorderedListOutlined />, label: '订单' },
  { key: '/history', icon: <HistoryOutlined />, label: '历史' },
  { key: '/risk', icon: <SafetyCertificateOutlined />, label: '风控' },
  { key: '/strategy', icon: <ExperimentOutlined />, label: '策略' },
  { key: '/backtest', icon: <HistoryOutlined />, label: '回测' },
];

export default function MainLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <div className="flex h-full">
      <div
        style={{
          width: collapsed ? 56 : 200,
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          background: 'linear-gradient(180deg, rgba(16,34,49,0.92), rgba(7,17,26,0.96))',
          borderRight: '1px solid rgba(148,186,215,0.12)',
          backdropFilter: 'blur(10px)',
          transition: 'width 200ms ease',
        }}
      >
        <div
          className="flex items-center gap-2 cursor-pointer shrink-0"
          style={{
            padding: collapsed ? '14px 16px' : '14px 20px',
            borderBottom: '1px solid rgba(148,186,215,0.10)',
          }}
          onClick={() => setCollapsed(!collapsed)}
        >
          <span style={{ color: '#6bc7ff', fontWeight: 700, fontSize: 16 }}>
            {collapsed ? 'AT' : 'AI Trade'}
          </span>
          {!collapsed && (
            <span style={{ color: '#334155', fontSize: 11, marginLeft: 'auto' }}>v0.2</span>
          )}
        </div>

        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          inlineCollapsed={collapsed}
          style={{ background: 'transparent', borderRight: 'none', flexShrink: 0, padding: '6px 0' }}
        />

        {!collapsed && (
          <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
            <SidebarNews />
          </div>
        )}
      </div>

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Outlet />
      </div>
    </div>
  );
}
