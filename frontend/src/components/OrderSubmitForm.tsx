import { useState, useCallback, useRef } from 'react';
import {
  Modal, Form, AutoComplete, InputNumber, Radio, Button, Space, message,
} from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type SubmitOrderBody } from '../services/api';

interface Props {
  open: boolean;
  onClose: () => void;
  /** Pre-fill stock code (e.g. from K-line chart) */
  defaultCode?: string;
}

export default function OrderSubmitForm({ open, onClose, defaultCode }: Props) {
  const [form] = Form.useForm();
  const qc = useQueryClient();
  const [options, setOptions] = useState<{ value: string; label: React.ReactNode }[]>([]);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const submitMut = useMutation({
    mutationFn: (body: SubmitOrderBody) => api.submitOrder(body),
    onSuccess: () => {
      message.success('订单已提交');
      qc.invalidateQueries({ queryKey: ['orders'] });
      qc.invalidateQueries({ queryKey: ['account'] });
      qc.invalidateQueries({ queryKey: ['positions'] });
      form.resetFields();
      onClose();
    },
    onError: (e: Error) => message.error(e.message),
  });

  const onSearch = useCallback((text: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!text || text.length < 1) { setOptions([]); return; }

    debounceRef.current = setTimeout(async () => {
      try {
        const res = await api.searchStocks(text);
        setOptions(
          res.data.map((s) => ({
            value: s.ts_code,
            label: (
              <span>
                <b>{s.ts_code}</b>
                <span style={{ marginLeft: 8, color: 'var(--color-t3)', fontSize: 12 }}>
                  {s.name} · {s.industry}
                </span>
              </span>
            ),
          })),
        );
      } catch {
        setOptions([]);
      }
    }, 200);
  }, []);

  const orderType = Form.useWatch('order_type', form);

  const handleOk = () => {
    form.validateFields().then((values) => {
      const body: SubmitOrderBody = {
        ts_code: values.ts_code,
        side: values.side,
        order_type: values.order_type,
        qty: values.qty,
        ...(values.order_type === 'LIMIT' ? { price: values.price } : {}),
      };
      submitMut.mutate(body);
    });
  };

  return (
    <Modal
      title="新建订单"
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnClose
      width={400}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          ts_code: defaultCode || '',
          side: 'BUY',
          order_type: 'MARKET',
          qty: 100,
        }}
        style={{ marginTop: 16 }}
      >
        <Form.Item name="ts_code" label="股票代码" rules={[{ required: true, message: '请输入股票代码' }]}>
          <AutoComplete
            options={options}
            onSearch={onSearch}
            placeholder="输入代码或名称搜索"
            allowClear
          />
        </Form.Item>

        <Form.Item name="side" label="方向" rules={[{ required: true }]}>
          <Radio.Group buttonStyle="solid">
            <Radio.Button value="BUY" style={{ width: 80, textAlign: 'center' }}>
              买入
            </Radio.Button>
            <Radio.Button value="SELL" style={{ width: 80, textAlign: 'center' }}>
              卖出
            </Radio.Button>
          </Radio.Group>
        </Form.Item>

        <Form.Item name="order_type" label="类型" rules={[{ required: true }]}>
          <Radio.Group buttonStyle="solid">
            <Radio.Button value="MARKET" style={{ width: 80, textAlign: 'center' }}>
              市价
            </Radio.Button>
            <Radio.Button value="LIMIT" style={{ width: 80, textAlign: 'center' }}>
              限价
            </Radio.Button>
          </Radio.Group>
        </Form.Item>

        {orderType === 'LIMIT' && (
          <Form.Item name="price" label="价格" rules={[{ required: true, message: '限价单需输入价格' }]}>
            <InputNumber min={0.01} step={0.01} precision={2} style={{ width: '100%' }} />
          </Form.Item>
        )}

        <Form.Item name="qty" label="数量 (股)" rules={[{ required: true, message: '请输入数量' }]}>
          <InputNumber min={100} step={100} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item style={{ marginBottom: 0, textAlign: 'right' }}>
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button type="primary" onClick={handleOk} loading={submitMut.isPending}>
              提交订单
            </Button>
          </Space>
        </Form.Item>
      </Form>
    </Modal>
  );
}
