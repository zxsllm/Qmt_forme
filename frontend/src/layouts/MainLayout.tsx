import { useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Menu, Drawer, Tag, Badge } from 'antd';
import {
  SwapOutlined,
  ExperimentOutlined,
  SettingOutlined,
  NotificationOutlined,
  FireOutlined,
  BarChartOutlined,
  DashboardOutlined,
  AimOutlined,
  MonitorOutlined,
  CheckCircleOutlined,
  WarningOutlined,
  CloseCircleOutlined,
  SyncOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type DataHealthReport, type DataHealthCheck } from '../services/api';
import SidebarNews from '../components/SidebarNews';

const menuItems = [
  { key: '/command', icon: <AimOutlined />, label: '决策中枢' },
  { key: '/', icon: <DashboardOutlined />, label: '控制台' },
  { key: '/monitor', icon: <MonitorOutlined />, label: '盘中监控' },
  { key: '/trading', icon: <SwapOutlined />, label: '交易中心' },
  { key: '/strategy', icon: <ExperimentOutlined />, label: '策略研究' },
  { key: '/system', icon: <SettingOutlined />, label: '市场监控' },
  { key: '/news', icon: <NotificationOutlined />, label: '消息中心' },
  { key: '/sentiment', icon: <FireOutlined />, label: '情绪看板' },
  { key: '/fundamental', icon: <BarChartOutlined />, label: '基本面' },
];

const OVERALL_ICON: Record<string, React.ReactNode> = {
  healthy: <CheckCircleOutlined style={{ color: '#22c55e' }} />,
  warning: <WarningOutlined style={{ color: '#f59e0b' }} />,
  degraded: <WarningOutlined style={{ color: '#f97316' }} />,
  critical: <CloseCircleOutlined style={{ color: '#ef4444' }} />,
};
const OVERALL_COLOR: Record<string, string> = {
  healthy: '#22c55e', warning: '#f59e0b', degraded: '#f97316', critical: '#ef4444',
};
const OVERALL_LABEL: Record<string, string> = {
  healthy: '数据正常', warning: '部分滞后', degraded: '数据滞后', critical: '数据异常',
};
export const STATUS_TAG: Record<string, { color: string; text: string }> = {
  ok: { color: 'green', text: '正常' },
  stale: { color: 'orange', text: '滞后' },
  missing: { color: 'red', text: '缺失' },
  unknown: { color: 'default', text: '未知' },
};

const REASON_ICON: Record<string, React.ReactNode> = {
  syncing: <SyncOutlined spin style={{ color: '#3b82f6' }} />,
  repairing: <ToolOutlined spin style={{ color: '#8b5cf6' }} />,
  schema_mismatch: <CloseCircleOutlined style={{ color: '#ef4444' }} />,
  tushare_delay: <WarningOutlined style={{ color: '#f59e0b' }} />,
  not_synced: <WarningOutlined style={{ color: '#f97316' }} />,
};

const GROUP_ORDER = ['console', 'monitor', 'trading', 'strategy', 'system', 'news', 'sentiment', 'fundamental', 'infra'];

function GroupSummaryDot({ checks }: { checks: DataHealthCheck[] }) {
  const bad = checks.filter(c => c.status === 'stale' || c.status === 'missing').length;
  const syncing = checks.some(c => c.diagnosis?.reason === 'syncing' || c.diagnosis?.reason === 'repairing');
  const color = syncing ? '#3b82f6' : bad > 0 ? '#f97316' : '#22c55e';
  return (
    <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block', flexShrink: 0 }} />
  );
}

