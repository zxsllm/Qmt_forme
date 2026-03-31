import { Table, Tag, Empty, Tabs, Button, Space, message, Alert, List, Badge, Spin } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useQuery, useMutation } from '@tanstack/react-query';
import { api, type SimOrder, type RiskAlert } from '../services/api';
import Panel from '../components/Panel';
import RiskPanel from '../components/RiskPanel';
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

const FORECAST_COLORS: Record<string, string> = {
  预增: 'red', 略增: 'volcano', 扭亏: 'blue', 续盈: 'cyan',
  预减: 'orange', 略减: 'gold', 首亏: 'magenta', 续亏: 'purple',
};

function RiskAlertPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ['risk-alerts'],
    queryFn: api.getRiskAlerts,
    staleTime: 60_000,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
  });

  if (isLoading) return <div style={{ textAlign: 'center', padding: 20 }}><Spin tip="加载预警..." /></div>;

  const alerts = data?.data ?? [];
  const summary = data?.summary ?? { st: 0, forecast: 0, cb_call: 0 };

  if (alerts.length === 0) {
    return (
      <Alert
        type="success"
        message="暂无风险预警"
        showIcon
        style={{ marginBottom: 12 }}
      />
    );
  }

  const stAlerts = alerts.filter((a) => a.type === 'ST预警');
  const fcAlerts = alerts.filter((a) => a.type === '业绩预告');
  const cbAlerts = alerts.filter((a) => a.type === '可转债强赎');

  const renderAlertItem = (item: RiskAlert) => {
    const levelColor = item.level === 'high' ? '#ff4d4f' : item.level === 'warning' ? '#faad14' : '#1677ff';
    return (
      <List.Item style={{ padding: '5px 0', borderBottom: '1px solid #1a2332' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', width: '100%' }}>
          <Badge color={levelColor} style={{ flexShrink: 0, marginTop: 4 }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', minWidth: 0 }}>
                <span style={{ color: '#e6f1fa', fontWeight: 500, fontSize: 13 }}>
                  {item.ts_code}
                </span>
                {item.name && <span style={{ color: '#93a9bc', fontSize: 12 }}>{item.name}</span>}
                {item.forecast_type && (
                  <Tag color={FORECAST_COLORS[item.forecast_type] ?? 'default'} style={{ fontSize: 11, lineHeight: '18px' }}>
                    {item.forecast_type}
                  </Tag>
                )}
              </div>
              {item.time && <span style={{ color: '#556677', fontSize: 11, flexShrink: 0, marginLeft: 8 }}>{item.time}</span>}
            </div>
            <div style={{ color: '#7a8ea0', fontSize: 12, marginTop: 2, wordBreak: 'break-all' }}>
              {item.detail}
            </div>
          </div>
        </div>
      </List.Item>
    );
  };

  const columnStyle: React.CSSProperties = {
    flex: '1 1 0',
    minWidth: 0,
    background: '#0d1626',
    borderRadius: 8,
    border: '1px solid #1a2332',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  };
  const headerBase: React.CSSProperties = {
    padding: '10px 14px',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    fontWeight: 600,
    fontSize: 14,
    borderBottom: '1px solid #1a2332',
    flexShrink: 0,
  };
  const listWrap: React.CSSProperties = {
    flex: 1,
    overflowY: 'auto',
    padding: '4px 12px',
    maxHeight: 'calc(100vh - 280px)',
    minHeight: 300,
  };

  return (
    <div style={{ marginBottom: 12 }}>
      <Alert
        type="warning"
        message={`共 ${alerts.length} 条风险预警 — ST ${summary.st} · 业绩预告 ${summary.forecast} · 可转债强赎 ${summary.cb_call}`}
        showIcon
        style={{ marginBottom: 10 }}
      />
      <div style={{ display: 'flex', gap: 12 }}>
        <div style={columnStyle}>
          <div style={{ ...headerBase, background: 'linear-gradient(90deg, rgba(255,77,79,0.15), transparent)', color: '#ff6b6b' }}>
            <Badge count={summary.st} overflowCount={99} style={{ backgroundColor: '#ff4d4f' }} />
            <span>ST预警</span>
          </div>
          <div style={listWrap}>
            <List dataSource={stAlerts} renderItem={renderAlertItem} locale={{ emptyText: '暂无' }} size="small" />
          </div>
        </div>

        <div style={columnStyle}>
          <div style={{ ...headerBase, background: 'linear-gradient(90deg, rgba(250,173,20,0.15), transparent)', color: '#faad14' }}>
            <Badge count={summary.forecast} overflowCount={99} style={{ backgroundColor: '#faad14' }} />
            <span>业绩预告</span>
          </div>
          <div style={listWrap}>
            <List dataSource={fcAlerts} renderItem={renderAlertItem} locale={{ emptyText: '暂无' }} size="small" />
          </div>
        </div>

        <div style={columnStyle}>
          <div style={{ ...headerBase, background: 'linear-gradient(90deg, rgba(22,119,255,0.15), transparent)', color: '#4096ff' }}>
            <Badge count={summary.cb_call} overflowCount={99} style={{ backgroundColor: '#1677ff' }} />
            <span>可转债强赎</span>
          </div>
          <div style={listWrap}>
            <List dataSource={cbAlerts} renderItem={renderAlertItem} locale={{ emptyText: '暂无' }} size="small" />
          </div>
        </div>
      </div>
    </div>
  );
}

function FeedStatusCard() {
  const { data: feed } = useQuery({
    queryKey: ['feed-status'],
    queryFn: api.getFeedStatus,
    refetchInterval: 5000,
  });

  const startMut = useMutation({
    mutationFn: api.startFeed,
    onSuccess: () => message.success('行情调度已启动'),
    onError: (e: Error) => message.error(e.message),
  });
  const stopMut = useMutation({
    mutationFn: api.stopFeed,
    onSuccess: () => message.success('行情调度已停止'),
    onError: (e: Error) => message.error(e.message),
  });

  return (
    <Panel title="行情调度器" className="w-80">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 12 }}>
        <div className="flex justify-between">
          <span style={{ color: '#93a9bc' }}>状态</span>
          <span style={{ color: feed?.running ? '#4ade80' : '#334155' }}>
            {feed?.running ? '运行中' : '已停止'}
          </span>
        </div>
        <div className="flex justify-between">
          <span style={{ color: '#93a9bc' }}>交易时段</span>
          <span style={{ color: feed?.trading_time ? '#4ade80' : '#334155' }}>
            {feed?.trading_time ? '是' : '否'}
          </span>
        </div>
        <div className="flex justify-between">
          <span style={{ color: '#93a9bc' }}>监控股票</span>
          <span style={{ color: '#e6f1fa' }}>{feed?.watch_codes ?? 0} 只</span>
        </div>
        <Space style={{ marginTop: 6 }}>
          <Button size="small" type="primary" onClick={() => startMut.mutate()} disabled={feed?.running} loading={startMut.isPending}>
            启动
          </Button>
          <Button size="small" danger onClick={() => stopMut.mutate()} disabled={!feed?.running} loading={stopMut.isPending}>
            停止
          </Button>
        </Space>
      </div>
    </Panel>
  );
}

export default function SystemPage() {
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
    <div className="flex flex-col h-full" style={{ padding: 18, gap: 12 }}>
      <Panel className="flex-1" noPadding>
        <Tabs
          defaultActiveKey="risk"
          style={{ height: '100%', padding: '0 10px' }}
          items={[
            {
              key: 'risk',
              label: '风控',
              children: (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <RiskAlertPanel />
                  <div className="flex" style={{ gap: 12, minHeight: 200 }}>
                    <RiskPanel className="flex-1" />
                    <FeedStatusCard />
                  </div>
                </div>
              ),
            },
            {
              key: 'history',
              label: '历史成交',
              children: (
                <Table
                  columns={historyColumns}
                  dataSource={data?.data ?? []}
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
    </div>
  );
}
