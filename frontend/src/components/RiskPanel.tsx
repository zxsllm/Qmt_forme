import { Table, Tag, Button } from 'antd';
import { WarningOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { mockRiskRules, type RiskRule } from '../services/mockData';
import Panel from './Panel';

const statusMap: Record<string, [string, string]> = {
  normal: ['success', '正常'],
  warning: ['warning', '预警'],
  triggered: ['error', '触发'],
};

const columns: ColumnsType<RiskRule> = [
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
  return (
    <Panel
      title="风控状态"
      secondary={secondary}
      extra={
        <Button danger size="small" icon={<WarningOutlined />} style={{ fontSize: 11, height: 24 }}>
          Kill
        </Button>
      }
      className={className}
      noPadding
    >
      <Table
        columns={columns}
        dataSource={mockRiskRules}
        rowKey="name"
        size="small"
        pagination={false}
      />
    </Panel>
  );
}
