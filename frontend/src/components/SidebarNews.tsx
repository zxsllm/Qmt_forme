import { useState, useCallback } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Modal } from 'antd';
import { api, type NewsItem } from '../services/api';
import { useMarketFeed } from '../services/useMarketFeed';

const SOURCE_LABELS: Record<string, { label: string; color: string }> = {
  sina:          { label: '新浪', color: '#e6654a' },
  cls:           { label: '财联', color: '#f5a623' },
  eastmoney:     { label: '东财', color: '#4a90d9' },
  wallstreetcn:  { label: '华尔', color: '#7ed321' },
  '10jqka':      { label: '同花', color: '#bd10e0' },
  yuncaijing:    { label: '云财', color: '#50e3c2' },
  fenghuang:     { label: '凤凰', color: '#d94a6a' },
  jinrongjie:    { label: '金融', color: '#f5c842' },
  yicai:         { label: '一财', color: '#42a5f5' },
};

export default function SidebarNews() {
  const queryClient = useQueryClient();

  const onNewsUpdate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['market-news'] });
    queryClient.refetchQueries({ queryKey: ['market-news'] });
  }, [queryClient]);

  useMarketFeed(undefined, onNewsUpdate);

  const { data } = useQuery({
    queryKey: ['market-news'],
    queryFn: () => api.marketNews(50),
    refetchInterval: 10_000,
  });

  const [selected, setSelected] = useState<NewsItem | null>(null);

  const items: NewsItem[] = data?.data ?? [];

  return (
    <div
      className="flex flex-col"
      style={{
        height: '100%',
        padding: '10px 14px',
        gap: 2,
        overflow: 'hidden',
        borderTop: '1px solid rgba(148,186,215,0.10)',
      }}
    >
      <span style={{
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: '0.04em',
        color: '#93a9bc',
        marginBottom: 6,
        textTransform: 'uppercase',
        flexShrink: 0,
      }}>
        新闻快讯
      </span>
      <div className="sidebar-news-scroll" style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {items.length === 0 && (
          <span style={{ fontSize: 11, color: '#556677' }}>暂无新闻</span>
        )}
        {items.map((n) => {
          const srcInfo = n.source ? SOURCE_LABELS[n.source] : null;
          return (
            <div
              key={n.id}
              onClick={() => setSelected(n)}
              style={{
                fontSize: 11,
                lineHeight: '18px',
                color: '#93a9bc',
                padding: '4px 0',
                borderBottom: '1px solid rgba(148,186,215,0.08)',
                cursor: 'pointer',
                transition: 'color 120ms ease',
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.color = '#e6f1fa'; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.color = '#93a9bc'; }}
            >
              <span style={{ color: '#556677', marginRight: 4, fontSize: 10 }}>
                {n.datetime?.slice(11, 16) || ''}
              </span>
              {srcInfo && (
                <span style={{
                  fontSize: 9,
                  color: srcInfo.color,
                  border: `1px solid ${srcInfo.color}40`,
                  borderRadius: 3,
                  padding: '0 3px',
                  marginRight: 4,
                  lineHeight: '14px',
                  display: 'inline-block',
                  verticalAlign: 'middle',
                }}>
                  {srcInfo.label}
                </span>
              )}
              {(n.content || '').slice(0, 36)}
              {(n.content || '').length > 36 ? '...' : ''}
            </div>
          );
        })}
      </div>

      <style>{`
        .sidebar-news-scroll::-webkit-scrollbar { width: 4px; }
        .sidebar-news-scroll::-webkit-scrollbar-track { background: transparent; }
        .sidebar-news-scroll::-webkit-scrollbar-thumb {
          background: rgba(148,186,215,0.18);
          border-radius: 2px;
        }
        .sidebar-news-scroll::-webkit-scrollbar-thumb:hover {
          background: rgba(148,186,215,0.35);
        }
      `}</style>

      <Modal
        open={!!selected}
        onCancel={() => setSelected(null)}
        footer={null}
        title={
          <span style={{ color: '#d7efff', fontSize: 14 }}>
            {selected?.datetime?.slice(0, 16) || '新闻详情'}
            {selected?.source && SOURCE_LABELS[selected.source] && (
              <span style={{
                fontSize: 11,
                color: SOURCE_LABELS[selected.source].color,
                marginLeft: 8,
              }}>
                {SOURCE_LABELS[selected.source].label}
              </span>
            )}
          </span>
        }
        width={520}
        styles={{
          root: {
            background: 'linear-gradient(180deg, rgba(23,42,59,0.96), rgba(8,17,25,0.98))',
            border: '1px solid rgba(148,186,215,0.18)',
            borderRadius: 22,
          },
          header: {
            background: 'transparent',
            borderBottom: '1px solid rgba(148,186,215,0.12)',
          },
        }}
      >
        {selected && (
          <div style={{ color: '#e6f1fa', fontSize: 13, lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
            {selected.content}
            {selected.channels && (
              <div style={{ marginTop: 12, fontSize: 11, color: '#556677' }}>
                频道: {selected.channels}
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
