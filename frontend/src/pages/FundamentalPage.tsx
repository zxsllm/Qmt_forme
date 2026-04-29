import { useState } from 'react';
import { Tabs, Select, Table, Tag, Card, Statistic, Row, Col, Empty, Descriptions, Drawer, Spin, Radio } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useQuery } from '@tanstack/react-query';
import {
  api,
  type IndustryStockRow,
  type ConceptStockRow,
  type CompanyProfile,
} from '../services/api';
import Panel from '../components/Panel';
import dayjs from 'dayjs';

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

  const { data: top10Data } = useQuery({
    queryKey: ['top10-holders', tsCode],
    queryFn: () => api.getTop10Holders(tsCode, 2),
    enabled: !!tsCode,
  });

  const { data: holderNumData } = useQuery({
    queryKey: ['holder-number', tsCode],
    queryFn: () => api.getHolderNumber(tsCode),
    enabled: !!tsCode,
  });

  const { data: holderTradeData } = useQuery({
    queryKey: ['holdertrade-stock', tsCode],
    queryFn: () => api.getHolderTrade(tsCode),
    enabled: !!tsCode,
  });

  const { data: floatData } = useQuery({
    queryKey: ['share-float-stock', tsCode],
    queryFn: () => api.getShareFloat(tsCode, dayjs().format('YYYYMMDD'), dayjs().add(90, 'day').format('YYYYMMDD')),
    enabled: !!tsCode,
  });

  return (
    <Drawer
      title={data ? `${data.basic.name} (${data.basic.ts_code})` : tsCode}
      open={!!tsCode}
      onClose={onClose}
      width={640}
      destroyOnHidden
    >
      {isLoading && <Spin />}
      {data && <CompanyDetail data={data} />}

      {(holderTradeData?.data?.length ?? 0) > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ color: '#93a9bc', fontSize: 12, marginBottom: 8 }}>股东增减持</div>
          <Table
            dataSource={(holderTradeData?.data ?? []) as Record<string, unknown>[]}
            rowKey={(_, i) => String(i)}
            size="small"
            pagination={false}
            scroll={{ x: 500 }}
            columns={[
              { title: '公告日', dataIndex: 'ann_date', width: 85 },
              { title: '方向', dataIndex: 'in_de', width: 50,
                render: (v: string) => <Tag color={v === 'IN' ? 'red' : 'green'} style={{ margin: 0 }}>{v === 'IN' ? '增持' : '减持'}</Tag> },
              { title: '股东', dataIndex: 'holder_name', width: 120, ellipsis: true },
              { title: '变动(万股)', dataIndex: 'change_vol', width: 90, align: 'right',
                render: (v: number) => v ? (v / 1e4).toFixed(1) : '-' },
              { title: '均价', dataIndex: 'avg_price', width: 70, align: 'right',
                render: (v: number) => v ? v.toFixed(2) : '-' },
              { title: '变动比例(%)', dataIndex: 'change_ratio', width: 90, align: 'right',
                render: (v: number) => v ? v.toFixed(2) : '-' },
            ]}
          />
        </div>
      )}

      {(top10Data?.data?.length ?? 0) > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ color: '#93a9bc', fontSize: 12, marginBottom: 8 }}>前十大流通股东</div>
          <Table
            dataSource={(top10Data?.data ?? []) as Record<string, unknown>[]}
            rowKey={(_, i) => String(i)}
            size="small"
            pagination={false}
            scroll={{ x: 500 }}
            columns={[
              { title: '报告期', dataIndex: 'end_date', width: 85 },
              { title: '股东名称', dataIndex: 'holder_name', width: 140, ellipsis: true },
              { title: '持股(万股)', dataIndex: 'hold_amount', width: 100, align: 'right',
                render: (v: number) => v ? (v / 1e4).toFixed(1) : '-' },
              { title: '占流通比(%)', dataIndex: 'hold_float_ratio', width: 90, align: 'right',
                render: (v: number) => v ? v.toFixed(2) : '-' },
              { title: '增减', dataIndex: 'hold_change', width: 80, align: 'right',
                render: (v: number) => {
                  if (v == null) return '-';
                  const c = v > 0 ? '#ef4444' : v < 0 ? '#22c55e' : '#93a9bc';
                  return <span style={{ color: c }}>{v > 0 ? '+' : ''}{(v / 1e4).toFixed(1)}万</span>;
                } },
              { title: '类型', dataIndex: 'holder_type', width: 40 },
            ]}
          />
        </div>
      )}

      {(holderNumData?.data?.length ?? 0) > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ color: '#93a9bc', fontSize: 12, marginBottom: 8 }}>股东人数变化</div>
          <Table
            dataSource={(holderNumData?.data ?? []) as Record<string, unknown>[]}
            rowKey={(_, i) => String(i)}
            size="small"
            pagination={false}
            columns={[
              { title: '截止日', dataIndex: 'end_date', width: 85 },
              { title: '股东户数', dataIndex: 'holder_num', width: 100, align: 'right',
                render: (v: number) => v ? v.toLocaleString() : '-' },
              { title: '公告日', dataIndex: 'ann_date', width: 85 },
            ]}
          />
        </div>
      )}

      {(floatData?.data?.length ?? 0) > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ color: '#93a9bc', fontSize: 12, marginBottom: 8 }}>未来解禁计划</div>
          <Table
            dataSource={(floatData?.data ?? []) as Record<string, unknown>[]}
            rowKey={(_, i) => String(i)}
            size="small"
            pagination={false}
            columns={[
              { title: '解禁日', dataIndex: 'float_date', width: 85 },
              { title: '解禁(万股)', dataIndex: 'float_share', width: 100, align: 'right',
                render: (v: number) => v ? (v / 1e4).toFixed(1) : '-' },
              { title: '占比(%)', dataIndex: 'float_ratio', width: 80, align: 'right',
                render: (v: number) => v ? v.toFixed(2) : '-' },
              { title: '股东', dataIndex: 'holder_name', ellipsis: true },
            ]}
          />
        </div>
      )}
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

