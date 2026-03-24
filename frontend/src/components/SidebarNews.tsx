import { useQuery } from '@tanstack/react-query';
import { api, type NewsItem } from '../services/api';

export default function SidebarNews() {
  const { data } = useQuery({
    queryKey: ['market-news'],
    queryFn: () => api.marketNews(30),
    refetchInterval: 60_000,
  });

  const items: NewsItem[] = data?.data ?? [];

  return (
    <div
      className="flex flex-col border-t border-edge"
      style={{ padding: '8px 12px', gap: 2, overflow: 'hidden' }}
    >
      <span style={{ fontSize: 11, color: '#64748b', fontWeight: 600, marginBottom: 4 }}>
        新闻快讯
      </span>
      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {items.length === 0 && (
          <span style={{ fontSize: 11, color: '#475569' }}>暂无新闻</span>
        )}
        {items.map((n) => (
          <div
            key={n.id}
            style={{
              fontSize: 11,
              lineHeight: '18px',
              color: '#94a3b8',
              padding: '3px 0',
              borderBottom: '1px solid #1e2530',
              cursor: 'pointer',
            }}
            title={n.content}
          >
            <span style={{ color: '#475569', marginRight: 4 }}>
              {n.datetime?.slice(11, 16) || ''}
            </span>
            {(n.content || '').slice(0, 40)}
            {(n.content || '').length > 40 ? '...' : ''}
          </div>
        ))}
      </div>
    </div>
  );
}
