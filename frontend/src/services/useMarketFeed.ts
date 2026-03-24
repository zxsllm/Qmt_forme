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

interface WsNewsEvent {
  type: 'news_update';
  count: number;
}

type WsMessage = MarketBar | WsNewsEvent;

function isNewsEvent(msg: WsMessage): msg is WsNewsEvent {
  return 'type' in msg && (msg as WsNewsEvent).type === 'news_update';
}

export function useMarketFeed(
  onBar?: (bar: MarketBar) => void,
  onNews?: () => void,
) {
  const [connected, setConnected] = useState(false);
  const [lastBar, setLastBar] = useState<MarketBar | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const onBarRef = useRef(onBar);
  const onNewsRef = useRef(onNews);
  onBarRef.current = onBar;
  onNewsRef.current = onNews;

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);

    ws.onmessage = (evt) => {
      try {
        const data: WsMessage = JSON.parse(evt.data);
        if (isNewsEvent(data)) {
          onNewsRef.current?.();
        } else if (data.ts_code) {
          setLastBar(data as MarketBar);
          onBarRef.current?.(data as MarketBar);
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
