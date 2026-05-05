import { useState, useMemo } from 'react';
import { Table, Tag, Tabs, Button, Space, message, Alert, List, Badge, Spin, Radio, Statistic, Row, Col, Card, Input } from 'antd';
import { useQuery, useMutation } from '@tanstack/react-query';
import { api, type RiskAlert, type StPredictItem } from '../services/api';
import Panel from '../components/Panel';
import RiskPanel from '../components/RiskPanel';

const FORECAST_COLORS: Record<string, string> = {
  预增: 'red', 略增: 'volcano', 扭亏: 'blue', 续盈: 'cyan',
  预减: 'green', 略减: 'green', 首亏: 'geekblue', 续亏: 'purple',
};

// Badge 需要实际 hex 值（Ant Design 命名色 → CSS 色值）
const BADGE_HEX: Record<string, string> = {
  red: '#ff4d4f', volcano: '#ff7a45', blue: '#1677ff', cyan: '#13c2c2',
  green: '#52c41a', geekblue: '#2f54eb', purple: '#722ed1',
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
    return <Alert type="success" message="暂无风险预警" showIcon style={{ marginBottom: 12 }} />;
  }

  const stAlerts = alerts.filter((a) => a.type === 'ST预警');
  const fcAlerts = alerts.filter((a) => a.type === '业绩预告');
  const cbAlerts = alerts.filter((a) => a.type === '可转债强赎');

  const renderAlertItem = (item: RiskAlert) => {
    const fcKey = FORECAST_COLORS[item.forecast_type ?? ''];
    const dotColor = fcKey ? (BADGE_HEX[fcKey] ?? fcKey) : item.level === 'high' ? '#ff4d4f' : item.level === 'warning' ? '#faad14' : '#1677ff';
    return (
      <List.Item style={{ padding: '5px 0', borderBottom: '1px solid #1a2332' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', width: '100%' }}>
          <Badge color={dotColor} style={{ flexShrink: 0, marginTop: 4 }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', minWidth: 0 }}>
                <span style={{ color: '#e6f1fa', fontWeight: 500, fontSize: 13 }}>{item.ts_code}</span>
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
              {item.ann_url && (() => {
                const lt = item.link_type;
                const label = lt === 'forecast' ? '查看预告'
                  : lt === 'report' ? '年报披露'
                  : lt === 'fallback' ? '公告主页'
                  : '查看公告';
                const color = lt === 'report' ? '#ffbf75'
                  : lt === 'fallback' ? '#93a9bc'
                  : '#6bc7ff';
                return (
                  <a href={item.ann_url} target="_blank" rel="noreferrer"
                    style={{ color, marginLeft: 6, fontSize: 11 }}>
                    {label}
                  </a>
                );
              })()}
            </div>
          </div>
        </div>
      </List.Item>
    );
  };

  const columnStyle: React.CSSProperties = {
    flex: '1 1 0', minWidth: 0, background: '#0d1626', borderRadius: 8,
    border: '1px solid #1a2332', display: 'flex', flexDirection: 'column', overflow: 'hidden',
  };
  const headerBase: React.CSSProperties = {
    padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 8,
    fontWeight: 600, fontSize: 14, borderBottom: '1px solid #1a2332', flexShrink: 0,
  };
  const listWrap: React.CSSProperties = {
    flex: 1, overflowY: 'auto', padding: '4px 12px', maxHeight: 'calc(100vh - 280px)', minHeight: 300,
  };

  return (
    <div style={{ marginBottom: 12 }}>
      <Alert
        type="warning"
        message={`共 ${alerts.length} 条风险预警 — ST ${summary.st} · 业绩预告 ${summary.forecast} · 可转债强赎 ${summary.cb_call}`}
        showIcon style={{ marginBottom: 10 }}
      />
      <div style={{ display: 'flex', gap: 12 }}>
        <div style={columnStyle}>
          <div style={{ ...headerBase, background: 'linear-gradient(90deg, rgba(255,77,79,0.15), transparent)', color: '#ff6b6b' }}>
            <Badge count={summary.st} overflowCount={99} style={{ backgroundColor: '#ff4d4f' }} />
            <span>ST预警</span>
          </div>
          <div style={listWrap}><List dataSource={stAlerts} renderItem={renderAlertItem} locale={{ emptyText: '暂无' }} size="small" /></div>
        </div>
        <div style={columnStyle}>
          <div style={{ ...headerBase, background: 'linear-gradient(90deg, rgba(250,173,20,0.15), transparent)', color: '#faad14' }}>
            <Badge count={summary.forecast} overflowCount={99} style={{ backgroundColor: '#faad14' }} />
            <span>业绩预告</span>
          </div>
          <div style={listWrap}><List dataSource={fcAlerts} renderItem={renderAlertItem} locale={{ emptyText: '暂无' }} size="small" /></div>
        </div>
        <div style={columnStyle}>
          <div style={{ ...headerBase, background: 'linear-gradient(90deg, rgba(22,119,255,0.15), transparent)', color: '#4096ff' }}>
            <Badge count={summary.cb_call} overflowCount={99} style={{ backgroundColor: '#1677ff' }} />
            <span>可转债强赎</span>
          </div>
          <div style={listWrap}><List dataSource={cbAlerts} renderItem={renderAlertItem} locale={{ emptyText: '暂无' }} size="small" /></div>
        </div>
      </div>
    </div>
  );
}

function FeedStatusCard() {
  const { data: feed } = useQuery({ queryKey: ['feed-status'], queryFn: api.getFeedStatus, refetchInterval: 5000 });
  const startMut = useMutation({ mutationFn: api.startFeed, onSuccess: () => message.success('行情调度已启动'), onError: (e: Error) => message.error(e.message) });
  const stopMut = useMutation({ mutationFn: api.stopFeed, onSuccess: () => message.success('行情调度已停止'), onError: (e: Error) => message.error(e.message) });

  return (
    <Panel title="行情调度器" className="w-80">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 12 }}>
        <div className="flex justify-between">
          <span style={{ color: '#93a9bc' }}>状态</span>
          <span style={{ color: feed?.running ? '#4ade80' : '#334155' }}>{feed?.running ? '运行中' : '已停止'}</span>
        </div>
        <div className="flex justify-between">
          <span style={{ color: '#93a9bc' }}>交易时段</span>
          <span style={{ color: feed?.trading_time ? '#4ade80' : '#334155' }}>{feed?.trading_time ? '是' : '否'}</span>
        </div>
        <div className="flex justify-between">
          <span style={{ color: '#93a9bc' }}>监控股票</span>
          <span style={{ color: '#e6f1fa' }}>{feed?.watch_codes ?? 0} 只</span>
        </div>
        <Space style={{ marginTop: 6 }}>
          <Button size="small" type="primary" onClick={() => startMut.mutate()} disabled={feed?.running} loading={startMut.isPending}>启动</Button>
          <Button size="small" danger onClick={() => stopMut.mutate()} disabled={!feed?.running} loading={stopMut.isPending}>停止</Button>
        </Space>
      </div>
    </Panel>
  );
}

