import { useState } from 'react';
import { Button, Switch, Tag, Space, InputNumber, Input, Modal, Form, message } from 'antd';
import { PlayCircleOutlined, PauseCircleOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import Panel from '../components/Panel';

const AVAILABLE = [
  {
    name: 'ma_crossover',
    label: 'MA 金叉/死叉',
    desc: '快速MA上穿慢速MA买入，下穿卖出',
    params: { fast_period: 5, slow_period: 20, position_pct: 0.25 },
  },
];

export default function StrategyPage() {
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
    <div className="flex flex-col h-full" style={{ padding: 18, gap: 12 }}>
      <Panel title="策略管理" className="flex-1">
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
                  transition: 'border-color 120ms ease, background 120ms ease',
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
                        form.setFieldsValue({
                          ...s.params,
                          codes: '000001.SZ',
                        });
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
      </Panel>

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
    </div>
  );
}