export function MarketCapitalTab() {
  const [marginDays, setMarginDays] = useState(30);
  const { data: marginData, isLoading: ml } = useQuery({
    queryKey: ['margin-data', marginDays],
    queryFn: () => api.getMargin('', '', marginDays),
    staleTime: 300_000,
  });

  const { data: topInstData, isLoading: tl } = useQuery({
    queryKey: ['top-inst-latest'],
    queryFn: () => api.getTopInst(),
    staleTime: 300_000,
  });

  const marginAgg = (() => {
    if (!marginData?.data?.length) return [];
    const byDate = new Map<string, { trade_date: string; rzye: number; rqye: number; rzrqye: number }>();
    for (const r of marginData.data) {
      const d = r.trade_date as string;
      if (!byDate.has(d)) byDate.set(d, { trade_date: d, rzye: 0, rqye: 0, rzrqye: 0 });
      const agg = byDate.get(d)!;
      agg.rzye += (r.rzye as number) || 0;
      agg.rqye += (r.rqye as number) || 0;
      agg.rzrqye += (r.rzrqye as number) || 0;
    }
    return Array.from(byDate.values()).sort((a, b) => b.trade_date.localeCompare(a.trade_date));
  })();

  return (
    <div style={{ display: 'flex', gap: 16 }}>
      <div style={{ flex: 1 }}>
        <div className="flex items-center gap-2" style={{ marginBottom: 8 }}>
          <span style={{ color: '#93a9bc', fontSize: 13 }}>融资融券汇总</span>
          <Radio.Group size="small" value={marginDays} onChange={e => setMarginDays(e.target.value)}>
            <Radio.Button value={7}>7天</Radio.Button>
            <Radio.Button value={30}>30天</Radio.Button>
            <Radio.Button value={90}>90天</Radio.Button>
          </Radio.Group>
        </div>
        <Table
          dataSource={marginAgg}
          rowKey="trade_date"
          size="small"
          loading={ml}
          pagination={{ pageSize: 15, size: 'small' }}
          columns={[
            { title: '日期', dataIndex: 'trade_date', width: 90 },
            { title: '融资余额(亿)', dataIndex: 'rzye', width: 110, align: 'right',
              render: (v: number) => (v / 1e8).toFixed(2) },
            { title: '融券余额(亿)', dataIndex: 'rqye', width: 110, align: 'right',
              render: (v: number) => (v / 1e8).toFixed(2) },
            { title: '融资融券余额(亿)', dataIndex: 'rzrqye', width: 130, align: 'right',
              render: (v: number) => (v / 1e8).toFixed(2) },
          ]}
        />
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ color: '#93a9bc', fontSize: 13, marginBottom: 8 }}>龙虎榜机构交易</div>
        <Table
          dataSource={(topInstData?.data ?? []) as Record<string, unknown>[]}
          rowKey={(_, i) => String(i)}
          size="small"
          loading={tl}
          pagination={{ pageSize: 15, size: 'small' }}
          scroll={{ x: 700 }}
          columns={[
            { title: '日期', dataIndex: 'trade_date', width: 85 },
            { title: '代码', dataIndex: 'ts_code', width: 90 },
            { title: '营业部', dataIndex: 'exalter', width: 140, ellipsis: true },
            { title: '方向', dataIndex: 'side', width: 50,
              render: (v: string) => <Tag color={v === '买入' || v === '0' ? 'red' : 'green'}>{v === '0' ? '买入' : v === '1' ? '卖出' : v}</Tag> },
            { title: '买入(万)', dataIndex: 'buy', width: 90, align: 'right',
              render: (v: number) => v ? (v / 1e4).toFixed(0) : '-' },
            { title: '卖出(万)', dataIndex: 'sell', width: 90, align: 'right',
              render: (v: number) => v ? (v / 1e4).toFixed(0) : '-' },
            { title: '净买入(万)', dataIndex: 'net_buy', width: 100, align: 'right',
              render: (v: number) => v ? <span style={{ color: v >= 0 ? '#ef4444' : '#22c55e' }}>{(v / 1e4).toFixed(0)}</span> : '-' },
            { title: '原因', dataIndex: 'reason', ellipsis: true },
          ]}
        />
      </div>
    </div>
  );
}

