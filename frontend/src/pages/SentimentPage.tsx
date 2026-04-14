import { useState } from 'react';
import {
  Table, Tag, Tabs, Card, Statistic, Row, Col, Empty, DatePicker, Modal,
  Descriptions, Input, Button, Alert, Spin, Progress, Drawer, List, Badge,
} from 'antd';
import {
  FireOutlined, ThunderboltOutlined, SearchOutlined,
  WarningOutlined, RiseOutlined, FallOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useQuery } from '@tanstack/react-query';
import dayjs, { type Dayjs } from 'dayjs';
import {
  api,
  type LimitBoardItem, type LimitStepItem, type DragonTigerItem, type HotListItem,
  type BoardLeaderItem, type HotMoneyItem,
} from '../services/api';
import Panel from '../components/Panel';

function fmtDate(d: Dayjs): string { return d.format('YYYYMMDD'); }
function isLimitUp(t: string) { return t === 'U' || t.includes('涨停'); }
function isLimitDown(t: string) { return t === 'D' || t.includes('跌停'); }
function isBroken(t: string) { return t === 'Z' || t.includes('炸板'); }
const LT_LABEL: Record<string, { t: string; c: string }> = {
  U: { t: '涨停', c: 'red' }, D: { t: '跌停', c: 'green' }, Z: { t: '炸板', c: 'orange' },
  '涨停池': { t: '涨停', c: 'red' }, '跌停池': { t: '跌停', c: 'green' }, '炸板池': { t: '炸板', c: 'orange' },
};

