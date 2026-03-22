import { Table, Tag, Button } from 'antd';
import { WarningOutlined, CheckCircleOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/api';
import Panel from './Panel';

interface RiskRow {
  name: string;
  status: 'normal' | 'warning' | 'triggered';
  value: string;
  threshold: string;
}

const statusMap: Record<string, [string, string]> = {
  normal: ['success', '正常'],
  warning: ['warning', '预警'],
  triggered: ['error', '触发'],
};

const columns: ColumnsType<RiskRow> = [
  { title: '规则', dataIndex: 'name', width: 120 },
  {
    title: '状态', dataIndex: 'status', width: 60,
    render: (v: string) => {
      const [c, t] = statusMap[v] || ['default', v];
      return <Tag color={c} variant="filled" style={{ fontSize: 11, margin: 0 }}>{t}</Tag>;
    },
  },
  { title: '当前值', dataIndex: 'value', width: 65, align: 'right' },
  { title: '阈值', dataIndex: 'threshold', width: 65, align: 'right' },
];

export default function RiskPanel({ className = '', secondary = false }: { className?: string; secondary?: boolean }) {
  const qc = useQueryClient();
  const { data: risk } = useQuery({
    queryKey: ['risk-status'],
    queryFn: api.getRiskStatus,
    refetchInterval: 3000,
  });

  const killOn = useMutation({
    mutationFn: () => api.activateKillSwitch('manual') as Promise<unknown>,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['risk-status'] }),
  });
  const killOff = useMutation({
    mutationFn: () => api.deactivateKillSwitch() as Promise<unknown>,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['risk-status'] }),
  });

  const ksActive = risk?.kill_switch?.active ?? false;

  const rows: RiskRow[] = [
    {
      name: 'Kill Switch',
      status: ksActive ? 'triggered' : 'normal',
      value: ksActive ? 'ON' : 'OFF',
      threshold: '手动',
    },
    {
      name: '盘中熔断',
      status: risk?.realtime_halted ? 'triggered' : 'normal',
      value: risk?.realtime_halted ? '已触发' : '正常',
      threshold: '-5%',
    },
    {
      name: '当日买入次数',
      status: (risk?.daily_buy_count ?? 0) >= 18 ? 'warning' : 'normal',
      value: String(risk?.daily_buy_count ?? 0),
      threshold: '≤20',
    },
  ];

  return (
    <Panel
      title="风控状态"
      secondary={secondary}
      extra={
        ksActive ? (
          <Button size="small" icon={<CheckCircleOutlined />}
                  onClick={() => killOff.mutate()}
                  style={{ fontSize: 11, height: 24 }}>
            解除
          </Button>
        ) : (
          <Button danger size="small" icon={<WarningOutlined />}
                  onClick={() => killOn.mutate()}
                  style={{ fontSize: 11, height: 24 }}>
            Kill
          </Button>
        )
      }
      className={className}
      noPadding
    >
      <Table
        columns={columns}
        dataSource={rows}
        rowKey="name"
        size="small"
        pagination={false}
      />
    </Panel>
  );
}
