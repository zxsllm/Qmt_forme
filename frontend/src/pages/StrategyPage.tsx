import { useState } from 'react';
import {
  Button, Tag, Space, InputNumber, Input, Modal, Form, message,
  Select, Table, Spin, Tabs,
} from 'antd';
import { PlayCircleOutlined, PauseCircleOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type BacktestRunResult, type BacktestStats, type TradeRecord } from '../services/api';
import Panel from '../components/Panel';

const AVAILABLE = [
  {
    name: 'ma_crossover',
    label: 'MA 金叉/死叉',
    desc: '快速MA上穿慢速MA买入，下穿卖出',
    params: { fast_period: 5, slow_period: 20, position_pct: 0.25 },
  },
];

// ── Strategy Management Tab ──────────────────────────────────

function StrategyManageTab() {
  const qc = useQueryClient();
  const [configTarget, setConfigTarget] = useState<typeof AVAILABLE[0] | null>(null);
  const [form] = Form.useForm();

  const { data: status } = useQuery({
    queryKey: ['strategy-runner'],
    queryFn: api.getRunningStrategies,
    refetchInterval: 3000,
  });

  const runningMap = new Map(
    status?.strategies?.map((s) => [s.name, s]) ?? [],
  );

  const startMut = useMutation({
    mutationFn: (body: { strategy_name: string; params: Record<string, unknown>; codes: string[] }) =>
      api.startStrategy(body),
    onSuccess: () => {
      message.success('策略已启动');
      qc.invalidateQueries({ queryKey: ['strategy-runner'] });
      setConfigTarget(null);
    },
    onError: (e: Error) => message.error(e.message),
  });

  const stopMut = useMutation({
    mutationFn: (name: string) => api.stopStrategy(name),
    onSuccess: () => {
      message.success('策略已停止');
      qc.invalidateQueries({ queryKey: ['strategy-runner'] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const handleStart = () => {
    if (!configTarget) return;
    form.validateFields().then((vals) => {
      const codes = (vals.codes as string).split(',').map((c: string) => c.trim()).filter(Boolean);
      startMut.mutate({
        strategy_name: configTarget.name,
        params: { fast_period: vals.fast_period, slow_period: vals.slow_period, position_pct: vals.position_pct },
        codes,
      });
    });
  };

  return (
    <>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14 }}>
        {AVAILABLE.map((s) => {
          const running = runningMap.get(s.name);
          return (
            <div
              key={s.name}
              style={{
                width: 340,
                padding: 18,
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid rgba(148,186,215,0.14)',
                borderRadius: 18,
              }}
            >
              <div className="flex items-center justify-between" style={{ marginBottom: 10 }}>
                <span style={{ color: '#e6f1fa', fontWeight: 600, fontSize: 14 }}>{s.label}</span>
                {running ? (
                  <Tag color="green">运行中</Tag>
                ) : (
                  <Tag color="default">已停止</Tag>
                )}
              </div>
              <div style={{ color: '#93a9bc', fontSize: 12, marginBottom: 14 }}>{s.desc}</div>
              {running && (
                <div style={{ fontSize: 11, color: '#64748b', marginBottom: 10 }}>
                  信号: {running.signals_today} 今日 / {running.total_signals} 总计
                  · {running.total_codes} 只股票
                </div>
              )}
              <Space>
                {running ? (
                  <Button
                    size="small" danger
                    icon={<PauseCircleOutlined />}
                    onClick={() => stopMut.mutate(s.name)}
                    loading={stopMut.isPending}
                  >
                    停止
                  </Button>
                ) : (
                  <Button
                    size="small" type="primary"
                    icon={<PlayCircleOutlined />}
                    onClick={() => {
                      setConfigTarget(s);
                      form.setFieldsValue({ ...s.params, codes: '000001.SZ' });
                    }}
                  >
                    配置启动
                  </Button>
                )}
              </Space>
            </div>
          );
        })}
      </div>

      <Modal
        title={`启动策略 · ${configTarget?.label ?? ''}`}
        open={!!configTarget}
        onCancel={() => setConfigTarget(null)}
        footer={null}
        destroyOnClose
        width={400}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item name="fast_period" label="快线周期">
            <InputNumber min={2} max={120} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="slow_period" label="慢线周期">
            <InputNumber min={5} max={250} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="position_pct" label="仓位比例">
            <InputNumber min={0.01} max={1} step={0.05} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="codes" label="股票代码 (逗号分隔)">
            <Input placeholder="000001.SZ, 600519.SH" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0, textAlign: 'right' }}>
            <Space>
              <Button onClick={() => setConfigTarget(null)}>取消</Button>
              <Button type="primary" onClick={handleStart} loading={startMut.isPending}>
                启动
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ── Backtest Tab ─────────────────────────────────────────────

const formatPct = (v: number | null | undefined) => {
  if (v == null || isNaN(v)) return '--';
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
};
const formatNum = (v: number | null | undefined) => {
  if (v == null || isNaN(v)) return '--';
  return v.toFixed(2);
};

function BacktestTab() {
  const [result, setResult] = useState<BacktestRunResult | null>(null);
  const [viewRunId, setViewRunId] = useState<string | null>(null);
  const qc = useQueryClient();

  const { data: strategies } = useQuery({
    queryKey: ['strategies'],
    queryFn: api.listStrategies,
  });

  const { data: history, isLoading: histLoading } = useQuery({
    queryKey: ['backtest-history'],
    queryFn: () => api.listBacktestRuns(20),
    staleTime: 10_000,
  });

  const { data: detailResult } = useQuery({
    queryKey: ['backtest-detail', viewRunId],
    queryFn: () => api.getBacktestResult(viewRunId!),
    enabled: !!viewRunId,
  });

  const mutation = useMutation({
    mutationFn: api.runBacktest,
    onSuccess: (data) => {
      setResult(data);
      qc.invalidateQueries({ queryKey: ['backtest-history'] });
      message.success(`回测完成：${data.stats.total_trades} 笔交易`);
    },
    onError: (err: Error) => message.error(`回测失败：${err.message}`),
  });

  const onFinish = (values: Record<string, unknown>) => {
    const universeStr = values.universe as string || '';
    mutation.mutate({
      strategy_name: values.strategy_name as string,
      strategy_params: strategies?.find(s => s.name === values.strategy_name)?.default_params || {},
      start_date: values.start_date as string,
      end_date: values.end_date as string,
      initial_capital: (values.initial_capital as number) || 1_000_000,
      benchmark: (values.benchmark as string) || '000300.SH',
      universe: universeStr ? universeStr.split(',').map(s => s.trim()) : [],
    });
  };

  const activeResult = viewRunId ? detailResult : result;

  return (
    <div style={{ display: 'flex', gap: 14 }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Form layout="inline" onFinish={onFinish} initialValues={{
          strategy_name: 'ma_crossover',
          start_date: '20260101',
          end_date: '20260320',
          initial_capital: 1000000,
          benchmark: '000300.SH',
          universe: '000001.SZ,600519.SH',
        }}>
          <Form.Item name="strategy_name" label="策略" rules={[{ required: true }]}>
            <Select style={{ width: 160 }}>
              {strategies?.map(s => (
                <Select.Option key={s.name} value={s.name}>{s.description || s.name}</Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="start_date" label="开始" rules={[{ required: true }]}>
            <Input style={{ width: 100 }} placeholder="YYYYMMDD" />
          </Form.Item>
          <Form.Item name="end_date" label="结束" rules={[{ required: true }]}>
            <Input style={{ width: 100 }} placeholder="YYYYMMDD" />
          </Form.Item>
          <Form.Item name="initial_capital" label="初始资金">
            <InputNumber style={{ width: 120 }} min={10000} step={100000} />
          </Form.Item>
          <Form.Item name="universe" label="股票池">
            <Input style={{ width: 240 }} placeholder="000001.SZ,600519.SH (空=全市场)" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={mutation.isPending}>
              运行回测
            </Button>
          </Form.Item>
        </Form>

        {mutation.isPending && (
          <div className="flex flex-col items-center justify-center py-12" style={{ gap: 12 }}>
            <Spin size="large" />
            <div style={{ color: '#93a9bc', fontSize: 13 }}>回测运行中，请耐心等待...</div>
          </div>
        )}

        {activeResult && <ResultPanel result={activeResult} />}
      </div>

      <div style={{
        width: 280, flexShrink: 0, borderLeft: '1px solid rgba(148,186,215,0.10)',
        paddingLeft: 14, display: 'flex', flexDirection: 'column', gap: 6,
      }}>
        <div style={{ color: '#93a9bc', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>回测历史</div>
        {histLoading && <Spin size="small" />}
        {(history ?? []).map(run => (
          <div
            key={run.run_id}
            onClick={() => { setViewRunId(run.run_id); setResult(null); }}
            style={{
              padding: '8px 10px', borderRadius: 10, cursor: 'pointer',
              background: viewRunId === run.run_id ? 'rgba(107,199,255,0.12)' : 'rgba(255,255,255,0.02)',
              border: `1px solid ${viewRunId === run.run_id ? 'rgba(107,199,255,0.3)' : 'rgba(148,186,215,0.08)'}`,
              transition: 'all 150ms',
            }}
          >
            <div className="flex items-center justify-between">
              <span style={{ fontSize: 12, fontWeight: 600, color: '#e6f1fa' }}>{run.strategy_name}</span>
              <Tag color={run.status === 'completed' ? 'green' : run.status === 'error' ? 'red' : 'blue'}
                style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                {run.status === 'completed' ? '完成' : run.status === 'error' ? '失败' : run.status}
              </Tag>
            </div>
            <div style={{ fontSize: 10, color: '#93a9bc', marginTop: 2 }}>
              {run.started_at?.replace('T', ' ').slice(0, 19)}
            </div>
            {run.stats && (
              <div className="flex gap-3" style={{ marginTop: 3, fontSize: 10 }}>
                <span style={{ color: (run.stats.total_return ?? 0) >= 0 ? '#ff6f91' : '#4ade80' }}>
                  收益 {formatPct(run.stats.total_return)}
                </span>
                <span style={{ color: '#93a9bc' }}>
                  夏普 {formatNum(run.stats.sharpe_ratio)}
                </span>
              </div>
            )}
          </div>
        ))}
        {!histLoading && (!history || history.length === 0) && (
          <div style={{ color: '#4b5563', fontSize: 11, textAlign: 'center', padding: 20 }}>暂无历史记录</div>
        )}
      </div>
    </div>
  );
}

function ResultPanel({ result }: { result: BacktestRunResult }) {
  const s = result.stats;
  return (
    <>
      <StatsCards stats={s} />
      <EquityCurveTable equity={result.equity_curve} />
      <TradesTable trades={result.trades} />
    </>
  );
}

function StatsCards({ stats }: { stats: BacktestStats }) {
  const items: { label: string; value: string; color?: string }[] = [
    { label: '总收益', value: formatPct(stats.total_return), color: stats.total_return >= 0 ? '#ff6f91' : '#4ade80' },
    { label: '年化收益', value: formatPct(stats.annual_return), color: stats.annual_return >= 0 ? '#ff6f91' : '#4ade80' },
    { label: '最大回撤', value: formatPct(stats.max_drawdown), color: '#4ade80' },
    { label: '夏普比率', value: formatNum(stats.sharpe_ratio) },
    { label: '索提诺', value: formatNum(stats.sortino_ratio) },
    { label: '胜率', value: formatPct(stats.win_rate) },
    { label: '盈亏比', value: formatNum(stats.profit_factor) },
    { label: '交易次数', value: String(stats.total_trades) },
    { label: '平均持仓', value: `${stats.avg_holding_days}天` },
    { label: '基准收益', value: formatPct(stats.benchmark_return) },
  ];

  return (
    <div className="grid grid-cols-5" style={{ gap: 10 }}>
      {items.map(item => (
        <div
          key={item.label}
          style={{
            padding: '10px 14px',
            textAlign: 'center',
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(148,186,215,0.12)',
            borderRadius: 16,
          }}
        >
          <div style={{ fontSize: 11, color: '#93a9bc', marginBottom: 4, letterSpacing: '0.04em' }}>
            {item.label}
          </div>
          <div style={{ fontSize: 16, fontWeight: 600, color: item.color || '#e6f1fa' }}>
            {item.value}
          </div>
        </div>
      ))}
    </div>
  );
}

function EquityCurveTable({ equity }: { equity: BacktestRunResult['equity_curve'] }) {
  const columns = [
    { title: '日期', dataIndex: 'date', key: 'date', width: 100 },
    { title: '总资产', dataIndex: 'total_asset', key: 'total_asset', render: formatNum, width: 120 },
    { title: '现金', dataIndex: 'cash', key: 'cash', render: formatNum, width: 120 },
    { title: '市值', dataIndex: 'market_value', key: 'market_value', render: formatNum, width: 120 },
    {
      title: '日收益', dataIndex: 'daily_return', key: 'daily_return', width: 90,
      render: (v: number) => (
        <span style={{ color: v >= 0 ? '#ff6f91' : '#4ade80' }}>
          {(v * 100).toFixed(2)}%
        </span>
      ),
    },
  ];

  return (
    <Panel title="权益曲线" noPadding>
      <Table
        dataSource={equity}
        columns={columns}
        rowKey="date"
        size="small"
        pagination={{ pageSize: 15, size: 'small' }}
        scroll={{ y: 300 }}
      />
    </Panel>
  );
}

function TradesTable({ trades }: { trades: TradeRecord[] }) {
  const columns = [
    { title: '信号日', dataIndex: 'signal_date', key: 'signal_date', width: 90 },
    { title: '成交日', dataIndex: 'trade_date', key: 'trade_date', width: 90 },
    { title: '代码', dataIndex: 'ts_code', key: 'ts_code', width: 100 },
    {
      title: '方向', dataIndex: 'side', key: 'side', width: 60,
      render: (v: string) => <Tag color={v === 'BUY' ? 'red' : 'green'}>{v}</Tag>,
    },
    { title: '价格', dataIndex: 'price', key: 'price', render: formatNum, width: 80 },
    { title: '数量', dataIndex: 'qty', key: 'qty', width: 80 },
    { title: '金额', dataIndex: 'amount', key: 'amount', render: formatNum, width: 110 },
    { title: '手续费', dataIndex: 'fee', key: 'fee', render: formatNum, width: 80 },
    { title: '原因', dataIndex: 'reason', key: 'reason', ellipsis: true },
  ];

  return (
    <Panel title={`交易明细 (${trades.length}笔)`} noPadding>
      <Table
        dataSource={trades}
        columns={columns}
        rowKey={(_, i) => String(i)}
        size="small"
        pagination={{ pageSize: 15, size: 'small' }}
        scroll={{ y: 300 }}
      />
    </Panel>
  );
}

// ── Main Page ────────────────────────────────────────────────

export default function StrategyPage() {
  return (
    <div className="flex flex-col h-full overflow-auto" style={{ padding: 18, gap: 12 }}>
      <Panel className="flex-1" noPadding>
        <Tabs
          defaultActiveKey="manage"
          style={{ height: '100%', padding: '0 10px' }}
          items={[
            { key: 'manage', label: '策略管理', children: <StrategyManageTab /> },
            { key: 'backtest', label: '回测', children: <BacktestTab /> },
          ]}
        />
      </Panel>
    </div>
  );
}
