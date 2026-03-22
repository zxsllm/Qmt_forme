import { useEffect, useRef } from 'react';
import { init, type Chart } from 'klinecharts';

interface BarData {
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  vol: number;
  amount?: number;
}

interface Props {
  data: BarData[];
  height?: number;
  autoFill?: boolean;
  indicators?: string[];
}

function toTimestamp(d: string): number {
  const y = d.slice(0, 4), m = d.slice(4, 6), day = d.slice(6, 8);
  return new Date(`${y}-${m}-${day}T00:00:00`).getTime();
}

const OVERLAY_INDICATORS = new Set(['MA', 'EMA', 'SMA', 'BOLL']);

/*
 * klinecharts 是 Canvas 渲染，不支持 CSS 变量。
 * 颜色必须是 hex 字面值，与 index.css @theme 中的 token 保持手动同步。
 */
const COLORS = {
  up: '#f87171',       // --color-up
  down: '#4ade80',     // --color-down
  bgBase: '#0d1117',   // --color-bg-base
  bgHover: '#1e2530',  // --color-bg-hover
  edge: '#1e2530',     // --color-edge
  t3: '#64748b',       // --color-t3
  t4: '#334155',       // --color-t4
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

function toKlineData(data: BarData[]) {
  return data.map((d) => ({
    timestamp: toTimestamp(d.trade_date),
    open: d.open,
    high: d.high,
    low: d.low,
    close: d.close,
    volume: d.vol,
    turnover: d.amount ?? 0,
  }));
}

export default function KlineChart({ data, height = 400, autoFill, indicators = ['MA', 'VOL'] }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);
  const indicatorsRef = useRef(indicators);
  indicatorsRef.current = indicators;

  // Init chart once, reuse across StrictMode remounts
  useEffect(() => {
    if (!containerRef.current) return;

    let chart = chartRef.current;

    if (!chart) {
      chart = init(containerRef.current, { styles: CHART_STYLES });
      if (!chart) return;
      chartRef.current = chart;

      for (const ind of indicatorsRef.current) {
        if (OVERLAY_INDICATORS.has(ind)) {
          chart.createIndicator(ind, true, { id: 'candle_pane' });
        } else {
          chart.createIndicator(ind, false, { height: 80 });
        }
      }
    }

    const c = chart;
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
    };
  }, []);

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
