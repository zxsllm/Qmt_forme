import { useState } from 'react';
import {
  Button, Form, Input, InputNumber, Select, Table, Spin, message, Tag,
} from 'antd';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api, type BacktestRunResult, type BacktestStats, type TradeRecord } from '../services/api';
import Panel from '../components/Panel';

const formatPct = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
const formatNum = (v: number) => v.toFixed(2);

export default function BacktestPage() {
  const [result, setResult] = useState<BacktestRunResult | null>(null);

  const { data: strategies } = useQuery({
    queryKey: ['strategies'],
    queryFn: api.listStrategies,
  });

  const mutation = useMutation({
    mutationFn: api.runBacktest,
    onSuccess: (data) => {
      setResult(data);
      message.success(`回测完成：${data.stats.total_trades} 笔交易`);
    },
    onError: (err: Error) => {
      message.error(`回测失败：${err.message}`);
    },
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

  return (
    <div className="flex flex-col h-full overflow-auto" style={{ padding: 18, gap: 12 }}>
      <Panel className="shrink-0">
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
      </Panel>

      {mutation.isPending && (
        <div className="flex items-center justify-center py-12">
          <Spin size="large" tip="回测运行中..." />
        </div>
      )}

      {result && <ResultPanel result={result} />}
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
