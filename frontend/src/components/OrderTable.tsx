import { useState } from 'react';
import { Table, Tag, Button, Modal, InputNumber, Form, Space, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type SimOrder } from '../services/api';

const statusMap: Record<string, { color: string; text: string }> = {
  PENDING: { color: 'blue', text: '待成交' },
  SUBMITTED: { color: 'blue', text: '已提交' },
  PARTIAL_FILLED: { color: 'orange', text: '部分成交' },
  FILLED: { color: 'green', text: '已成交' },
  CANCELED: { color: 'default', text: '已撤单' },
  REJECTED: { color: 'red', text: '已拒绝' },
};

export default function OrderTable() {
  const qc = useQueryClient();
  const [modifyTarget, setModifyTarget] = useState<SimOrder | null>(null);
  const [form] = Form.useForm();

  const { data } = useQuery({
    queryKey: ['orders'],
    queryFn: () => api.listOrders(),
    refetchInterval: 3000,
  });

  const cancelMut = useMutation({
    mutationFn: (id: string) => api.cancelOrder(id),
    onSuccess: () => {
      message.success('撤单成功');
      qc.invalidateQueries({ queryKey: ['orders'] });
      qc.invalidateQueries({ queryKey: ['account'] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const modifyMut = useMutation({
    mutationFn: async ({ oldOrder, newPrice, newQty }: {
      oldOrder: SimOrder; newPrice: number; newQty: number;
    }) => {
      await api.cancelOrder(oldOrder.order_id);
      return api.submitOrder({
        ts_code: oldOrder.ts_code,
        side: oldOrder.side,
        order_type: 'LIMIT',
        price: newPrice,
        qty: newQty,
      });
    },
    onSuccess: () => {
      message.success('改单成功');
      qc.invalidateQueries({ queryKey: ['orders'] });
      qc.invalidateQueries({ queryKey: ['account'] });
      setModifyTarget(null);
    },
    onError: (e: Error) => message.error(e.message),
  });

  const handleModifyOk = () => {
    if (!modifyTarget) return;
    form.validateFields().then((vals) => {
      modifyMut.mutate({
        oldOrder: modifyTarget,
        newPrice: vals.price,
        newQty: vals.qty,
      });
    });
  };

  const columns: ColumnsType<SimOrder> = [
    {
      title: '时间', dataIndex: 'created_at', width: 80,
      render: (v: string) => v ? new Date(v).toLocaleTimeString('zh-CN', { hour12: false }) : '',
    },
    { title: '代码', dataIndex: 'ts_code', width: 100 },
    {
      title: '方向', dataIndex: 'side', width: 60,
      render: (v: string) => (
        <Tag color={v === 'BUY' ? 'red' : 'green'} variant="filled" style={{ fontSize: 11, margin: 0 }}>
          {v === 'BUY' ? '买入' : '卖出'}
        </Tag>
      ),
    },
    {
      title: '价格', dataIndex: 'price', width: 80, align: 'right',
      render: (v: number | null) => v != null ? v.toFixed(2) : 'MKT',
    },
    { title: '委托', dataIndex: 'qty', width: 60, align: 'right' },
    { title: '成交', dataIndex: 'filled_qty', width: 60, align: 'right' },
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: (v: string) => {
        const s = statusMap[v] || { color: 'default', text: v };
        return <Tag color={s.color} variant="filled" style={{ fontSize: 11, margin: 0 }}>{s.text}</Tag>;
      },
    },
    {
      title: '操作', width: 100, align: 'center',
      render: (_: unknown, record: SimOrder) => {
        const canAct = ['PENDING', 'SUBMITTED', 'PARTIAL_FILLED'].includes(record.status);
        const isLimit = record.order_type === 'LIMIT';
        if (!canAct) return null;
        return (
          <Space size={4}>
            <Button size="small" danger onClick={() => cancelMut.mutate(record.order_id)}
                    style={{ fontSize: 11, height: 22 }}>
              撤单
            </Button>
            {isLimit && (
              <Button size="small" onClick={() => {
                setModifyTarget(record);
                form.setFieldsValue({ price: record.price, qty: record.qty });
              }} style={{ fontSize: 11, height: 22 }}>
                改单
              </Button>
            )}
          </Space>
        );
      },
    },
  ];

  return (
    <>
      <Table
        columns={columns}
        dataSource={data?.data ?? []}
        rowKey="order_id"
        size="small"
        pagination={false}
      />
      <Modal
        title={`改单 · ${modifyTarget?.ts_code ?? ''}`}
        open={!!modifyTarget}
        onCancel={() => setModifyTarget(null)}
        footer={null}
        destroyOnClose
        width={340}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item name="price" label="新价格" rules={[{ required: true }]}>
            <InputNumber min={0.01} step={0.01} precision={2} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="qty" label="新数量" rules={[{ required: true }]}>
            <InputNumber min={100} step={100} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0, textAlign: 'right' }}>
            <Space>
              <Button onClick={() => setModifyTarget(null)}>取消</Button>
              <Button type="primary" onClick={handleModifyOk} loading={modifyMut.isPending}>
                确认改单
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
