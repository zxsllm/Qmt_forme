import { useState } from 'react';
import { Table, Tag, Tabs, Card, Statistic, Row, Col, Empty } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useQuery } from '@tanstack/react-query';
import { api, type LimitBoardItem, type LimitStepItem, type DragonTigerItem, type HotListItem } from '../services/api';
import Panel from '../components/Panel';

function isLimitUp(t: string) { return t === 'U' || t.includes('涨停'); }
function isLimitDown(t: string) { return t === 'D' || t.includes('跌停'); }
function isBroken(t: string) { return t === 'Z' || t.includes('炸板'); }

function LimitSummaryCards({ data }: { data: LimitBoardItem[] }) {
  const upCount = data.filter(d => isLimitUp(d.limit_type)).length;
  const downCount = data.filter(d => isLimitDown(d.limit_type)).length;
  const brokenCount = data.filter(d => isBroken(d.limit_type)).length;
  const sealRate = upCount > 0 ? ((upCount / (upCount + brokenCount)) * 100).toFixed(1) : '0';

  return (
    <Row gutter={12} style={{ marginBottom: 12 }}>
      <Col span={6}>
        <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(148,186,215,0.12)' }}>
          <Statistic title="涨停" value={upCount} valueStyle={{ color: '#ef4444', fontSize: 22 }} suffix="家" />
        </Card>
      </Col>
      <Col span={6}>
        <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(148,186,215,0.12)' }}>
          <Statistic title="跌停" value={downCount} valueStyle={{ color: '#22c55e', fontSize: 22 }} suffix="家" />
        </Card>
      </Col>
      <Col span={6}>
        <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(148,186,215,0.12)' }}>
          <Statistic title="炸板" value={brokenCount} valueStyle={{ color: '#f59e0b', fontSize: 22 }} suffix="家" />
        </Card>
      </Col>
      <Col span={6}>
        <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(148,186,215,0.12)' }}>
          <Statistic title="封板率" value={sealRate} valueStyle={{ color: '#6bc7ff', fontSize: 22 }} suffix="%" />
        </Card>
      </Col>
    </Row>
  );
}

const limitBoardColumns: ColumnsType<LimitBoardItem> = [
  { title: '代码', dataIndex: 'ts_code', width: 100 },
  { title: '名称', dataIndex: 'name', width: 90 },
  {
    title: '类型', dataIndex: 'limit_type', width: 60,
    render: (v: string) => {
      const m: Record<string, { t: string; c: string }> = {
        U: { t: '涨停', c: 'red' }, D: { t: '跌停', c: 'green' }, Z: { t: '炸板', c: 'orange' },
        '涨停板': { t: '涨停', c: 'red' }, '跌停板': { t: '跌停', c: 'green' }, '炸板股': { t: '炸板', c: 'orange' },
      };
      const s = m[v] || { t: v, c: 'default' };
      return <Tag color={s.c}>{s.t}</Tag>;
    },
  },
  {
    title: '涨跌幅', dataIndex: 'pct_chg', width: 80, align: 'right',
    render: (v: number | null) => v != null
      ? <span style={{ color: v >= 0 ? '#ef4444' : '#22c55e' }}>{v.toFixed(2)}%</span>
      : '-',
  },
  {
    title: '封单(万)', dataIndex: 'limit_amount', width: 90, align: 'right',
    render: (v: number | null) => v != null ? (v / 10000).toFixed(0) : '-',
  },
  {
    title: '换手率', dataIndex: 'turnover_rate', width: 70, align: 'right',
    render: (v: number | null) => v != null ? `${v.toFixed(1)}%` : '-',
  },
  { title: '标签', dataIndex: 'tag', width: 70 },
  { title: '状态', dataIndex: 'status', width: 70 },
  { title: '开板次', dataIndex: 'open_num', width: 60, align: 'center' },
  { title: '首封', dataIndex: 'first_lu_time', width: 100, ellipsis: true },
  { title: '末封', dataIndex: 'last_lu_time', width: 100, ellipsis: true },
];

const limitStepColumns: ColumnsType<LimitStepItem> = [
  {
    title: '连板', dataIndex: 'nums', width: 60, align: 'center',
    render: (v: string) => {
      const n = parseInt(v, 10);
      return <Tag color={n >= 5 ? 'red' : n >= 3 ? 'orange' : 'default'}>{n}板</Tag>;
    },
  },
  { title: '代码', dataIndex: 'ts_code', width: 100 },
  { title: '名称', dataIndex: 'name', width: 90 },
];

const dragonColumns: ColumnsType<DragonTigerItem> = [
  { title: '代码', dataIndex: 'ts_code', width: 100 },
  { title: '名称', dataIndex: 'name', width: 90 },
  {
    title: '涨跌幅', dataIndex: 'pct_change', width: 80, align: 'right',
    render: (v: number | null) => v != null
      ? <span style={{ color: v >= 0 ? '#ef4444' : '#22c55e' }}>{v.toFixed(2)}%</span>
      : '-',
  },
  {
    title: '成交额(万)', dataIndex: 'amount', width: 100, align: 'right',
    render: (v: number | null) => v != null ? (v / 10000).toFixed(0) : '-',
  },
  {
    title: '龙虎买入(万)', dataIndex: 'l_buy', width: 110, align: 'right',
    render: (v: number | null) => v != null ? <span style={{ color: '#ef4444' }}>{(v / 10000).toFixed(0)}</span> : '-',
  },
  {
    title: '龙虎卖出(万)', dataIndex: 'l_sell', width: 110, align: 'right',
    render: (v: number | null) => v != null ? <span style={{ color: '#22c55e' }}>{(v / 10000).toFixed(0)}</span> : '-',
  },
  {
    title: '净额(万)', dataIndex: 'net_amount', width: 100, align: 'right',
    render: (v: number | null) => v != null
      ? <span style={{ color: v >= 0 ? '#ef4444' : '#22c55e' }}>{(v / 10000).toFixed(0)}</span>
      : '-',
  },
  {
    title: '净买率', dataIndex: 'net_rate', width: 80, align: 'right',
    render: (v: number | null) => v != null ? `${v.toFixed(1)}%` : '-',
  },
  { title: '上榜原因', dataIndex: 'reason', ellipsis: true },
];

