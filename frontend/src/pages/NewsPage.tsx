import { useState } from 'react';
import { Tabs, Select, Tag, Table, Empty, Card, Statistic, Row, Col } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useQuery } from '@tanstack/react-query';
import { api, type ClassifiedNewsItem, type ClassifiedAnnItem } from '../services/api';
import Panel from '../components/Panel';

const SCOPE_LABELS: Record<string, { text: string; color: string }> = {
  macro: { text: '宏观', color: '#6bc7ff' },
  industry: { text: '行业', color: '#f59e0b' },
  stock: { text: '个股', color: '#a78bfa' },
  mixed: { text: '综合', color: '#64748b' },
};

const SENTIMENT_LABELS: Record<string, { text: string; color: string }> = {
  positive: { text: '利好', color: '#ef4444' },
  negative: { text: '利空', color: '#22c55e' },
  neutral: { text: '中性', color: '#64748b' },
};

const TIME_SLOT_LABELS: Record<string, string> = {
  pre_open: '盘前',
  intraday: '盘中',
  after_hours: '盘后',
};

const ANN_TYPE_LABELS: Record<string, string> = {
  earnings_forecast: '业绩预告',
  earnings_report: '业绩快报',
  holder_change: '增减持',
  buyback: '回购',
  dividend: '分红',
  equity_change: '股权变动',
  violation: '违规处罚',
  other: '其他',
};

const newsColumns: ColumnsType<ClassifiedNewsItem> = [
  {
    title: '时间', dataIndex: 'datetime', width: 150,
    render: (v: string) => v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '',
  },
  {
    title: '类型', dataIndex: 'news_scope', width: 70,
    render: (v: string) => {
      const s = SCOPE_LABELS[v] || { text: v, color: '#64748b' };
      return <Tag color={s.color}>{s.text}</Tag>;
    },
  },
  {
    title: '时段', dataIndex: 'time_slot', width: 60,
    render: (v: string) => <span style={{ color: '#93a9bc', fontSize: 12 }}>{TIME_SLOT_LABELS[v] || v}</span>,
  },
  {
    title: '情绪', dataIndex: 'sentiment', width: 60,
    render: (v: string) => {
      const s = SENTIMENT_LABELS[v] || { text: v, color: '#64748b' };
      return <Tag color={s.color}>{s.text}</Tag>;
    },
  },
  {
    title: '内容', dataIndex: 'content', ellipsis: true,
  },
  {
    title: '关联', dataIndex: 'related_codes', width: 140,
    render: (v: string | null) => {
      if (!v) return '-';
      try {
        const codes: string[] = JSON.parse(v);
        return codes.slice(0, 3).join(', ') + (codes.length > 3 ? '...' : '');
      } catch { return v; }
    },
  },
];

const annColumns: ColumnsType<ClassifiedAnnItem> = [
  { title: '日期', dataIndex: 'ann_date', width: 100 },
  { title: '代码', dataIndex: 'ts_code', width: 100 },
  {
    title: '类型', dataIndex: 'ann_type', width: 90,
    render: (v: string) => <Tag>{ANN_TYPE_LABELS[v] || v}</Tag>,
  },
  {
    title: '情绪', dataIndex: 'sentiment', width: 60,
    render: (v: string) => {
      const s = SENTIMENT_LABELS[v] || { text: v, color: '#64748b' };
      return <Tag color={s.color}>{s.text}</Tag>;
    },
  },
  {
    title: '标题', dataIndex: 'title', ellipsis: true,
    render: (v: string, row: ClassifiedAnnItem) =>
      row.url ? <a href={row.url} target="_blank" rel="noopener noreferrer" style={{ color: '#6bc7ff' }}>{v}</a> : v,
  },
];

function NewsStatsBar() {
  const { data } = useQuery({
    queryKey: ['news-stats'],
    queryFn: api.newsStats,
    staleTime: 60_000,
  });

  if (!data?.data?.length) return null;

  const byScope: Record<string, number> = {};
  const bySentiment: Record<string, number> = {};
  let total = 0;
  for (const row of data.data) {
    byScope[row.scope] = (byScope[row.scope] || 0) + row.count;
    bySentiment[row.sentiment] = (bySentiment[row.sentiment] || 0) + row.count;
    total += row.count;
  }

  return (
    <Row gutter={12} style={{ marginBottom: 12 }}>
      <Col span={4}>
        <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(148,186,215,0.12)' }}>
          <Statistic title="总计" value={total} valueStyle={{ fontSize: 18, color: '#e6f1fa' }} />
        </Card>
      </Col>
      {Object.entries(SCOPE_LABELS).map(([key, { text, color }]) => (
        <Col span={4} key={key}>
          <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(148,186,215,0.12)' }}>
            <Statistic title={text} value={byScope[key] || 0} valueStyle={{ fontSize: 18, color }} />
          </Card>
        </Col>
      ))}
      <Col span={4}>
        <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(148,186,215,0.12)' }}>
          <Statistic
            title="利好/利空"
            value={`${bySentiment['positive'] || 0}/${bySentiment['negative'] || 0}`}
            valueStyle={{ fontSize: 16, color: '#e6f1fa' }}
          />
        </Card>
      </Col>
    </Row>
  );
}

