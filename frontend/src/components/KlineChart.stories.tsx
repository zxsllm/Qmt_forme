import type { Meta, StoryObj } from '@storybook/react-vite';
import KlineChart from './KlineChart';

const sampleData = Array.from({ length: 60 }, (_, i) => {
  const d = new Date(2026, 0, 2 + i);
  const ds = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`;
  const base = 15 + Math.sin(i / 5) * 2;
  return {
    trade_date: ds,
    open: +(base + Math.random()).toFixed(2),
    high: +(base + 1 + Math.random()).toFixed(2),
    low: +(base - 1 + Math.random()).toFixed(2),
    close: +(base + Math.random() * 0.5).toFixed(2),
    vol: Math.round(50000 + Math.random() * 100000),
  };
});

const meta: Meta<typeof KlineChart> = {
  title: 'Components/KlineChart',
  component: KlineChart,
};
export default meta;
type Story = StoryObj<typeof KlineChart>;

export const Default: Story = {
  args: { data: sampleData, height: 400, indicators: ['MA', 'VOL'] },
};

export const WithMACD: Story = {
  args: { data: sampleData, height: 500, indicators: ['MA', 'VOL', 'MACD'] },
};

const minuteData = Array.from({ length: 240 }, (_, i) => {
  const h = 9 + Math.floor((i + 30) / 60);
  const m = (i + 30) % 60;
  const t = `2026-03-23 ${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:00`;
  const base = 15 + Math.sin(i / 20) * 1.5;
  return {
    trade_time: t,
    open: +(base + Math.random() * 0.2).toFixed(2),
    high: +(base + 0.3 + Math.random() * 0.2).toFixed(2),
    low: +(base - 0.3 + Math.random() * 0.2).toFixed(2),
    close: +(base + Math.random() * 0.1).toFixed(2),
    vol: Math.round(10000 + Math.random() * 30000),
  };
});

export const IntradayArea: Story = {
  args: { data: minuteData, period: '1min', height: 400, indicators: ['VOL'] },
};

export const Weekly: Story = {
  args: { data: sampleData, period: 'weekly', height: 400, indicators: ['MA', 'VOL'] },
};