function fmtWan(v: number | null): string {
  if (v == null) return '-';
  const abs = Math.abs(v);
  if (abs >= 1e8) return `${(v / 1e8).toFixed(1)}亿`;
  return `${(v / 1e4).toFixed(0)}万`;
}

function fmtDate(d: string | null): string {
  if (!d || d.length !== 8) return '-';
  return `${d.slice(4, 6)}-${d.slice(6)}`;
}

function daysUntil(d: string | null): number | null {
  if (!d || d.length !== 8) return null;
  const target = new Date(`${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}`);
  const diff = Math.ceil((target.getTime() - Date.now()) / 86400000);
  return diff;
}

function StPredictTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['st-predict'],
    queryFn: api.getStPredict,
    staleTime: 600_000,
  });

  const [search, setSearch] = useState('');
  const items = data?.data ?? [];

  const filtered = useMemo(() => {
    if (!search.trim()) return items;
    const q = search.trim().toLowerCase();
    return items.filter(i => i.ts_code.toLowerCase().includes(q) || (i.name || '').toLowerCase().includes(q));
  }, [items, search]);

  const columns = [
    { title: '代码', dataIndex: 'ts_code', width: 95, render: (v: string) => <span style={{ color: '#e6f1fa', fontWeight: 500 }}>{v}</span> },
    { title: '名称', dataIndex: 'name', width: 85, ellipsis: true, render: (v: string) => <span style={{ color: '#93a9bc' }}>{v}</span> },
    {
      title: '利润(万)', dataIndex: 'profit', width: 100, align: 'right' as const,
      sorter: (a: StPredictItem, b: StPredictItem) => (a.profit ?? 0) - (b.profit ?? 0),
      render: (v: number | null) => <span style={{ color: '#ff6f91' }}>{fmtWan(v)}</span>,
    },
    {
      title: '预告利润', key: 'fc_profit', width: 130, align: 'right' as const,
      sorter: (a: StPredictItem, b: StPredictItem) => (a.net_profit_min ?? 0) - (b.net_profit_min ?? 0),
      render: (_: unknown, r: StPredictItem) => {
        if (!r.net_profit_min && !r.net_profit_max) return '-';
        return <span style={{ color: '#ff6f91', fontSize: 12 }}>{fmtWan(r.net_profit_min)} ~ {fmtWan(r.net_profit_max)}</span>;
      },
    },
    {
      title: '年报披露', dataIndex: 'disclosure_date', width: 85, align: 'center' as const,
      sorter: (a: StPredictItem, b: StPredictItem) => (a.disclosure_date || '').localeCompare(b.disclosure_date || ''),
      render: (v: string) => <span style={{ color: '#93a9bc' }}>{fmtDate(v)}</span>,
    },
    {
      title: '预计ST日', dataIndex: 'predicted_st_date', width: 85, align: 'center' as const,
      defaultSortOrder: 'ascend' as const,
      sorter: (a: StPredictItem, b: StPredictItem) => (a.predicted_st_date || 'z').localeCompare(b.predicted_st_date || 'z'),
      render: (v: string | null) => <span style={{ color: '#ffbf75', fontWeight: 600 }}>{fmtDate(v)}</span>,
    },
    {
      title: '倒计时', key: 'countdown', width: 75, align: 'center' as const,
      render: (_: unknown, r: StPredictItem) => {
        const d = daysUntil(r.predicted_st_date);
        if (d == null) return '-';
        if (d <= 0) return <Tag color="red" style={{ margin: 0 }}>已到期</Tag>;
        if (d <= 7) return <Tag color="volcano" style={{ margin: 0 }}>{d}天</Tag>;
        return <span style={{ color: '#93a9bc' }}>{d}天</span>;
      },
    },
    {
      title: '风险公告', dataIndex: 'warn_count', width: 75, align: 'center' as const,
      sorter: (a: StPredictItem, b: StPredictItem) => (a.warn_count ?? 0) - (b.warn_count ?? 0),
      render: (v: number) => v > 0
        ? <Tag color={v >= 3 ? 'red' : 'orange'} style={{ margin: 0 }}>{v}次</Tag>
        : <span style={{ color: '#556677' }}>-</span>,
    },
    {
      title: '方式', dataIndex: 'predict_method', width: 95, align: 'center' as const,
      filters: [
        { text: '公告确认', value: '公告确认' },
        { text: '公告风险提示', value: '公告风险提示' },
        { text: '年报财务', value: '年报财务' },
        { text: '预告推算', value: '预告推算' },
      ],
      onFilter: (value: boolean | React.Key, record: StPredictItem) => record.predict_method === value,
      render: (v: string | undefined) => {
        const color = v === '公告确认' ? 'red' : v === '公告风险提示' ? 'orange' : v === '年报财务' ? 'blue' : 'purple';
        return v ? <Tag color={color} style={{ margin: 0 }}>{v}</Tag> : '-';
      },
    },
    {
      title: '预测理由', dataIndex: 'reason', width: 390, ellipsis: { showTitle: true },
      render: (v: string, r: StPredictItem) => (
        <span style={{ color: '#93a9bc', fontSize: 12 }}>
          {v || '-'}
          {r.ann_url && (
            <a href={r.ann_url} target="_blank" rel="noreferrer"
              style={{ color: '#6bc7ff', marginLeft: 6, fontSize: 11 }}>
              查看公告
            </a>
          )}
        </span>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 14, alignItems: 'center' }}>
        <Tag color="volcano" style={{ fontSize: 13, padding: '2px 12px', borderRadius: 999 }}>
          {data?.count ?? 0} 只待ST
        </Tag>
        <span style={{ color: '#556677', fontSize: 12 }}>基于{data?.report_year ?? ''}年报/预告 · 规则: 利润孰低为负+营收不达标 / 净资产为负 (沪深9.3.2/创业板10.3.1/科创板12.4.2)</span>
        <div style={{ flex: 1 }} />
        <Input.Search size="small" placeholder="搜索代码/名称" allowClear
          style={{ width: 180 }}
          onSearch={setSearch} onChange={e => !e.target.value && setSearch('')}
        />
      </div>
      <Table<StPredictItem>
        dataSource={filtered}
        columns={columns}
        rowKey="ts_code"
        size="small"
        loading={isLoading}
        pagination={{ pageSize: 25, size: 'small', showSizeChanger: true, pageSizeOptions: ['25', '50', '100'] }}
        scroll={{ y: 'calc(100vh - 300px)' }}
      />
    </div>
  );
}