function CheckItem({ c }: { c: DataHealthCheck }) {
  const isStale = c.status === 'stale' || c.status === 'missing';
  const isSyncing = c.diagnosis?.reason === 'syncing' || c.diagnosis?.reason === 'repairing';
  return (
    <div style={{
      padding: '4px 6px', borderRadius: 4,
      background: isStale ? 'rgba(249,115,22,0.06)' : 'transparent',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{
          width: 5, height: 5, borderRadius: '50%', flexShrink: 0,
          background: isSyncing ? '#3b82f6' : isStale ? '#f97316' : '#22c55e',
        }} />
        <span style={{ color: '#c8d6e0', fontSize: 11, minWidth: 68 }}>{c.label}</span>
        <span style={{ color: '#6b7f8e', fontSize: 10, flex: 1 }}>{c.actual_date || '-'}</span>
        {isSyncing ? (
          <SyncOutlined spin style={{ color: '#3b82f6', fontSize: 10 }} />
        ) : isStale ? (
          <span style={{ color: '#f97316', fontSize: 10, fontWeight: 600 }}>
            {c.status === 'missing' ? '缺失' : '滞后'}
          </span>
        ) : null}
      </div>
      {isStale && c.diagnosis && (
        <div style={{ marginLeft: 11, marginTop: 2, fontSize: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 3, color: '#d4a574' }}>
            {REASON_ICON[c.diagnosis.reason] ?? <WarningOutlined style={{ color: '#f97316', fontSize: 10 }} />}
            <span>{c.diagnosis.detail}</span>
          </div>
          <div style={{ color: '#556575', marginTop: 1 }}>
            {c.diagnosis.repairable ? '→ 可自动修复' : `→ ${c.diagnosis.action}`}
          </div>
        </div>
      )}
    </div>
  );
}

function HealthDrawerContent({ report }: { report: DataHealthReport }) {
  const qc = useQueryClient();
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => {
    const stale = new Set<string>();
    for (const [g, cks] of Object.entries(report.groups)) {
      if (cks.some(c => c.status === 'stale' || c.status === 'missing')) stale.add(g);
    }
    return stale.size > 0 ? stale : new Set(['core']);
  });

  const toggleGroup = (g: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev);
      if (next.has(g)) next.delete(g); else next.add(g);
      return next;
    });
  };

  const allChecks = Object.values(report.groups).flat();
  const hasRepair = report.repair?.triggered || allChecks.some(c => c.diagnosis?.reason === 'repairing' || c.diagnosis?.reason === 'syncing');

  const totalOk = allChecks.filter(c => c.status === 'ok').length;
  const totalBad = allChecks.filter(c => c.status === 'stale' || c.status === 'missing').length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* Header */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <Tag color={OVERALL_COLOR[report.overall]} style={{ fontSize: 12, padding: '1px 8px' }}>
          {report.phase_label}
        </Tag>
        <span style={{ color: '#93a9bc', fontSize: 11 }}>
          {report.is_trade_date ? '交易日' : '非交易日'} | {report.today}
        </span>
        <span style={{ color: '#556575', fontSize: 11, marginLeft: 'auto' }}>
          <span style={{ color: '#22c55e' }}>{totalOk}</span>
          {totalBad > 0 && <> / <span style={{ color: '#f97316' }}>{totalBad}异常</span></>}
        </span>
        <span style={{ color: '#475569', fontSize: 11, cursor: 'pointer' }}
          onClick={() => qc.invalidateQueries({ queryKey: ['data-health'] })}>
          <SyncOutlined />
        </span>
        {hasRepair && (
          <Tag icon={<SyncOutlined spin />} color="processing" style={{ fontSize: 10 }}>修复中</Tag>
        )}
      </div>

      {report.repair?.triggered && (
        <div style={{ padding: '6px 8px', borderRadius: 5, background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.15)' }}>
          <div style={{ color: '#a78bfa', fontSize: 11, fontWeight: 600 }}>
            <ToolOutlined /> 自动修复: {report.repair.tables.join(', ')}
          </div>
          <div style={{ color: '#64748b', fontSize: 10, marginTop: 2 }}>
            日期 {report.repair.trade_date} · 约30秒后刷新
          </div>
        </div>
      )}

      {/* Groups */}
      {GROUP_ORDER.filter(g => report.groups[g]).map(g => {
        const checks = report.groups[g];
        const label = report.group_labels[g] || g;
        const expanded = expandedGroups.has(g);
        const badCount = checks.filter(c => c.status === 'stale' || c.status === 'missing').length;

        return (
          <div key={g} style={{ borderTop: '1px solid rgba(148,186,215,0.08)' }}>
            <div
              style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '7px 4px', cursor: 'pointer', userSelect: 'none',
              }}
              onClick={() => toggleGroup(g)}
            >
              <GroupSummaryDot checks={checks} />
              <span style={{ color: '#b8cfe0', fontSize: 12, fontWeight: 600, flex: 1 }}>{label}</span>
              {badCount > 0 && (
                <span style={{ color: '#f97316', fontSize: 10, fontWeight: 600 }}>{badCount}项异常</span>
              )}
              <span style={{ color: '#556575', fontSize: 10 }}>
                {checks.length}项 {expanded ? '▾' : '▸'}
              </span>
            </div>
            {expanded && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 1, paddingLeft: 4, paddingBottom: 4 }}>
                {checks.map(c => <CheckItem key={c.name} c={c} />)}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function MainLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const [healthOpen, setHealthOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const { data: healthReport, isLoading: healthLoading, isError: healthIsError, error: healthError, refetch: healthRefetch } = useQuery({
    queryKey: ['data-health'],
    queryFn: () => api.dataHealth(),
    refetchInterval: (query) => {
      const r = query.state.data as DataHealthReport | undefined;
      if (r?.repair?.triggered || r?.overall !== 'healthy') return 10_000;
      return 60_000;
    },
    staleTime: 8_000,
    retry: 2,
  });

  const overall = healthReport?.overall ?? 'healthy';
  const dotColor = OVERALL_COLOR[overall] ?? '#22c55e';

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
            <span style={{ color: '#334155', fontSize: 11, marginLeft: 'auto' }}>v0.3</span>
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

        <div
          className="flex items-center cursor-pointer shrink-0"
          style={{
            padding: collapsed ? '8px 16px' : '8px 14px',
            borderTop: '1px solid rgba(148,186,215,0.10)',
            gap: 8,
          }}
          onClick={() => setHealthOpen(true)}
        >
          <Badge dot color={dotColor} offset={[0, 0]}>
            <span style={{ width: 8 }} />
          </Badge>
          {!collapsed && (
            <span style={{ color: dotColor, fontSize: 11, whiteSpace: 'nowrap' }}>
              {healthReport?.phase_label ?? '...'} · {OVERALL_LABEL[overall] ?? '检查中'}
            </span>
          )}
        </div>
      </div>

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Outlet />
      </div>

      <Drawer
        title={
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {OVERALL_ICON[overall]}
            <span>数据健康检查</span>
          </span>
        }
        placement="left"
        width={380}
        open={healthOpen}
        onClose={() => setHealthOpen(false)}
        styles={{ body: { padding: '12px 16px' } }}
      >
        {healthReport ? (
          <HealthDrawerContent report={healthReport} />
        ) : healthIsError ? (
          <div style={{ padding: '32px 8px', textAlign: 'center' }}>
            <CloseCircleOutlined style={{ fontSize: 28, color: '#ef4444' }} />
            <div style={{ color: '#e6f1fa', fontSize: 13, marginTop: 12, fontWeight: 600 }}>
              健康接口请求失败
            </div>
            <div style={{ color: '#93a9bc', fontSize: 11, marginTop: 6, wordBreak: 'break-all' }}>
              {(healthError as Error)?.message ?? '未知错误'}
            </div>
            <div
              onClick={() => healthRefetch()}
              style={{
                display: 'inline-block', marginTop: 14, padding: '6px 14px',
                borderRadius: 14, cursor: 'pointer', fontSize: 12,
                background: 'linear-gradient(135deg, #2481bd, #3b61d6)', color: '#fff',
              }}
            >
              <SyncOutlined /> 重试
            </div>
          </div>
        ) : healthLoading ? (
          <div style={{ padding: '32px 8px', textAlign: 'center', color: '#93a9bc', fontSize: 12 }}>
            <SyncOutlined spin style={{ fontSize: 22, color: '#6bc7ff' }} />
            <div style={{ marginTop: 10 }}>正在拉取数据健康状态...</div>
          </div>
        ) : (
          <div style={{ padding: '32px 8px', textAlign: 'center', color: '#93a9bc', fontSize: 12 }}>
            <WarningOutlined style={{ fontSize: 22, color: '#f59e0b' }} />
            <div style={{ marginTop: 10 }}>暂无健康数据</div>
            <div
              onClick={() => healthRefetch()}
              style={{
                display: 'inline-block', marginTop: 12, padding: '6px 14px',
                borderRadius: 14, cursor: 'pointer', fontSize: 12,
                background: 'linear-gradient(135deg, #2f4354, #22303b)', color: '#e6f1fa',
              }}
            >
              <SyncOutlined /> 立即检查
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
