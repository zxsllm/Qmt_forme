import { useEffect, useRef, useState, useCallback } from 'react';

const WS_URL = 'ws://localhost:8000/ws/market';
const RECONNECT_DELAY = 3000;

export interface MarketBar {
  ts_code: string;
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  vol: number;
  amount: number;
  freq: string;
}

export function useMarketFeed(onBar?: (bar: MarketBar) => void) {
  const [connected, setConnected] = useState(false);
  const [lastBar, setLastBar] = useState<MarketBar | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const onBarRef = useRef(onBar);
  onBarRef.current = onBar;

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);

    ws.onmessage = (evt) => {
      try {
        const bar: MarketBar = JSON.parse(evt.data);
        if (bar.ts_code) {
          setLastBar(bar);
          onBarRef.current?.(bar);
        }
      } catch { /* ignore non-JSON (e.g. pong) */ }
    };

    ws.onclose = () => {
      setConnected(false);
      setTimeout(connect, RECONNECT_DELAY);
    };

    ws.onerror = () => ws.close();
  }, []);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected, lastBar };
}