const hotColumns: ColumnsType<HotListItem> = [
  { title: '排名', dataIndex: 'rank', width: 60, align: 'center' },
  { title: '代码', dataIndex: 'ts_code', width: 100 },
  { title: '名称', dataIndex: 'ts_name', width: 90 },
  { title: '类型', dataIndex: 'data_type', width: 90 },
  {
    title: '涨跌幅', dataIndex: 'pct_change', width: 80, align: 'right',
    render: (v: number | null) => v != null
      ? <span style={{ color: v >= 0 ? '#ef4444' : '#22c55e' }}>{v.toFixed(2)}%</span>
      : '-',
  },
  {
    title: '现价', dataIndex: 'current_price', width: 80, align: 'right',
    render: (v: number | null) => v != null ? v.toFixed(2) : '-',
  },
];

function LimitBoardTab() {
  const [limitType, setLimitType] = useState('');
  const { data, isLoading } = useQuery({
    queryKey: ['limit-board', limitType],
    queryFn: () => api.limitBoard({ limit_type: limitType }),
    refetchInterval: 60_000,
  });

  return (
    <div>
      {data?.data && <LimitSummaryCards data={data.data} />}
      <div className="flex items-center" style={{ gap: 8, marginBottom: 8 }}>
        <span style={{ color: '#93a9bc', fontSize: 12 }}>
          {data?.trade_date ? `数据日期: ${data.trade_date}` : ''}
        </span>
        <Tag
          style={{ cursor: 'pointer' }}
          color={!limitType ? 'blue' : 'default'}
          onClick={() => setLimitType('')}
        >全部</Tag>
        <Tag style={{ cursor: 'pointer' }} color={limitType === 'U' ? 'red' : 'default'} onClick={() => setLimitType('U')}>涨停</Tag>
        <Tag style={{ cursor: 'pointer' }} color={limitType === 'D' ? 'green' : 'default'} onClick={() => setLimitType('D')}>跌停</Tag>
        <Tag style={{ cursor: 'pointer' }} color={limitType === 'Z' ? 'orange' : 'default'} onClick={() => setLimitType('Z')}>炸板</Tag>
      </div>
      <Table
        columns={limitBoardColumns}
        dataSource={data?.data ?? []}
        rowKey={(r) => `${r.ts_code}-${r.limit_type}`}
        size="small"
        loading={isLoading}
        pagination={{ pageSize: 30, size: 'small' }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" /> }}
      />
    </div>
  );
}

function LimitStepTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['limit-step'],
    queryFn: () => api.limitStep(),
    refetchInterval: 60_000,
  });

  return (
    <div>
      <div style={{ color: '#93a9bc', fontSize: 12, marginBottom: 8 }}>
        {data?.trade_date ? `数据日期: ${data.trade_date}` : ''}
      </div>
      <Table
        columns={limitStepColumns}
        dataSource={data?.data ?? []}
        rowKey={(r) => `${r.ts_code}-${r.nums}`}
        size="small"
        loading={isLoading}
        pagination={{ pageSize: 30, size: 'small' }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无连板数据" /> }}
      />
    </div>
  );
}

function DragonTigerTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['dragon-tiger'],
    queryFn: () => api.dragonTiger(),
    refetchInterval: 60_000,
  });

  return (
    <div>
      <div style={{ color: '#93a9bc', fontSize: 12, marginBottom: 8 }}>
        {data?.trade_date ? `数据日期: ${data.trade_date}` : ''}
      </div>
      <Table
        columns={dragonColumns}
        dataSource={data?.data ?? []}
        rowKey={(r) => `${r.ts_code}-dragon`}
        size="small"
        loading={isLoading}
        pagination={{ pageSize: 20, size: 'small' }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无龙虎榜数据" /> }}
      />
    </div>
  );
}

function HotListTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['hot-list'],
    queryFn: () => api.hotList(),
    refetchInterval: 60_000,
  });

  return (
    <div>
      <div style={{ color: '#93a9bc', fontSize: 12, marginBottom: 8 }}>
        {data?.trade_date ? `数据日期: ${data.trade_date}` : ''}
      </div>
      <Table
        columns={hotColumns}
        dataSource={data?.data ?? []}
        rowKey={(r) => `${r.ts_code}-hot`}
        size="small"
        loading={isLoading}
        pagination={{ pageSize: 30, size: 'small' }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无热榜数据" /> }}
      />
    </div>
  );
}

export default function SentimentPage() {
  return (
    <div className="flex flex-col h-full overflow-auto" style={{ padding: 18, gap: 12 }}>
      <Panel className="flex-1" noPadding>
        <Tabs
          defaultActiveKey="limit-board"
          style={{ height: '100%', padding: '0 10px' }}
          items={[
            { key: 'limit-board', label: '涨跌停榜', children: <LimitBoardTab /> },
            { key: 'limit-step', label: '连板天梯', children: <LimitStepTab /> },
            { key: 'dragon-tiger', label: '龙虎榜', children: <DragonTigerTab /> },
            { key: 'hot-list', label: '市场热榜', children: <HotListTab /> },
          ]}
        />
      </Panel>
    </div>
  );
}