function UnlockTradeTab() {
  const [floatDays, setFloatDays] = useState(30);
  const [tradeDays, setTradeDays] = useState(7);
  const [tradeType, setTradeType] = useState('');

  const { data: floatData, isLoading: fl } = useQuery({
    queryKey: ['upcoming-float', floatDays],
    queryFn: () => api.getUpcomingShareFloat(floatDays),
    staleTime: 300_000,
  });

  const { data: tradeData, isLoading: tl } = useQuery({
    queryKey: ['recent-holdertrade', tradeDays, tradeType],
    queryFn: () => api.getRecentHolderTrade(tradeDays, tradeType),
    staleTime: 300_000,
  });

  return (
    <div style={{ display: 'flex', gap: 16 }}>
      <div style={{ flex: 1 }}>
        <div className="flex items-center gap-2" style={{ marginBottom: 8 }}>
          <span style={{ color: '#93a9bc', fontSize: 13 }}>近期限售股解禁</span>
          <Radio.Group size="small" value={floatDays} onChange={e => setFloatDays(e.target.value)}>
            <Radio.Button value={7}>7天</Radio.Button>
            <Radio.Button value={30}>30天</Radio.Button>
            <Radio.Button value={60}>60天</Radio.Button>
          </Radio.Group>
        </div>
        <Table
          dataSource={(floatData?.data ?? []) as Record<string, unknown>[]}
          rowKey={(_, i) => String(i)}
          size="small"
          loading={fl}
          pagination={{ pageSize: 15, size: 'small' }}
          scroll={{ x: 600 }}
          columns={[
            { title: '解禁日', dataIndex: 'float_date', width: 85 },
            { title: '代码', dataIndex: 'ts_code', width: 90 },
            { title: '名称', dataIndex: 'name', width: 80 },
            { title: '解禁股数(万)', dataIndex: 'float_share', width: 100, align: 'right',
              render: (v: number) => v ? (v / 1e4).toFixed(0) : '-' },
            { title: '占比(%)', dataIndex: 'float_ratio', width: 80, align: 'right',
              render: (v: number) => v ? v.toFixed(2) : '-' },
            { title: '股东', dataIndex: 'holder_name', ellipsis: true },
            { title: '类型', dataIndex: 'share_type', width: 80, ellipsis: true },
          ]}
        />
      </div>
      <div style={{ flex: 1 }}>
        <div className="flex items-center gap-2" style={{ marginBottom: 8 }}>
          <span style={{ color: '#93a9bc', fontSize: 13 }}>近期增减持</span>
          <Radio.Group size="small" value={tradeDays} onChange={e => setTradeDays(e.target.value)}>
            <Radio.Button value={3}>3天</Radio.Button>
            <Radio.Button value={7}>7天</Radio.Button>
            <Radio.Button value={14}>14天</Radio.Button>
          </Radio.Group>
          <Radio.Group size="small" value={tradeType} onChange={e => setTradeType(e.target.value)}>
            <Radio.Button value="">全部</Radio.Button>
            <Radio.Button value="IN">增持</Radio.Button>
            <Radio.Button value="DE">减持</Radio.Button>
          </Radio.Group>
        </div>
        <Table
          dataSource={(tradeData?.data ?? []) as Record<string, unknown>[]}
          rowKey={(_, i) => String(i)}
          size="small"
          loading={tl}
          pagination={{ pageSize: 15, size: 'small' }}
          scroll={{ x: 700 }}
          columns={[
            { title: '公告日', dataIndex: 'ann_date', width: 85 },
            { title: '代码', dataIndex: 'ts_code', width: 90 },
            { title: '名称', dataIndex: 'name', width: 80 },
            { title: '方向', dataIndex: 'in_de', width: 55,
              render: (v: string) => <Tag color={v === 'IN' ? 'red' : 'green'}>{v === 'IN' ? '增持' : '减持'}</Tag> },
            { title: '股东', dataIndex: 'holder_name', width: 100, ellipsis: true },
            { title: '变动(万股)', dataIndex: 'change_vol', width: 90, align: 'right',
              render: (v: number) => v ? (v / 1e4).toFixed(1) : '-' },
            { title: '均价', dataIndex: 'avg_price', width: 70, align: 'right',
              render: (v: number) => v ? v.toFixed(2) : '-' },
            { title: '变动比例(%)', dataIndex: 'change_ratio', width: 90, align: 'right',
              render: (v: number) => v ? v.toFixed(2) : '-' },
          ]}
        />
      </div>
    </div>
  );
}

