import { useState } from 'react';
import { Tabs, Select, Table, Tag, Card, Statistic, Row, Col, Empty, Descriptions, Drawer, Spin } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useQuery } from '@tanstack/react-query';
import {
  api,
  type IndustryStockRow,
  type ConceptStockRow,
  type CompanyProfile,
} from '../services/api';
import Panel from '../components/Panel';

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null) return '-';
  return v.toFixed(digits);
}

function fmtMv(v: number | null | undefined): string {
  if (v == null) return '-';
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万亿`;
  return `${v.toFixed(0)}亿`;
}

function colorVal(v: number | null | undefined): string {
  if (v == null) return '#93a9bc';
  return v >= 0 ? '#ef4444' : '#22c55e';
}

const industryColumns: ColumnsType<IndustryStockRow> = [
  { title: '代码', dataIndex: 'ts_code', width: 100, fixed: 'left' },
  { title: '名称', dataIndex: 'name', width: 80, fixed: 'left' },
  {
    title: '市值(亿)', dataIndex: 'total_mv', width: 85, align: 'right',
    sorter: (a, b) => (a.total_mv ?? 0) - (b.total_mv ?? 0),
    render: (v: number | null) => fmtMv(v),
  },
  {
    title: 'PE(TTM)', dataIndex: 'pe_ttm', width: 80, align: 'right',
    sorter: (a, b) => (a.pe_ttm ?? 9999) - (b.pe_ttm ?? 9999),
    render: (v: number | null) => fmtNum(v, 1),
  },
  {
    title: 'PB', dataIndex: 'pb', width: 60, align: 'right',
    sorter: (a, b) => (a.pb ?? 9999) - (b.pb ?? 9999),
    render: (v: number | null) => fmtNum(v, 1),
  },
  {
    title: 'ROE(%)', dataIndex: 'roe', width: 75, align: 'right',
    sorter: (a, b) => (a.roe ?? -999) - (b.roe ?? -999),
    render: (v: number | null) => <span style={{ color: colorVal(v) }}>{fmtNum(v)}</span>,
  },
  {
    title: '净利率(%)', dataIndex: 'netprofit_margin', width: 85, align: 'right',
    render: (v: number | null) => fmtNum(v),
  },
  {
    title: '毛利率(%)', dataIndex: 'grossprofit_margin', width: 85, align: 'right',
    render: (v: number | null) => fmtNum(v),
  },
  {
    title: '净利增速(%)', dataIndex: 'netprofit_yoy', width: 95, align: 'right',
    sorter: (a, b) => (a.netprofit_yoy ?? -999) - (b.netprofit_yoy ?? -999),
    render: (v: number | null) => <span style={{ color: colorVal(v) }}>{fmtNum(v)}</span>,
  },
  {
    title: '营收增速(%)', dataIndex: 'or_yoy', width: 95, align: 'right',
    render: (v: number | null) => <span style={{ color: colorVal(v) }}>{fmtNum(v)}</span>,
  },
  {
    title: 'EPS', dataIndex: 'eps', width: 65, align: 'right',
    render: (v: number | null) => fmtNum(v),
  },
  {
    title: '负债率(%)', dataIndex: 'debt_to_assets', width: 85, align: 'right',
    render: (v: number | null) => fmtNum(v, 1),
  },
  {
    title: '报告期', dataIndex: 'fina_period', width: 85,
    render: (v: string | null) => v || '-',
  },
];

const conceptStockColumns: ColumnsType<ConceptStockRow> = [
  { title: '代码', dataIndex: 'ts_code', width: 100 },
  { title: '名称', dataIndex: 'name', width: 80 },
  { title: '行业', dataIndex: 'industry', width: 80 },
  {
    title: '市值(亿)', dataIndex: 'total_mv', width: 85, align: 'right',
    sorter: (a, b) => (a.total_mv ?? 0) - (b.total_mv ?? 0),
    render: (v: number | null) => fmtMv(v),
  },
  {
    title: 'PE(TTM)', dataIndex: 'pe_ttm', width: 80, align: 'right',
    render: (v: number | null) => fmtNum(v, 1),
  },
  {
    title: 'PB', dataIndex: 'pb', width: 60, align: 'right',
    render: (v: number | null) => fmtNum(v, 1),
  },
  {
    title: 'ROE(%)', dataIndex: 'roe', width: 75, align: 'right',
    sorter: (a, b) => (a.roe ?? -999) - (b.roe ?? -999),
    render: (v: number | null) => <span style={{ color: colorVal(v) }}>{fmtNum(v)}</span>,
  },
  {
    title: '净利增速(%)', dataIndex: 'netprofit_yoy', width: 95, align: 'right',
    sorter: (a, b) => (a.netprofit_yoy ?? -999) - (b.netprofit_yoy ?? -999),
    render: (v: number | null) => <span style={{ color: colorVal(v) }}>{fmtNum(v)}</span>,
  },
  {
    title: '营收增速(%)', dataIndex: 'or_yoy', width: 95, align: 'right',
    render: (v: number | null) => <span style={{ color: colorVal(v) }}>{fmtNum(v)}</span>,
  },
  {
    title: 'EPS', dataIndex: 'eps', width: 65, align: 'right',
    render: (v: number | null) => fmtNum(v),
  },
];

function CompanyDrawer({ tsCode, onClose }: { tsCode: string; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ['company-profile', tsCode],
    queryFn: () => api.companyProfile(tsCode),
    enabled: !!tsCode,
  });

  return (
    <Drawer
      title={data ? `${data.basic.name} (${data.basic.ts_code})` : tsCode}
      open={!!tsCode}
      onClose={onClose}
      width={560}
      destroyOnHidden
    >
      {isLoading && <Spin />}
      {data && <CompanyDetail data={data} />}
    </Drawer>
  );
}

function CompanyDetail({ data }: { data: CompanyProfile }) {
  const { basic, valuation, fina_history, main_business, forecasts, concepts } = data;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Descriptions column={2} size="small" bordered>
        <Descriptions.Item label="全称" span={2}>{basic.fullname || basic.name}</Descriptions.Item>
        <Descriptions.Item label="行业">{basic.industry}</Descriptions.Item>
        <Descriptions.Item label="地区">{basic.area}</Descriptions.Item>
        <Descriptions.Item label="市场">{basic.market}</Descriptions.Item>
        <Descriptions.Item label="上市日期">{basic.list_date}</Descriptions.Item>
      </Descriptions>

      {concepts.length > 0 && (
        <div>
          <div style={{ color: '#93a9bc', fontSize: 12, marginBottom: 4 }}>概念板块</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {concepts.map(c => (
              <Tag key={c} style={{ background: 'rgba(107,199,255,0.15)', color: '#6bc7ff', border: 'none', fontSize: 11 }}>{c}</Tag>
            ))}
          </div>
        </div>
      )}

      {valuation.trade_date && (
        <Row gutter={8}>
          <Col span={6}>
            <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(148,186,215,0.12)' }}>
              <Statistic title="PE(TTM)" value={fmtNum(valuation.pe_ttm, 1)} valueStyle={{ fontSize: 16, color: '#e6f1fa' }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(148,186,215,0.12)' }}>
              <Statistic title="PB" value={fmtNum(valuation.pb, 1)} valueStyle={{ fontSize: 16, color: '#e6f1fa' }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(148,186,215,0.12)' }}>
              <Statistic title="总市值" value={fmtMv(valuation.total_mv)} valueStyle={{ fontSize: 16, color: '#e6f1fa' }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(148,186,215,0.12)' }}>
              <Statistic title="换手率" value={fmtNum(valuation.turnover_rate, 1) + '%'} valueStyle={{ fontSize: 16, color: '#e6f1fa' }} />
            </Card>
          </Col>
        </Row>
      )}

      {fina_history.length > 0 && (
        <div>
          <div style={{ color: '#93a9bc', fontSize: 12, marginBottom: 8 }}>财务指标历史</div>
          <Table
            dataSource={fina_history}
            rowKey="end_date"
            size="small"
            pagination={false}
            scroll={{ x: 600 }}
            columns={[
              { title: '报告期', dataIndex: 'end_date', width: 85 },
              { title: 'ROE(%)', dataIndex: 'roe', width: 70, align: 'right', render: (v: number | null) => <span style={{ color: colorVal(v) }}>{fmtNum(v)}</span> },
              { title: '净利率(%)', dataIndex: 'netprofit_margin', width: 80, align: 'right', render: (v: number | null) => fmtNum(v) },
              { title: '毛利率(%)', dataIndex: 'grossprofit_margin', width: 80, align: 'right', render: (v: number | null) => fmtNum(v) },
              { title: '净利增速', dataIndex: 'netprofit_yoy', width: 80, align: 'right', render: (v: number | null) => <span style={{ color: colorVal(v) }}>{fmtNum(v)}</span> },
              { title: '营收增速', dataIndex: 'or_yoy', width: 80, align: 'right', render: (v: number | null) => <span style={{ color: colorVal(v) }}>{fmtNum(v)}</span> },
              { title: 'EPS', dataIndex: 'eps', width: 60, align: 'right', render: (v: number | null) => fmtNum(v) },
              { title: '负债率', dataIndex: 'debt_to_assets', width: 70, align: 'right', render: (v: number | null) => fmtNum(v, 1) },
            ]}
          />
        </div>
      )}

      {main_business.length > 0 && (
        <div>
          <div style={{ color: '#93a9bc', fontSize: 12, marginBottom: 8 }}>主营业务构成</div>
          <Table
            dataSource={main_business}
            rowKey={(r, i) => `${r.end_date}-${r.bz_item}-${i}`}
            size="small"
            pagination={false}
            columns={[
              { title: '报告期', dataIndex: 'end_date', width: 85 },
              { title: '业务', dataIndex: 'bz_item', ellipsis: true },
              { title: '营收(万)', dataIndex: 'bz_sales', width: 100, align: 'right', render: (v: number | null) => v != null ? (v / 10000).toFixed(0) : '-' },
              { title: '利润(万)', dataIndex: 'bz_profit', width: 100, align: 'right', render: (v: number | null) => v != null ? (v / 10000).toFixed(0) : '-' },
            ]}
          />
        </div>
      )}

      {forecasts.length > 0 && (
        <div>
          <div style={{ color: '#93a9bc', fontSize: 12, marginBottom: 8 }}>业绩预告</div>
          <Table
            dataSource={forecasts}
            rowKey={(r) => `${r.ann_date}-${r.end_date}`}
            size="small"
            pagination={false}
            columns={[
              { title: '公告日', dataIndex: 'ann_date', width: 85 },
              { title: '报告期', dataIndex: 'end_date', width: 85 },
              {
                title: '类型', dataIndex: 'type', width: 70,
                render: (v: string | null) => {
                  const colors: Record<string, string> = { '预增': 'red', '预减': 'green', '扭亏': 'orange', '续亏': 'green', '略增': 'red', '略减': 'green' };
                  return v ? <Tag color={colors[v] || 'default'}>{v}</Tag> : '-';
                },
              },
              {
                title: '变动幅度', width: 120,
                render: (_: unknown, r: CompanyProfile['forecasts'][0]) => {
                  if (r.p_change_min == null && r.p_change_max == null) return '-';
                  return `${fmtNum(r.p_change_min, 0)}% ~ ${fmtNum(r.p_change_max, 0)}%`;
                },
              },
              { title: '摘要', dataIndex: 'summary', ellipsis: true },
            ]}
          />
        </div>
      )}
    </div>
  );
}

function IndustryTab() {
  const [industry, setIndustry] = useState('');
  const [selectedCode, setSelectedCode] = useState('');

  const { data: industries } = useQuery({
    queryKey: ['fundamental-industries'],
    queryFn: api.fundamentalIndustries,
    staleTime: 300_000,
  });

  const { data: stocks, isLoading } = useQuery({
    queryKey: ['industry-profile', industry],
    queryFn: () => api.industryProfile(industry),
    enabled: !!industry,
  });

  const summary = stocks?.data?.length ? (() => {
    const d = stocks.data.filter(s => s.roe != null);
    const avgRoe = d.length ? d.reduce((s, r) => s + (r.roe ?? 0), 0) / d.length : 0;
    const d2 = stocks.data.filter(s => s.pe_ttm != null && s.pe_ttm > 0 && s.pe_ttm < 1000);
    const avgPe = d2.length ? d2.reduce((s, r) => s + (r.pe_ttm ?? 0), 0) / d2.length : 0;
    const totalMv = stocks.data.reduce((s, r) => s + (r.total_mv ?? 0), 0);
    return { count: stocks.data.length, avgRoe, avgPe, totalMv };
  })() : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className="flex items-center" style={{ gap: 8 }}>
        <Select
          showSearch
          value={industry || undefined}
          onChange={setIndustry}
          style={{ width: 200 }}
          size="small"
          placeholder="选择申万行业"
          optionFilterProp="label"
          options={industries?.data?.map(i => ({ value: i.industry, label: `${i.industry} (${i.count})` })) || []}
        />
        {summary && (
          <Row gutter={8} style={{ flex: 1 }}>
            <Col><Tag color="blue">{summary.count}只</Tag></Col>
            <Col><Tag style={{ background: 'rgba(107,199,255,0.15)', color: '#6bc7ff', border: 'none' }}>均ROE: {summary.avgRoe.toFixed(1)}%</Tag></Col>
            <Col><Tag style={{ background: 'rgba(167,139,250,0.15)', color: '#a78bfa', border: 'none' }}>均PE: {summary.avgPe.toFixed(1)}</Tag></Col>
            <Col><Tag style={{ background: 'rgba(245,158,11,0.15)', color: '#f59e0b', border: 'none' }}>总市值: {fmtMv(summary.totalMv)}</Tag></Col>
          </Row>
        )}
      </div>
      <Table
        columns={industryColumns}
        dataSource={stocks?.data ?? []}
        rowKey="ts_code"
        size="small"
        loading={isLoading}
        scroll={{ x: 1100 }}
        pagination={{ pageSize: 30, size: 'small' }}
        onRow={(r) => ({ onClick: () => setSelectedCode(r.ts_code), style: { cursor: 'pointer' } })}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={industry ? '暂无数据' : '请选择行业'} /> }}
      />
      {selectedCode && <CompanyDrawer tsCode={selectedCode} onClose={() => setSelectedCode('')} />}
    </div>
  );
}

function ConceptTab() {
  const [concept, setConcept] = useState('');
  const [selectedCode, setSelectedCode] = useState('');

  const { data: concepts } = useQuery({
    queryKey: ['fundamental-concepts'],
    queryFn: api.fundamentalConcepts,
    staleTime: 300_000,
  });

  const { data: stocks, isLoading } = useQuery({
    queryKey: ['concept-stocks', concept],
    queryFn: () => api.conceptStocks(concept),
    enabled: !!concept,
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className="flex items-center" style={{ gap: 8 }}>
        <Select
          showSearch
          value={concept || undefined}
          onChange={setConcept}
          style={{ width: 260 }}
          size="small"
          placeholder="搜索概念板块"
          optionFilterProp="label"
          options={concepts?.data?.map(c => ({ value: c.code, label: `${c.name} (${c.count})` })) || []}
        />
        {stocks?.count != null && <Tag color="blue">{stocks.count}只</Tag>}
      </div>
      <Table
        columns={conceptStockColumns}
        dataSource={stocks?.data ?? []}
        rowKey="ts_code"
        size="small"
        loading={isLoading}
        pagination={{ pageSize: 30, size: 'small' }}
        onRow={(r) => ({ onClick: () => setSelectedCode(r.ts_code), style: { cursor: 'pointer' } })}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={concept ? '暂无数据' : '请选择概念板块'} /> }}
      />
      {selectedCode && <CompanyDrawer tsCode={selectedCode} onClose={() => setSelectedCode('')} />}
    </div>
  );
}

export default function FundamentalPage() {
  return (
    <div className="flex flex-col h-full overflow-auto" style={{ padding: 18, gap: 12 }}>
      <Panel className="flex-1" noPadding>
        <Tabs
          defaultActiveKey="industry"
          style={{ height: '100%', padding: '0 10px' }}
          items={[
            { key: 'industry', label: '行业分析', children: <IndustryTab /> },
            { key: 'concept', label: '概念板块', children: <ConceptTab /> },
          ]}
        />
      </Panel>
    </div>
  );
}
