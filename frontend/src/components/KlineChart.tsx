import { useEffect, useRef } from 'react';
import { init, dispose, registerIndicator, CandleType, TooltipShowRule, TooltipShowType, type Chart } from 'klinecharts';

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
  pre_close?: number;
  pct_chg?: number;
}

interface Props {
  data: BarData[];
  period?: KlinePeriod;
  height?: number;
  autoFill?: boolean;
  indicators?: string[];
  preClose?: number;
  isIndex?: boolean;
}

function toTimestamp(d: string): number {
  if (d.includes('-') || d.includes(' ')) {
    return new Date(d).getTime();
  }
  const y = d.slice(0, 4), m = d.slice(4, 6), day = d.slice(6, 8);
  return new Date(`${y}-${m}-${day}T00:00:00`).getTime();
}

const OVERLAY_INDICATORS = new Set(['MA', 'EMA', 'SMA', 'BOLL', 'AVG_PRICE']);

registerIndicator({
  name: 'AVG_PRICE',
  shortName: '均价',
  figures: [{ key: 'avgPrice', title: '均价: ', type: 'line' }],
  calc: (kLineDataList) => {
    let cumTurnover = 0;
    let cumVolume = 0;
    return kLineDataList.map((d) => {
      cumTurnover += d.turnover ?? 0;
      cumVolume += d.volume ?? 0;
      return { avgPrice: cumVolume > 0 ? cumTurnover / cumVolume : d.close };
    });
  },
});

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
    type: CandleType.CandleSolid,
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
    pre_close: d.pre_close,
    pct_chg: d.pct_chg,
  }));
}

export default function KlineChart({
  data,
  period = 'daily',
  height = 400,
  autoFill,
  indicators = ['MA', 'VOL'],
  preClose,
  isIndex = false,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);
  const indicatorsRef = useRef(indicators);
  const periodRef = useRef(period);
  const preCloseRef = useRef(preClose);
  indicatorsRef.current = indicators;
  periodRef.current = period;
  preCloseRef.current = preClose;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const isArea = period === '1min';
    const baseStyles = isArea ? AREA_STYLES : CHART_STYLES;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const tooltipCustom = (cbData: any) => {
      const cur = cbData?.current;
      if (!cur) return [];
      const tc = COLORS.t3;
      const base = [
        { title: { text: 'Time: ', color: tc }, value: '{time}' },
        { title: { text: 'Open: ', color: tc }, value: '{open}' },
        { title: { text: 'High: ', color: tc }, value: '{high}' },
        { title: { text: 'Low: ', color: tc }, value: '{low}' },
        { title: { text: 'Close: ', color: tc }, value: '{close}' },
        { title: { text: 'Volume: ', color: tc }, value: '{volume}' },
      ];
      let ref: number | undefined;
      if (isArea) {
        ref = preCloseRef.current;
      } else {
        ref = cur.pre_close ?? cbData?.prev?.close;
      }
      if (ref && ref > 0) {
        const chg = ((cur.close - ref) / ref) * 100;
        const color = chg >= 0 ? COLORS.up : COLORS.down;
        base.push({ title: { text: '涨跌幅: ', color: tc }, value: { text: `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%`, color } } as any);
      }
      return base;
    };

    const styles = {
      ...baseStyles,
      candle: {
        ...(baseStyles as any).candle,
        tooltip: { showRule: TooltipShowRule.Always, showType: TooltipShowType.Standard, custom: tooltipCustom },
      },
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const chart = init(container, {
      styles: styles as any,
      customApi: {
        formatBigNumber: (value: string | number): string => {
          const n = typeof value === 'number' ? value : parseFloat(value);
          if (isNaN(n)) return String(value);
          const abs = Math.abs(n);
          if (abs >= 1e8) return (n / 1e8).toFixed(2) + '亿';
          if (abs >= 1e4) return (n / 1e4).toFixed(2) + '万';
          return String(value);
        },
      },
    });
    if (!chart) return;
    chartRef.current = chart;

    if (isArea && !isIndex) {
      chart.createIndicator('AVG_PRICE', true, { id: 'candle_pane' });
    }

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