const CARD_S: React.CSSProperties = { background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(148,186,215,0.08)', borderRadius: 14 };

function MarginTab() {
  const [days, setDays] = useState(30);
  const { data, isLoading } = useQuery({
    queryKey: ['margin-market', days],
    queryFn: () => api.getMargin('', '', days),
    staleTime: 300_000,
  });

  const agg = (() => {
    if (!data?.data?.length) return [];
    const byDate = new Map<string, { trade_date: string; rzye: number; rqye: number; rzrqye: number; cnt: number }>();
    for (const r of data.data) {
      const d = r.trade_date as string;
      if (!byDate.has(d)) byDate.set(d, { trade_date: d, rzye: 0, rqye: 0, rzrqye: 0, cnt: 0 });
      const a = byDate.get(d)!;
      a.rzye += (r.rzye as number) || 0;
      a.rqye += (r.rqye as number) || 0;
      a.rzrqye += (r.rzrqye as number) || 0;
      a.cnt++;
    }
    return Array.from(byDate.values()).sort((a, b) => b.trade_date.localeCompare(a.trade_date));
  })();

  const latest = agg[0];
  const prev = agg[1];
  const rzChg = latest && prev ? latest.rzye - prev.rzye : 0;

  return (
    <div>
      <div className="flex items-center gap-2" style={{ marginBottom: 10 }}>
        <span style={{ color: '#93a9bc', fontSize: 13 }}>融资融券</span>
        <Radio.Group size="small" value={days} onChange={e => setDays(e.target.value)}>
          <Radio.Button value={7}>7天</Radio.Button>
          <Radio.Button value={30}>30天</Radio.Button>
          <Radio.Button value={90}>90天</Radio.Button>
        </Radio.Group>
      </div>
      {latest && (
        <Row gutter={12} style={{ marginBottom: 12 }}>
          <Col span={6}><Card size="small" style={CARD_S}><Statistic title="融资余额" value={(latest.rzye / 1e8).toFixed(0)} suffix="亿" valueStyle={{ fontSize: 20 }} /></Card></Col>
          <Col span={6}><Card size="small" style={CARD_S}><Statistic title="融券余额" value={(latest.rqye / 1e8).toFixed(0)} suffix="亿" valueStyle={{ fontSize: 20 }} /></Card></Col>
          <Col span={6}><Card size="small" style={CARD_S}><Statistic title="两融合计" value={(latest.rzrqye / 1e8).toFixed(0)} suffix="亿" valueStyle={{ fontSize: 20 }} /></Card></Col>
          <Col span={6}><Card size="small" style={CARD_S}><Statistic title="融资日变动" value={(rzChg / 1e8).toFixed(1)} suffix="亿"
            valueStyle={{ fontSize: 20, color: rzChg >= 0 ? '#ff6f91' : '#4ade80' }} /></Card></Col>
        </Row>
      )}
      <Table dataSource={agg} rowKey="trade_date" size="small" loading={isLoading}
        pagination={{ pageSize: 15, size: 'small' }}
        columns={[
          { title: '日期', dataIndex: 'trade_date', width: 90 },
          { title: '融资余额(亿)', dataIndex: 'rzye', width: 110, align: 'right', render: (v: number) => (v / 1e8).toFixed(2) },
          { title: '融券余额(亿)', dataIndex: 'rqye', width: 110, align: 'right', render: (v: number) => (v / 1e8).toFixed(2) },
          { title: '两融余额(亿)', dataIndex: 'rzrqye', width: 130, align: 'right', render: (v: number) => (v / 1e8).toFixed(2) },
          { title: '标的数', dataIndex: 'cnt', width: 70, align: 'right' },
        ]}
      />
    </div>
  );
}

export default function SystemPage() {
  return (
    <div className="flex flex-col h-full" style={{ padding: 18, gap: 12 }}>
      <Panel className="flex-1" noPadding>
        <Tabs
          defaultActiveKey="risk"
          style={{ height: '100%', padding: '0 10px' }}
          items={[
            {
              key: 'risk',
              label: '风控预警',
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
            { key: 'st-predict', label: 'ST预测', children: <StPredictTab /> },
            { key: 'margin', label: '融资融券', children: <MarginTab /> },
          ]}
        />
      </Panel>
    </div>
  );
}