const CARD_STYLE = { background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(148,186,215,0.12)' };

// ─── Market Temperature (C-Step4) ──────────────────────────────

function TemperaturePanel({ tradeDate }: { tradeDate: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['market-temperature', tradeDate],
    queryFn: () => api.marketTemperature(tradeDate),
    staleTime: 120_000,
  });

  if (isLoading) return <Spin />;
  const t = data?.data;
  if (!t) return <Empty description="暂无情绪数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />;

  const tempColor: Record<string, string> = {
    '极热': '#ef4444', '偏热': '#f97316', '中性': '#6bc7ff', '偏冷': '#22c55e', '冰点': '#16a34a',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Row gutter={12}>
        <Col span={4}>
          <Card size="small" style={CARD_STYLE}>
            <Statistic title="市场温度" value={t.temperature}
              valueStyle={{ color: tempColor[t.temperature] || '#6bc7ff', fontSize: 24, fontWeight: 700 }}
              prefix={<FireOutlined />} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={CARD_STYLE}>
            <Statistic title="涨停" value={t.limit_up} valueStyle={{ color: '#ef4444', fontSize: 20 }} suffix="家" />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={CARD_STYLE}>
            <Statistic title="跌停" value={t.limit_down} valueStyle={{ color: '#22c55e', fontSize: 20 }} suffix="家" />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={CARD_STYLE}>
            <Statistic title="炸板" value={t.broken} valueStyle={{ color: '#f59e0b', fontSize: 20 }} suffix="家" />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={CARD_STYLE}>
            <Statistic title="封板率" value={t.seal_rate} valueStyle={{ color: '#6bc7ff', fontSize: 20 }} suffix="%" />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={CARD_STYLE}>
            <Statistic title="最高板" value={t.max_board} valueStyle={{ color: '#f97316', fontSize: 20 }} suffix="板" />
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col span={12}>
          <Card size="small" title="连板天梯" style={CARD_STYLE}>
            {t.ladder.length ? t.ladder.map(l => (
              <div key={l.level} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <Tag color={l.level >= 5 ? 'red' : l.level >= 3 ? 'orange' : 'default'}>{l.level}板</Tag>
                <Progress percent={Math.min(l.count * 10, 100)} steps={10} size="small"
                  strokeColor={l.level >= 5 ? '#ef4444' : '#6bc7ff'}
                  format={() => `${l.count}只`} />
              </div>
            )) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无连板" />}
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title="游资概况" style={CARD_STYLE}>
            <Row gutter={8}>
              <Col span={12}>
                <Statistic title="活跃席位" value={t.hot_money.active_seats} valueStyle={{ fontSize: 16 }} />
              </Col>
              <Col span={12}>
                <Statistic title="涉及个股" value={t.hot_money.involved_stocks} valueStyle={{ fontSize: 16 }} />
              </Col>
              <Col span={12}>
                <Statistic title="总买入(亿)" valueStyle={{ fontSize: 14, color: '#ef4444' }}
                  value={t.hot_money.total_buy ? (t.hot_money.total_buy / 1e8).toFixed(2) : '-'} />
              </Col>
              <Col span={12}>
                <Statistic title="总卖出(亿)" valueStyle={{ fontSize: 14, color: '#22c55e' }}
                  value={t.hot_money.total_sell ? (t.hot_money.total_sell / 1e8).toFixed(2) : '-'} />
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>
    </div>
  );
}

// ─── Board Leaders (C-Step4) ───────────────────────────────────

const leaderColumns: ColumnsType<BoardLeaderItem> = [
  {
    title: '', dataIndex: 'label', width: 50,
    render: (v: string) => v ? <Tag color="red">{v}</Tag> : null,
  },
  { title: '代码', dataIndex: 'ts_code', width: 100 },
  { title: '名称', dataIndex: 'name', width: 90 },
  {
    title: '涨幅', dataIndex: 'pct_chg', width: 70, align: 'right',
    render: (v: number | null) => v != null ? <span style={{ color: '#ef4444' }}>{v.toFixed(2)}%</span> : '-',
  },
  {
    title: '封单(万)', dataIndex: 'limit_amount', width: 90, align: 'right',
    render: (v: number | null) => v != null ? (v / 10000).toFixed(0) : '-',
  },
  { title: '首封时间', dataIndex: 'first_lu_time', width: 100, ellipsis: true },
  { title: '开板次', dataIndex: 'open_num', width: 60, align: 'center' },
  { title: '标签', dataIndex: 'tag', width: 100, ellipsis: true },
  { title: '状态', dataIndex: 'status', width: 70 },
];

function BoardLeadersTab({ tradeDate }: { tradeDate: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['board-leaders', tradeDate],
    queryFn: () => api.boardLeaders(tradeDate),
  });

  return (
    <div>
      <div style={{ color: '#93a9bc', fontSize: 12, marginBottom: 8 }}>
        {data?.trade_date ? `数据日期: ${data.trade_date}` : ''} — 按首封时间排序，龙1为最早封板
      </div>
      <Table columns={leaderColumns} dataSource={data?.data ?? []} rowKey="ts_code"
        size="small" loading={isLoading} pagination={{ pageSize: 30, size: 'small' }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无龙头数据" /> }} />
    </div>
  );
}

// ─── Hot Money (C-Step4) ───────────────────────────────────────

function fmtHmAmt(v: number | null | undefined): string {
  if (v == null) return '-';
  const abs = Math.abs(v);
  if (abs >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (abs >= 1e4) return (v / 1e4).toFixed(0) + '万';
  return v.toFixed(0);
}

function HotMoneyStockTable({ stocks }: { stocks: HotMoneyItem['stocks'] }) {
  return (
    <Table
      dataSource={stocks} rowKey={(r) => r.ts_code} size="small" pagination={false}
      columns={[
        { title: '代码', dataIndex: 'ts_code', width: 90 },
        { title: '名称', dataIndex: 'name', width: 80 },
        { title: '买入', dataIndex: 'buy', width: 90, align: 'right',
          render: (v: number | null) => v ? <span style={{ color: '#ef4444' }}>{fmtHmAmt(v)}</span> : '-' },
        { title: '卖出', dataIndex: 'sell', width: 90, align: 'right',
          render: (v: number | null) => v ? <span style={{ color: '#22c55e' }}>{fmtHmAmt(v)}</span> : '-' },
        { title: '净买入', dataIndex: 'net', width: 100, align: 'right',
          render: (v: number | null) => v != null
            ? <span style={{ color: v >= 0 ? '#ef4444' : '#22c55e', fontWeight: 600 }}>{fmtHmAmt(v)}</span> : '-' },
        { title: '方向', dataIndex: 'net', width: 60, align: 'center', key: 'dir',
          render: (v: number | null) => {
            if (v == null) return '-';
            return v > 0
              ? <Tag color="red" style={{ margin: 0 }}>买</Tag>
              : v < 0 ? <Tag color="green" style={{ margin: 0 }}>卖</Tag>
              : <Tag style={{ margin: 0 }}>平</Tag>;
          },
        },
      ]}
    />
  );
}

const hotMoneyColumns: ColumnsType<HotMoneyItem> = [
  { title: '游资名称', dataIndex: 'hm_name', width: 140, ellipsis: true,
    render: (v: string) => <span style={{ fontWeight: 600, color: '#ffbf75' }}>{v}</span>,
  },
  { title: '个股', dataIndex: 'stock_count', width: 55, align: 'center',
    sorter: (a, b) => a.stock_count - b.stock_count,
  },
  {
    title: '买入', dataIndex: 'total_buy', width: 90, align: 'right',
    sorter: (a, b) => (a.total_buy ?? 0) - (b.total_buy ?? 0),
    render: (v: number | null) => v != null ? <span style={{ color: '#ef4444' }}>{fmtHmAmt(v)}</span> : '-',
  },
  {
    title: '卖出', dataIndex: 'total_sell', width: 90, align: 'right',
    render: (v: number | null) => v != null ? <span style={{ color: '#22c55e' }}>{fmtHmAmt(v)}</span> : '-',
  },
  {
    title: '净买', dataIndex: 'total_net', width: 90, align: 'right',
    sorter: (a, b) => (a.total_net ?? 0) - (b.total_net ?? 0),
    defaultSortOrder: 'descend',
    render: (v: number | null) => v != null
      ? <span style={{ color: v >= 0 ? '#ef4444' : '#22c55e', fontWeight: 600 }}>{fmtHmAmt(v)}</span> : '-',
  },
  {
    title: '操作概览', dataIndex: 'stocks', ellipsis: true,
    render: (stocks: HotMoneyItem['stocks']) => {
      if (!stocks?.length) return '-';
      const buys = stocks.filter(s => (s.net ?? 0) > 0);
      const sells = stocks.filter(s => (s.net ?? 0) < 0);
      return (
        <span style={{ fontSize: 12 }}>
          {buys.length > 0 && <span style={{ color: '#ef4444' }}>买 {buys.map(s => s.name).join('/')}</span>}
          {buys.length > 0 && sells.length > 0 && <span style={{ color: '#555' }}> | </span>}
          {sells.length > 0 && <span style={{ color: '#22c55e' }}>卖 {sells.map(s => s.name).join('/')}</span>}
        </span>
      );
    },
  },
];

function HotMoneyTab({ tradeDate }: { tradeDate: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['hot-money', tradeDate],
    queryFn: () => api.hotMoneySignal(tradeDate),
  });

  const items = data?.data ?? [];
  const totalNet = items.reduce((s, r) => s + (r.total_net ?? 0), 0);
  const totalBuy = items.reduce((s, r) => s + (r.total_buy ?? 0), 0);
  const totalSell = items.reduce((s, r) => s + (r.total_sell ?? 0), 0);
  const netBuyCount = items.filter(r => (r.total_net ?? 0) > 0).length;
  const netSellCount = items.filter(r => (r.total_net ?? 0) < 0).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div className="flex items-center" style={{ gap: 8 }}>
        <span style={{ color: '#93a9bc', fontSize: 12 }}>
          {data?.trade_date ? `数据日期: ${data.trade_date}` : ''}
        </span>
        <span style={{ color: '#93a9bc', fontSize: 12 }}>共 {items.length} 家游资</span>
      </div>

      <Row gutter={10}>
        <Col span={4}>
          <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <Statistic title="游资总买入" value={+(totalBuy / 1e8).toFixed(1)} suffix="亿" valueStyle={{ fontSize: 17, color: '#ef4444' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <Statistic title="游资总卖出" value={+(totalSell / 1e8).toFixed(1)} suffix="亿" valueStyle={{ fontSize: 17, color: '#22c55e' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <Statistic title="游资净买入" value={+(totalNet / 1e8).toFixed(1)} suffix="亿"
              valueStyle={{ fontSize: 17, color: totalNet >= 0 ? '#ef4444' : '#22c55e', fontWeight: 700 }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <Statistic title="净买入游资" value={netBuyCount} suffix="家" valueStyle={{ fontSize: 17, color: '#ef4444' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <Statistic title="净卖出游资" value={netSellCount} suffix="家" valueStyle={{ fontSize: 17, color: '#22c55e' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <Statistic title="活跃游资" value={items.length} suffix="家" valueStyle={{ fontSize: 17, color: '#6bc7ff' }} />
          </Card>
        </Col>
      </Row>

      <Table<HotMoneyItem>
        columns={hotMoneyColumns} dataSource={items} rowKey="hm_name"
        size="small" loading={isLoading} pagination={{ pageSize: 20, size: 'small' }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无游资数据" /> }}
        expandable={{
          expandedRowRender: (record) => <HotMoneyStockTable stocks={record.stocks} />,
          rowExpandable: (record) => record.stocks?.length > 0,
        }}
      />
    </div>
  );
}

// ─── Pre-market Three Columns ──────────────────────────────────

function PremarketThreeColumns({ watchlist, riskAlerts }: {
  watchlist: { ts_code: string; name: string; reason?: string; nums?: string | number; tag?: string | null; time?: string }[];
  riskAlerts: { ts_code: string; name: string; type: string; detail: string; tag?: string | null; time?: string }[];
}) {
  const [modalItem, setModalItem] = useState<{ title: string; content: string } | null>(null);

  const brokenAlerts = riskAlerts.filter((a) => a.type === '炸板');
  const negAlerts = riskAlerts.filter((a) => a.type !== '炸板');
  const boardWatch = [
    ...watchlist.filter((w) => !w.reason?.startsWith('利好消息')),
    ...brokenAlerts.map((a) => ({ ts_code: a.ts_code, name: a.name, reason: `炸板 ${a.detail}`, tag: a.tag })),
  ];
  const newsWatch = watchlist.filter((w) => w.reason?.startsWith('利好消息'));

  const colCard: React.CSSProperties = { ...CARD_STYLE, flex: '1 1 0', minWidth: 0, display: 'flex', flexDirection: 'column' };
  const scrollBody: React.CSSProperties = { flex: 1, overflowY: 'auto', maxHeight: 'calc(100vh - 340px)', minHeight: 300 };
  const descStyle: React.CSSProperties = {
    color: '#93a9bc', fontSize: 12, marginTop: 2,
    display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' as const,
    overflow: 'hidden', lineHeight: '18px', cursor: 'pointer',
  };

  return (
    <>
      <div style={{ display: 'flex', gap: 12 }}>
        <Card size="small" title={<><RiseOutlined style={{ color: '#ef4444' }} /> 今日关注 <Badge count={boardWatch.length} style={{ backgroundColor: '#ef4444', marginLeft: 6 }} /></>} style={colCard}>
          <div style={scrollBody}>
            {boardWatch.length ? (
              <List size="small" dataSource={boardWatch}
                renderItem={(item) => (
                  <List.Item>
                    <List.Item.Meta
                      title={<span>{item.ts_code} <span style={{ color: '#d1d5db' }}>{item.name}</span>
                        {'nums' in item && item.nums && <Tag color="orange" style={{ marginLeft: 6 }}>连板{item.nums}</Tag>}
                      </span>}
                      description={
                        <span style={descStyle} onClick={() => setModalItem({ title: `${item.ts_code} ${item.name}`, content: item.reason || '' })}>
                          {item.reason}
                        </span>
                      }
                    />
                  </List.Item>
                )} />
            ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无关注标的" />}
          </div>
        </Card>

        <Card size="small" title={<><FireOutlined style={{ color: '#22c55e' }} /> 利好股票 <Badge count={newsWatch.length} style={{ backgroundColor: '#22c55e', marginLeft: 6 }} /></>} style={colCard}>
          <div style={scrollBody}>
            {newsWatch.length ? (
              <List size="small" dataSource={newsWatch}
                renderItem={(item) => {
                  const text = item.reason?.replace('利好消息: ', '') || '';
                  return (
                    <List.Item>
                      <List.Item.Meta
                        title={
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span>{item.ts_code} <span style={{ color: '#d1d5db' }}>{item.name}</span></span>
                            {item.time && <span style={{ color: '#556677', fontSize: 11, flexShrink: 0 }}>{item.time}</span>}
                          </div>
                        }
                        description={
                          <span style={descStyle} onClick={() => setModalItem({ title: `${item.ts_code} ${item.name}`, content: text })}>
                            {text}
                          </span>
                        }
                      />
                    </List.Item>
                  );
                }} />
            ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无利好消息" />}
          </div>
        </Card>

        <Card size="small" title={<><WarningOutlined style={{ color: '#f59e0b' }} /> 利空股票 <Badge count={negAlerts.length} style={{ backgroundColor: '#f59e0b', marginLeft: 6 }} /></>} style={colCard}>
          <div style={scrollBody}>
            {negAlerts.length ? (
              <List size="small" dataSource={negAlerts}
                renderItem={(item) => (
                  <List.Item>
                    <List.Item.Meta
                      title={
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span>{item.ts_code} <span style={{ color: '#d1d5db' }}>{item.name}</span></span>
                          {item.time && <span style={{ color: '#556677', fontSize: 11, flexShrink: 0 }}>{item.time}</span>}
                        </div>
                      }
                      description={
                        <span style={descStyle} onClick={() => setModalItem({ title: `${item.ts_code} ${item.name}`, content: item.detail })}>
                          {item.detail}
                        </span>
                      }
                    />
                  </List.Item>
                )} />
            ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无利空消息" />}
          </div>
        </Card>
      </div>

      <Modal
        open={!!modalItem}
        title={modalItem?.title}
        onCancel={() => setModalItem(null)}
        footer={null}
        width={520}
      >
        <div style={{ fontSize: 14, lineHeight: 1.8, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
          {modalItem?.content}
        </div>
      </Modal>
    </>
  );
}

// ─── Pre-market Plan (C-Step5) ─────────────────────────────────

function PremarketTab({ tradeDate }: { tradeDate: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['premarket-plan', tradeDate],
    queryFn: () => api.premarketPlan(tradeDate),
    refetchInterval: 2 * 60 * 1000,
    staleTime: 30_000,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
  });

  if (isLoading) return <Spin />;
  if (!data) return <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />;

  const ms = data.market_summary;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Card size="small" title={`昨日市场概览 (${data.yesterday || '-'})`} style={CARD_STYLE}>
        {ms.limit_up != null ? (
          <Row gutter={12}>
            <Col span={4}><Statistic title="涨停" value={ms.limit_up} valueStyle={{ color: '#ef4444', fontSize: 16 }} /></Col>
            <Col span={4}><Statistic title="跌停" value={ms.limit_down} valueStyle={{ color: '#22c55e', fontSize: 16 }} /></Col>
            <Col span={4}><Statistic title="炸板" value={ms.broken} valueStyle={{ color: '#f59e0b', fontSize: 16 }} /></Col>
            <Col span={4}><Statistic title="封板率" value={`${ms.seal_rate}%`} valueStyle={{ fontSize: 16 }} /></Col>
            <Col span={4}><Statistic title="最高板" value={ms.max_board} valueStyle={{ color: '#f97316', fontSize: 16 }} /></Col>
            <Col span={4}>
              <div style={{ color: '#93a9bc', fontSize: 12, marginBottom: 4 }}>热门板块</div>
              {ms.hot_sectors?.slice(0, 3).map(s => (
                <Tag key={s.name} color="blue" style={{ marginBottom: 2 }}>{s.name} ({s.up_nums}只)</Tag>
              )) || '-'}
            </Col>
          </Row>
        ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无昨日数据" />}
      </Card>

      <PremarketThreeColumns watchlist={data.watchlist} riskAlerts={data.risk_alerts} />
    </div>
  );
}

// ─── Technical Analysis (D-Step1 + D-Step2) ────────────────────

function TechAnalysisTab({ tradeDate }: { tradeDate: string }) {
  const [code, setCode] = useState('');
  const [searchCode, setSearchCode] = useState('');

  const { data: volData, isLoading: volLoading } = useQuery({
    queryKey: ['tech-volume', searchCode, tradeDate],
    queryFn: () => api.techVolume(searchCode, tradeDate),
    enabled: !!searchCode,
  });
  const { data: gapData } = useQuery({
    queryKey: ['tech-gaps', searchCode, tradeDate],
    queryFn: () => api.techGaps(searchCode, tradeDate),
    enabled: !!searchCode,
  });
  const { data: srData } = useQuery({
    queryKey: ['tech-sr', searchCode],
    queryFn: () => api.techSupportResistance(searchCode),
    enabled: !!searchCode,
  });
  const { data: riskData } = useQuery({
    queryKey: ['tech-risk', searchCode, tradeDate],
    queryFn: () => api.techRiskCheck(searchCode, tradeDate),
    enabled: !!searchCode,
  });
  const { data: contData } = useQuery({
    queryKey: ['continuation', searchCode],
    queryFn: () => api.continuationAnalysis(searchCode),
    enabled: !!searchCode,
  });

  const handleSearch = () => {
    if (code.trim()) setSearchCode(code.trim().toUpperCase());
  };

  const volSignalLabel: Record<string, { text: string; color: string }> = {
    extreme_surge: { text: '极端放量', color: '#ef4444' },
    surge: { text: '显著放量', color: '#f97316' },
    normal: { text: '正常', color: '#6bc7ff' },
    shrink: { text: '缩量', color: '#22c55e' },
    extreme_shrink: { text: '极端缩量', color: '#16a34a' },
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <Input placeholder="输入股票代码 (如 000001.SZ)" value={code}
          onChange={e => setCode(e.target.value)} onPressEnter={handleSearch}
          style={{ width: 220 }} size="small" />
        <Button type="primary" size="small" icon={<SearchOutlined />} onClick={handleSearch}
          loading={volLoading}>分析</Button>
      </div>

      {!searchCode && <Empty description="请输入股票代码进行技术分析" image={Empty.PRESENTED_IMAGE_SIMPLE} />}

      {searchCode && riskData && riskData.warnings.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {riskData.warnings.map((w, i) => (
            <Alert key={i} type={w.level === 'high' ? 'error' : 'warning'}
              message={w.message} showIcon banner />
          ))}
        </div>
      )}

      {searchCode && volData?.data && (
        <Row gutter={12}>
          <Col span={8}>
            <Card size="small" title="量能分析" style={CARD_STYLE}>
              <Descriptions column={1} size="small">
                <Descriptions.Item label="今日成交量">
                  {volData.data.today_vol ? (volData.data.today_vol / 10000).toFixed(0) + ' 万手' : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="20日均量">
                  {volData.data.avg_vol_20d ? (volData.data.avg_vol_20d / 10000).toFixed(0) + ' 万手' : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="量比">
                  {volData.data.ratio != null
                    ? <Tag color={volSignalLabel[volData.data.signal]?.color || 'default'}>
                        {volData.data.ratio}x — {volSignalLabel[volData.data.signal]?.text || volData.data.signal}
                      </Tag>
                    : '-'}
                </Descriptions.Item>
              </Descriptions>
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small" title="支撑压力" style={CARD_STYLE}>
              {srData?.data ? (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="当前价">{srData.data.current_close}</Descriptions.Item>
                  <Descriptions.Item label="区间位置">
                    <Progress percent={srData.data.position_pct} size="small"
                      strokeColor={srData.data.position_pct > 80 ? '#ef4444' : srData.data.position_pct < 20 ? '#22c55e' : '#6bc7ff'} />
                  </Descriptions.Item>
                  <Descriptions.Item label="压力位">
                    {srData.data.resistance.map(p => <Tag key={p} color="red">{p}</Tag>)}
                    {!srData.data.resistance.length && '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="支撑位">
                    {srData.data.support.map(p => <Tag key={p} color="green">{p}</Tag>)}
                    {!srData.data.support.length && '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="均线">
                    MA5={srData.data.ma5 ?? '-'} MA10={srData.data.ma10 ?? '-'} MA20={srData.data.ma20 ?? '-'}
                  </Descriptions.Item>
                </Descriptions>
              ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无数据" />}
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small" title="缺口检测" style={CARD_STYLE}>
              {gapData?.gaps?.length ? (
                <List size="small" dataSource={gapData.gaps.slice(0, 5)} renderItem={(g) => (
                  <List.Item>
                    <Tag color={g.type === 'up' ? 'red' : 'green'}>{g.type === 'up' ? '向上' : '向下'}</Tag>
                    {g.trade_date} {g.gap_pct}%
                    {g.filled && <Tag color="default" style={{ marginLeft: 4 }}>已回补</Tag>}
                  </List.Item>
                )} />
              ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="近期无缺口" />}
            </Card>
          </Col>
        </Row>
      )}

      {searchCode && contData && contData.current_streak > 0 && (
        <Card size="small" title="连板延续分析" style={CARD_STYLE}>
          <Row gutter={12}>
            <Col span={4}>
              <Statistic title="当前连板" value={contData.current_streak} suffix="板"
                valueStyle={{ color: '#ff6f91', fontSize: 22, fontWeight: 700 }} />
            </Col>
            <Col span={4}>
              <Statistic title="历史最高" value={contData.max_streak} suffix="板"
                valueStyle={{ fontSize: 18 }} />
            </Col>
            <Col span={4}>
              <Statistic title="断板率" value={`${(contData.broken_rate * 100).toFixed(1)}%`}
                valueStyle={{ color: contData.broken_rate > 0.5 ? '#ef4444' : '#4ade80', fontSize: 18 }} />
            </Col>
            <Col span={4}>
              <Statistic title="涨停日" value={contData.total_limit_up_days} suffix="天"
                valueStyle={{ fontSize: 18 }} />
            </Col>
            <Col span={4}>
              <Statistic title="断板日" value={contData.total_broken_days} suffix="天"
                valueStyle={{ fontSize: 18 }} />
            </Col>
          </Row>
          {contData.recent_history?.length > 0 && (
            <Table
              style={{ marginTop: 10 }}
              dataSource={contData.recent_history.slice(0, 10)}
              rowKey={(r, i) => `${r.trade_date}-${i}`}
              size="small"
              pagination={false}
              columns={[
                { title: '日期', dataIndex: 'trade_date', width: 85 },
                { title: '状态', dataIndex: 'limit_type', width: 60,
                  render: (v: string) => <Tag color={v === 'U' ? 'red' : v === 'D' ? 'green' : 'default'}>{v === 'U' ? '涨停' : v === 'D' ? '跌停' : v}</Tag> },
                { title: '涨幅', dataIndex: 'pct_chg', width: 70, align: 'right',
                  render: (v: number | null) => v != null ? <span style={{ color: v >= 0 ? '#ff6f91' : '#4ade80' }}>{v.toFixed(2)}%</span> : '-' },
                { title: '炸板次数', dataIndex: 'open_num', width: 80, align: 'right',
                  render: (v: number | null) => v ?? '-' },
                { title: '首封时间', dataIndex: 'first_lu_time', width: 80, ellipsis: true },
              ]}
            />
          )}
        </Card>
      )}

      {searchCode && riskData && (
        <Card size="small" title="综合风险评估" style={CARD_STYLE}>
          <Badge status={riskData.risk_level === 'high' ? 'error' : riskData.risk_level === 'medium' ? 'warning' : 'success'}
            text={<span style={{ fontSize: 16, fontWeight: 600 }}>
              风险等级: {riskData.risk_level === 'high' ? '高' : riskData.risk_level === 'medium' ? '中' : '低'}
            </span>} />
          {!riskData.warnings.length && <span style={{ color: '#93a9bc', marginLeft: 12 }}>未发现技术面风险信号</span>}
        </Card>
      )}
    </div>
  );
}

// ─── Original Tabs (C-Step1~3 raw data) ────────────────────────

function LimitSummaryCards({ data }: { data: LimitBoardItem[] }) {
  const upCount = data.filter(d => isLimitUp(d.limit_type)).length;
  const downCount = data.filter(d => isLimitDown(d.limit_type)).length;
  const brokenCount = data.filter(d => isBroken(d.limit_type)).length;
  const sealRate = upCount > 0 ? ((upCount / (upCount + brokenCount)) * 100).toFixed(1) : '0';
  return (
    <Row gutter={12} style={{ marginBottom: 12 }}>
      <Col span={6}><Card size="small" style={CARD_STYLE}><Statistic title="涨停" value={upCount} valueStyle={{ color: '#ef4444', fontSize: 22 }} suffix="家" /></Card></Col>
      <Col span={6}><Card size="small" style={CARD_STYLE}><Statistic title="跌停" value={downCount} valueStyle={{ color: '#22c55e', fontSize: 22 }} suffix="家" /></Card></Col>
      <Col span={6}><Card size="small" style={CARD_STYLE}><Statistic title="炸板" value={brokenCount} valueStyle={{ color: '#f59e0b', fontSize: 22 }} suffix="家" /></Card></Col>
      <Col span={6}><Card size="small" style={CARD_STYLE}><Statistic title="封板率" value={sealRate} valueStyle={{ color: '#6bc7ff', fontSize: 22 }} suffix="%" /></Card></Col>
    </Row>
  );
}

const limitBoardColumns: ColumnsType<LimitBoardItem> = [
  { title: '代码', dataIndex: 'ts_code', width: 100 },
  { title: '名称', dataIndex: 'name', width: 90 },
  {
    title: '类型', dataIndex: 'limit_type', width: 60,
    render: (v: string) => {
      const s = LT_LABEL[v] || { t: v, c: 'default' };
      return <Tag color={s.c}>{s.t}</Tag>;
    },
  },
  {
    title: '涨跌幅', dataIndex: 'pct_chg', width: 80, align: 'right',
    render: (v: number | null) => v != null ? <span style={{ color: v >= 0 ? '#ef4444' : '#22c55e' }}>{v.toFixed(2)}%</span> : '-',
  },
  { title: '封单(万)', dataIndex: 'limit_amount', width: 90, align: 'right', render: (v: number | null) => v != null ? (v / 10000).toFixed(0) : '-' },
  { title: '换手率', dataIndex: 'turnover_rate', width: 70, align: 'right', render: (v: number | null) => v != null ? `${v.toFixed(1)}%` : '-' },
  { title: '标签', dataIndex: 'tag', width: 70 },
  { title: '状态', dataIndex: 'status', width: 70 },
  { title: '开板次', dataIndex: 'open_num', width: 60, align: 'center' },
  { title: '首封', dataIndex: 'first_lu_time', width: 100, ellipsis: true },
  { title: '末封', dataIndex: 'last_lu_time', width: 100, ellipsis: true },
];

const limitStepColumns: ColumnsType<LimitStepItem> = [
  {
    title: '连板', dataIndex: 'nums', width: 60, align: 'center',
    render: (v: string) => { const n = parseInt(v, 10); return <Tag color={n >= 5 ? 'red' : n >= 3 ? 'orange' : 'default'}>{n}板</Tag>; },
  },
  { title: '代码', dataIndex: 'ts_code', width: 100 },
  { title: '名称', dataIndex: 'name', width: 90 },
];

function fmtAmt(v: number | null | undefined): string {
  if (v == null) return '-';
  const abs = Math.abs(v);
  if (abs >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  return (v / 1e4).toFixed(0) + '万';
}

const dragonColumns: ColumnsType<DragonTigerItem> = [
  { title: '代码', dataIndex: 'ts_code', width: 90 },
  { title: '名称', dataIndex: 'name', width: 80 },
  {
    title: '涨跌幅', dataIndex: 'pct_change', width: 72, align: 'right',
    sorter: (a, b) => (a.pct_change ?? 0) - (b.pct_change ?? 0),
    render: (v: number | null) => v != null ? <span style={{ color: v >= 0 ? '#ef4444' : '#22c55e', fontWeight: 600 }}>{v >= 0 ? '+' : ''}{v.toFixed(2)}%</span> : '-',
  },
  { title: '成交额', dataIndex: 'amount', width: 85, align: 'right', render: (v: number | null) => fmtAmt(v) },
  { title: '买入', dataIndex: 'l_buy', width: 85, align: 'right', render: (v: number | null) => <span style={{ color: '#ef4444' }}>{fmtAmt(v)}</span> },
  { title: '卖出', dataIndex: 'l_sell', width: 85, align: 'right', render: (v: number | null) => <span style={{ color: '#22c55e' }}>{fmtAmt(v)}</span> },
  { title: '净额', dataIndex: 'net_amount', width: 85, align: 'right', sorter: (a, b) => (a.net_amount ?? 0) - (b.net_amount ?? 0),
    render: (v: number | null) => v != null ? <span style={{ color: v >= 0 ? '#ef4444' : '#22c55e', fontWeight: 600 }}>{fmtAmt(v)}</span> : '-' },
  { title: '净买率', dataIndex: 'net_rate', width: 68, align: 'right',
    render: (v: number | null) => v != null ? <span style={{ color: v >= 0 ? '#ef4444' : '#22c55e' }}>{v.toFixed(1)}%</span> : '-' },
  { title: '机构净额', dataIndex: 'inst_net', width: 85, align: 'right', sorter: (a, b) => (a.inst_net ?? 0) - (b.inst_net ?? 0),
    render: (v: number) => v ? <Tag color={v > 0 ? 'red' : 'green'} style={{ margin: 0 }}>{fmtAmt(v)}</Tag> : <span style={{ color: '#555' }}>-</span> },
  { title: '上榜原因', dataIndex: 'reason', ellipsis: true, width: 160 },
];

const hotColumns: ColumnsType<HotListItem> = [
  { title: '排名', dataIndex: 'rank', width: 60, align: 'center' },
  { title: '代码', dataIndex: 'ts_code', width: 100 },
  { title: '名称', dataIndex: 'ts_name', width: 90 },
  { title: '类型', dataIndex: 'data_type', width: 90 },
  {
    title: '涨跌幅', dataIndex: 'pct_change', width: 80, align: 'right',
    render: (v: number | null) => v != null ? <span style={{ color: v >= 0 ? '#ef4444' : '#22c55e' }}>{v.toFixed(2)}%</span> : '-',
  },
  { title: '现价', dataIndex: 'current_price', width: 80, align: 'right', render: (v: number | null) => v != null ? v.toFixed(2) : '-' },
];

function LimitBoardTab({ tradeDate }: { tradeDate: string }) {
  const [limitType, setLimitType] = useState('');
  const { data, isLoading } = useQuery({
    queryKey: ['limit-board', tradeDate, limitType],
    queryFn: () => api.limitBoard({ trade_date: tradeDate, limit_type: limitType }),
    refetchInterval: 60_000,
  });
  return (
    <div>
      {data?.data && <LimitSummaryCards data={data.data} />}
      <div className="flex items-center" style={{ gap: 8, marginBottom: 8 }}>
        <span style={{ color: '#93a9bc', fontSize: 12 }}>{data?.trade_date ? `数据日期: ${data.trade_date}` : ''}</span>
        <Tag style={{ cursor: 'pointer' }} color={!limitType ? 'blue' : 'default'} onClick={() => setLimitType('')}>全部</Tag>
        <Tag style={{ cursor: 'pointer' }} color={limitType === 'U' ? 'red' : 'default'} onClick={() => setLimitType('U')}>涨停</Tag>
        <Tag style={{ cursor: 'pointer' }} color={limitType === 'D' ? 'green' : 'default'} onClick={() => setLimitType('D')}>跌停</Tag>
        <Tag style={{ cursor: 'pointer' }} color={limitType === 'Z' ? 'orange' : 'default'} onClick={() => setLimitType('Z')}>炸板</Tag>
      </div>
      <Table columns={limitBoardColumns} dataSource={data?.data ?? []} rowKey={(r) => `${r.ts_code}-${r.limit_type}`}
        size="small" loading={isLoading} pagination={{ pageSize: 30, size: 'small' }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" /> }} />
    </div>
  );
}

function LimitStepTab({ tradeDate }: { tradeDate: string }) {
  const { data, isLoading } = useQuery({ queryKey: ['limit-step', tradeDate], queryFn: () => api.limitStep(tradeDate), refetchInterval: 60_000 });
  return (
    <div>
      <div style={{ color: '#93a9bc', fontSize: 12, marginBottom: 8 }}>{data?.trade_date ? `数据日期: ${data.trade_date}` : ''}</div>
      <Table columns={limitStepColumns} dataSource={data?.data ?? []} rowKey={(r) => `${r.ts_code}-${r.nums}`}
        size="small" loading={isLoading} pagination={{ pageSize: 30, size: 'small' }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无连板数据" /> }} />
    </div>
  );
}

function SeatDetail({ tsCode, tradeDate }: { tsCode: string; tradeDate: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['dragon-seats', tsCode, tradeDate],
    queryFn: () => api.dragonTigerSeats(tsCode, tradeDate),
    staleTime: 600_000,
  });
  if (isLoading) return <Spin size="small" />;
  const seatCols = [
    { title: '席位', dataIndex: 'exalter', ellipsis: true,
      render: (v: string, r: { seat_type: string; hm_name?: string | null }) => {
        const tag = r.seat_type === '机构'
          ? <Tag color="volcano" style={{ margin: '0 4px 0 0', fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>机构</Tag>
          : r.seat_type === '游资'
            ? <Tag color="orange" style={{ margin: '0 4px 0 0', fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>游资</Tag>
            : null;
        const hmLabel = r.hm_name ? <span style={{ color: '#ffbf75', fontSize: 11 }}> ({r.hm_name})</span> : null;
        return <span>{tag}{v}{hmLabel}</span>;
      },
    },
    { title: '买入', dataIndex: 'buy', width: 90, align: 'right' as const,
      render: (v: number | null) => v ? <span style={{ color: '#ef4444' }}>{fmtAmt(v)}</span> : '-' },
    { title: '卖出', dataIndex: 'sell', width: 90, align: 'right' as const,
      render: (v: number | null) => v ? <span style={{ color: '#22c55e' }}>{fmtAmt(v)}</span> : '-' },
    { title: '净买入', dataIndex: 'net_buy', width: 100, align: 'right' as const,
      render: (v: number | null) => v != null ? <span style={{ color: v >= 0 ? '#ef4444' : '#22c55e', fontWeight: 600 }}>{fmtAmt(v)}</span> : '-' },
  ];
  const buySeats = data?.buy_seats ?? [];
  const sellSeats = data?.sell_seats ?? [];
  const buyTotal = buySeats.reduce((s, r) => s + (r.buy ?? 0), 0);
  const sellTotal = sellSeats.reduce((s, r) => s + (r.sell ?? 0), 0);
  return (
    <div style={{ display: 'flex', gap: 16, padding: '4px 0' }}>
      <div style={{ flex: 1 }}>
        <div style={{ color: '#ef4444', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
          买方席位 TOP5 <span style={{ fontWeight: 400, color: '#93a9bc' }}>合计 {fmtAmt(buyTotal)}</span>
        </div>
        <Table dataSource={buySeats.slice(0, 5)} columns={seatCols} rowKey={(_, i) => `b${i}`}
          size="small" pagination={false} showHeader={false} />
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ color: '#22c55e', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
          卖方席位 TOP5 <span style={{ fontWeight: 400, color: '#93a9bc' }}>合计 {fmtAmt(sellTotal)}</span>
        </div>
        <Table dataSource={sellSeats.slice(0, 5)} columns={seatCols} rowKey={(_, i) => `s${i}`}
          size="small" pagination={false} showHeader={false} />
      </div>
    </div>
  );
}

function DragonTigerTab({ tradeDate }: { tradeDate: string }) {
  const { data, isLoading } = useQuery({ queryKey: ['dragon-tiger', tradeDate], queryFn: () => api.dragonTiger(tradeDate, 200), refetchInterval: 60_000 });
  const items = data?.data ?? [];

  // Summary cards
  const totalBuy = items.reduce((s, r) => s + (r.l_buy ?? 0), 0);
  const totalSell = items.reduce((s, r) => s + (r.l_sell ?? 0), 0);
  const totalNet = totalBuy - totalSell;
  const instNetTotal = items.reduce((s, r) => s + (r.inst_net ?? 0), 0);
  const instBuyCount = items.filter(r => (r.inst_net ?? 0) > 0).length;
  const instSellCount = items.filter(r => (r.inst_net ?? 0) < 0).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Summary */}
      <div>
        <div className="flex items-center" style={{ gap: 8, marginBottom: 8 }}>
          <span style={{ color: '#93a9bc', fontSize: 12 }}>{data?.trade_date ? `数据日期: ${data.trade_date}` : ''}</span>
          <span style={{ color: '#93a9bc', fontSize: 12 }}>共 {items.length} 只</span>
        </div>
        <Row gutter={10}>
          <Col span={4}>
            <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
              <Statistic title="龙虎买入" value={+(totalBuy / 1e8).toFixed(1)} suffix="亿" valueStyle={{ fontSize: 18, color: '#ef4444' }} />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
              <Statistic title="龙虎卖出" value={+(totalSell / 1e8).toFixed(1)} suffix="亿" valueStyle={{ fontSize: 18, color: '#22c55e' }} />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
              <Statistic title="龙虎净额" value={+(totalNet / 1e8).toFixed(1)} suffix="亿"
                valueStyle={{ fontSize: 18, color: totalNet >= 0 ? '#ef4444' : '#22c55e', fontWeight: 700 }} />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
              <Statistic title="机构净额" value={+(instNetTotal / 1e8).toFixed(1)} suffix="亿"
                valueStyle={{ fontSize: 18, color: instNetTotal >= 0 ? '#ef4444' : '#22c55e', fontWeight: 700 }} />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
              <Statistic title="机构净买" value={instBuyCount} suffix="只" valueStyle={{ fontSize: 18, color: '#ef4444' }} />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
              <Statistic title="机构净卖" value={instSellCount} suffix="只" valueStyle={{ fontSize: 18, color: '#22c55e' }} />
            </Card>
          </Col>
        </Row>
      </div>

      {/* Main table with expandable seat detail */}
      <Table<DragonTigerItem>
        columns={dragonColumns}
        dataSource={items}
        rowKey={(r) => `${r.ts_code}-dragon`}
        size="small"
        loading={isLoading}
        pagination={{ pageSize: 30, size: 'small' }}
        scroll={{ x: 900 }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无龙虎榜数据" /> }}
        expandable={{
          expandedRowRender: (record) => (
            <SeatDetail tsCode={record.ts_code} tradeDate={record.trade_date} />
          ),
          rowExpandable: () => true,
        }}
      />
    </div>
  );
}

function HotListTab({ tradeDate }: { tradeDate: string }) {
  const { data, isLoading } = useQuery({ queryKey: ['hot-list', tradeDate], queryFn: () => api.hotList(tradeDate), refetchInterval: 60_000 });
  return (
    <div>
      <div style={{ color: '#93a9bc', fontSize: 12, marginBottom: 8 }}>{data?.trade_date ? `数据日期: ${data.trade_date}` : ''}</div>
      <Table columns={hotColumns} dataSource={data?.data ?? []} rowKey={(r) => `${r.ts_code}-hot`}
        size="small" loading={isLoading} pagination={{ pageSize: 30, size: 'small' }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无热榜数据" /> }} />
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────

export default function SentimentPage() {
  const [dateOverride, setDateOverride] = useState<Dayjs | null>(null);

  const date = dateOverride ?? dayjs();
  const setDate = (d: Dayjs) => setDateOverride(d);
  const tradeDate = fmtDate(date);

  return (
    <div className="flex flex-col h-full overflow-auto" style={{ padding: 18, gap: 12 }}>
      <div className="flex items-center" style={{ gap: 12 }}>
        <span style={{ color: '#93a9bc', fontSize: 13 }}>选择日期:</span>
        <DatePicker value={date} onChange={(d) => d && setDate(d)} allowClear={false} size="small" style={{ width: 140 }} />
        <Tag color="blue" style={{ cursor: 'pointer', marginLeft: 4 }}
          onClick={() => setDate(dayjs())}>
          今天
        </Tag>
      </div>
      <Panel className="flex-1" noPadding>
        <Tabs defaultActiveKey="temperature" style={{ height: '100%', padding: '0 10px' }}
          items={[
            { key: 'temperature', label: <><FireOutlined /> 市场温度</>, children: <TemperaturePanel tradeDate={tradeDate} /> },
            { key: 'premarket', label: <><ThunderboltOutlined /> 盘前计划</>, children: <PremarketTab tradeDate={tradeDate} /> },
            { key: 'leaders', label: '板块龙头', children: <BoardLeadersTab tradeDate={tradeDate} /> },
            { key: 'hot-money', label: '游资动向', children: <HotMoneyTab tradeDate={tradeDate} /> },
            { key: 'tech', label: <><SearchOutlined /> 个股技术</>, children: <TechAnalysisTab tradeDate={tradeDate} /> },
            { key: 'limit-board', label: '涨跌停榜', children: <LimitBoardTab tradeDate={tradeDate} /> },
            { key: 'limit-step', label: '连板天梯', children: <LimitStepTab tradeDate={tradeDate} /> },
            { key: 'dragon-tiger', label: '龙虎榜', children: <DragonTigerTab tradeDate={tradeDate} /> },
            { key: 'hot-list', label: '市场热榜', children: <HotListTab tradeDate={tradeDate} /> },
          ]}
        />
      </Panel>
    </div>
  );
}