function ClassifiedNewsTab() {
  const [scope, setScope] = useState('');
  const [timeSlot, setTimeSlot] = useState('');
  const [sentiment, setSentiment] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['classified-news', scope, timeSlot, sentiment],
    queryFn: () => api.classifiedNews({ scope, time_slot: timeSlot, sentiment, limit: 200 }),
    refetchInterval: 30_000,
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className="flex items-center" style={{ gap: 8, flexWrap: 'wrap' }}>
        <Select value={scope} onChange={setScope} style={{ width: 100 }} size="small" allowClear placeholder="类型">
          <Select.Option value="">全部</Select.Option>
          <Select.Option value="macro">宏观</Select.Option>
          <Select.Option value="industry">行业</Select.Option>
          <Select.Option value="stock">个股</Select.Option>
        </Select>
        <Select value={timeSlot} onChange={setTimeSlot} style={{ width: 100 }} size="small" allowClear placeholder="时段">
          <Select.Option value="">全部</Select.Option>
          <Select.Option value="pre_open">盘前</Select.Option>
          <Select.Option value="intraday">盘中</Select.Option>
          <Select.Option value="after_hours">盘后</Select.Option>
        </Select>
        <Select value={sentiment} onChange={setSentiment} style={{ width: 100 }} size="small" allowClear placeholder="情绪">
          <Select.Option value="">全部</Select.Option>
          <Select.Option value="positive">利好</Select.Option>
          <Select.Option value="negative">利空</Select.Option>
          <Select.Option value="neutral">中性</Select.Option>
        </Select>
      </div>
      <Table
        columns={newsColumns}
        dataSource={data?.data ?? []}
        rowKey="id"
        size="small"
        loading={isLoading}
        pagination={{ pageSize: 30, size: 'small' }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无分类新闻" /> }}
      />
    </div>
  );
}

function ClassifiedAnnsTab() {
  const [annType, setAnnType] = useState('');
  const [sentiment, setSentiment] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['classified-anns', annType, sentiment],
    queryFn: () => api.classifiedAnns({ ann_type: annType, sentiment, limit: 200 }),
    refetchInterval: 60_000,
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className="flex items-center" style={{ gap: 8 }}>
        <Select value={annType} onChange={setAnnType} style={{ width: 120 }} size="small" allowClear placeholder="公告类型">
          <Select.Option value="">全部</Select.Option>
          {Object.entries(ANN_TYPE_LABELS).map(([k, v]) => (
            <Select.Option key={k} value={k}>{v}</Select.Option>
          ))}
        </Select>
        <Select value={sentiment} onChange={setSentiment} style={{ width: 100 }} size="small" allowClear placeholder="情绪">
          <Select.Option value="">全部</Select.Option>
          <Select.Option value="positive">利好</Select.Option>
          <Select.Option value="negative">利空</Select.Option>
          <Select.Option value="neutral">中性</Select.Option>
        </Select>
      </div>
      <Table
        columns={annColumns}
        dataSource={data?.data ?? []}
        rowKey="id"
        size="small"
        loading={isLoading}
        pagination={{ pageSize: 30, size: 'small' }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无分类公告" /> }}
      />
    </div>
  );
}

export default function NewsPage() {
  return (
    <div className="flex flex-col h-full overflow-auto" style={{ padding: 18, gap: 12 }}>
      <NewsStatsBar />
      <Panel className="flex-1" noPadding>
        <Tabs
          defaultActiveKey="news"
          style={{ height: '100%', padding: '0 10px' }}
          items={[
            {
              key: 'news',
              label: '分类新闻',
              children: <ClassifiedNewsTab />,
            },
            {
              key: 'anns',
              label: '分类公告',
              children: <ClassifiedAnnsTab />,
            },
          ]}
        />
      </Panel>
    </div>
  );
}