export function EventCalendarTab() {
  const [dateRange, setDateRange] = useState('upcoming');

  const params = (() => {
    const now = dayjs();
    if (dateRange === 'upcoming') return { start: now.format('YYYYMMDD'), end: now.add(30, 'day').format('YYYYMMDD') };
    if (dateRange === 'recent') return { start: now.subtract(14, 'day').format('YYYYMMDD'), end: now.format('YYYYMMDD') };
    return { start: now.subtract(30, 'day').format('YYYYMMDD'), end: now.add(30, 'day').format('YYYYMMDD') };
  })();

  const { data, isLoading } = useQuery({
    queryKey: ['event-calendar', dateRange],
    queryFn: () => api.eventCalendar(params.start, params.end),
    staleTime: 300_000,
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div className="flex items-center gap-2">
        <span style={{ color: '#93a9bc', fontSize: 13 }}>时间范围</span>
        <Radio.Group size="small" value={dateRange} onChange={e => setDateRange(e.target.value)}>
          <Radio.Button value="upcoming">未来30天</Radio.Button>
          <Radio.Button value="recent">近14天</Radio.Button>
          <Radio.Button value="all">前后30天</Radio.Button>
        </Radio.Group>
        {data && (
          <span style={{ color: '#93a9bc', fontSize: 11, marginLeft: 8 }}>
            披露 {data.disclosures?.length ?? 0} 条 · 预告 {data.forecasts?.length ?? 0} 条
          </span>
        )}
      </div>
      <div style={{ display: 'flex', gap: 16 }}>
        <div style={{ flex: 1 }}>
          <div style={{ color: '#93a9bc', fontSize: 12, fontWeight: 600, marginBottom: 8 }}>财报披露日历</div>
          <Table
            dataSource={data?.disclosures ?? []}
            rowKey={(r, i) => `${r.ts_code}-${r.end_date}-${i}`}
            size="small"
            loading={isLoading}
            pagination={{ pageSize: 15, size: 'small' }}
            scroll={{ x: 500 }}
            columns={[
              { title: '代码', dataIndex: 'ts_code', width: 90 },
              { title: '名称', dataIndex: 'name', width: 80 },
              { title: '报告期', dataIndex: 'end_date', width: 85 },
              { title: '计划披露', dataIndex: 'pre_date', width: 85,
                render: (v: string) => v || <span style={{ color: '#4b5563' }}>待定</span> },
              { title: '实际披露', dataIndex: 'actual_date', width: 85,
                render: (v: string) => v ? <Tag color="green" style={{ margin: 0 }}>{v}</Tag> : <span style={{ color: '#4b5563' }}>未披露</span> },
            ]}
          />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ color: '#93a9bc', fontSize: 12, fontWeight: 600, marginBottom: 8 }}>业绩预告</div>
          <Table
            dataSource={data?.forecasts ?? []}
            rowKey={(r, i) => `${r.ts_code}-${r.ann_date}-${i}`}
            size="small"
            loading={isLoading}
            pagination={{ pageSize: 15, size: 'small' }}
            scroll={{ x: 650 }}
            columns={[
              { title: '公告日', dataIndex: 'ann_date', width: 85 },
              { title: '代码', dataIndex: 'ts_code', width: 90 },
              { title: '名称', dataIndex: 'name', width: 80 },
              { title: '类型', dataIndex: 'type', width: 60,
                render: (v: string, _r: any) => {
                  const colors: Record<string, string> = { '预增': 'red', '预减': 'green', '扭亏': 'orange', '续亏': 'green', '略增': 'red', '略减': 'green', '首亏': 'green', '预告': 'blue', '快报': 'cyan' };
                  return v ? <Tag color={colors[v] || 'default'} style={{ margin: 0 }}>{v}</Tag> : '-';
                } },
              { title: '变动/净利润', width: 140,
                render: (_: unknown, r: any) => {
                  if (r.p_change_min != null || r.p_change_max != null) {
                    const pct = `同比${fmtNum(r.p_change_min, 0)}%~${fmtNum(r.p_change_max, 0)}%`;
                    const profit = (r.net_profit_min != null)
                      ? `, 净利润 ${(r.net_profit_min / 10000).toFixed(2)}~${(r.net_profit_max / 10000).toFixed(2)} 亿`
                      : '';
                    return <span style={{ fontSize: 11 }}>{pct}{profit}</span>;
                  }
                  if (r.source === 'anns_parsed' && r.ann_url) {
                    return <a href={r.ann_url} target="_blank" rel="noreferrer" style={{ color: '#6bc7ff', fontSize: 11 }}>查看公告原文</a>;
                  }
                  return <span style={{ color: '#4b5563' }}>报告期{r.end_date}</span>;
                },
              },
            ]}
          />
        </div>
      </div>
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
            { key: 'unlock', label: '解禁/增减持', children: <UnlockTradeTab /> },
          ]}
        />
      </Panel>
    </div>
  );
}
