import { useEffect, useRef } from 'react';
import { init, dispose, type Chart } from 'klinecharts';

export type KlinePeriod = '1min' | 'daily' | 'weekly' | 'monthly';

interface BarData {
  trade_date?: string;
  trade_time?: string;
  open: number;
  high: number;
  low: number;
  close: number;
  vol: number;
  amount?: number;
}

interface Props {
  data: BarData[];
  period?: KlinePeriod;
  height?: number;
  autoFill?: boolean;
  indicators?: string[];
}

function toTimestamp(d: string): number {
  if (d.includes('-') || d.includes(' ')) {
    return new Date(d).getTime();
  }
  const y = d.slice(0, 4), m = d.slice(4, 6), day = d.slice(6, 8);
  return new Date(`${y}-${m}-${day}T00:00:00`).getTime();
}

const OVERLAY_INDICATORS = new Set(['MA', 'EMA', 'SMA', 'BOLL']);

const COLORS = {
  up: '#f87171',
  down: '#4ade80',
  bgBase: '#0d1117',
  bgHover: '#1e2530',
  edge: '#1e2530',
  t3: '#64748b',
  t4: '#334155',
};

const CHART_STYLES = {
  grid: {
    show: true,
    horizontal: { color: COLORS.bgHover },
    vertical: { color: COLORS.bgHover },
  },
  candle: {
    type: 'candle_solid' as const,
    priceMark: { last: { show: true } },
    bar: {
      upColor: COLORS.up,
      downColor: COLORS.down,
      upBorderColor: COLORS.up,
      downBorderColor: COLORS.down,
      upWickColor: COLORS.up,
      downWickColor: COLORS.down,
    },
  },
  indicator: {
    lines: [
      { color: '#f6bf26' },
      { color: '#ff6d00' },
      { color: '#ab47bc' },
      { color: '#42a5f5' },
      { color: '#66bb6a' },
    ],
  },
  xAxis: {
    axisLine: { color: COLORS.edge },
    tickLine: { color: COLORS.edge },
    tickText: { color: COLORS.t3 },
  },
  yAxis: {
    axisLine: { color: COLORS.edge },
    tickLine: { color: COLORS.edge },
    tickText: { color: COLORS.t3 },
  },
  crosshair: {
    horizontal: { line: { color: COLORS.t4 } },
    vertical: { line: { color: COLORS.t4 } },
  },
  separator: { color: COLORS.edge },
};

const AREA_STYLES = {
  ...CHART_STYLES,
  candle: {
    type: 'area' as const,
    priceMark: { last: { show: true } },
    area: {
      lineSize: 1,
      lineColor: '#3b82f6',
      value: 'close',
      backgroundColor: [{ offset: 0, color: 'rgba(59,130,246,0.2)' }, { offset: 1, color: 'transparent' }],
    },
  },
};

function toKlineData(data: BarData[]) {
  return data.map((d) => ({
    timestamp: toTimestamp(d.trade_time || d.trade_date || ''),
    open: d.open,
    high: d.high,
    low: d.low,
    close: d.close,
    volume: d.vol,
    turnover: d.amount ?? 0,
  }));
}

export default function KlineChart({
  data,
  period = 'daily',
  height = 400,
  autoFill,
  indicators = ['MA', 'VOL'],
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);
  const indicatorsRef = useRef(indicators);
  const periodRef = useRef(period);
  indicatorsRef.current = indicators;
  periodRef.current = period;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const isArea = period === '1min';
    const styles = isArea ? AREA_STYLES : CHART_STYLES;
    const chart = init(container, { styles });
    if (!chart) return;
    chartRef.current = chart;

    for (const ind of indicatorsRef.current) {
      if (OVERLAY_INDICATORS.has(ind)) {
        chart.createIndicator(ind, true, { id: 'candle_pane' });
      } else {
        chart.createIndicator(ind, false, { height: 80 });
      }
    }

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(container);

    return () => {
      ro.disconnect();
      dispose(container);
      chartRef.current = null;
    };
  }, [period]);

  useEffect(() => {
    if (!chartRef.current || !data.length) return;
    chartRef.current.applyNewData(toKlineData(data));
    chartRef.current.resize();
  }, [data]);

  return (
    <div
      ref={containerRef}
      className="bg-bg-base"
      style={{ width: '100%', height: autoFill ? '100%' : height }}
    />
  );
}
