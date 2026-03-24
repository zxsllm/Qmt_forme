import { Tabs, Empty } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { api } from '../services/api';

interface Props {
  tsCode: string;
  height?: number;
}

export default function StockNewsPanel({ tsCode, height = 160 }: Props) {
  const { data: newsData } = useQuery({
    queryKey: ['stock-news', tsCode],
    queryFn: () => api.stockNews(tsCode),
    enabled: !!tsCode,
    refetchInterval: 120_000,
  });

  const { data: annsData } = useQuery({
    queryKey: ['stock-anns', tsCode],
    queryFn: () => api.stockAnns(tsCode),
    enabled: !!tsCode,
    refetchInterval: 120_000,
  });

  const newsItems = newsData?.data ?? [];
  const annsItems = annsData?.data ?? [];

  const listStyle: React.CSSProperties = {
    overflowY: 'auto',
    height: height - 40,
    padding: '0 8px',
  };

  const rowStyle: React.CSSProperties = {
    fontSize: 12,
    lineHeight: '22px',
    color: '#cbd5e1',
    borderBottom: '1px solid #1e2530',
    padding: '3px 0',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  };

  return (
    <div style={{ height, borderTop: '1px solid #1e2530' }}>
      <Tabs
        size="small"
        defaultActiveKey="news"
        style={{ height: '100%' }}
        items={[
          {
            key: 'news',
            label: '个股新闻',
            children: (
              <div style={listStyle}>
                {newsItems.length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无新闻" />
                ) : (
                  newsItems.map((n) => (
                    <div key={n.id} style={rowStyle} title={n.content}>
                      <span style={{ color: '#64748b', marginRight: 6 }}>
                        {n.datetime?.slice(0, 10)}
                      </span>
                      {n.content?.slice(0, 60)}
                    </div>
                  ))
                )}
              </div>
            ),
          },
          {
            key: 'anns',
            label: '公司公告',
            children: (
              <div style={listStyle}>
                {annsItems.length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无公告" />
                ) : (
                  annsItems.map((a) => (
                    <div key={a.id} style={rowStyle} title={a.title}>
                      <span style={{ color: '#64748b', marginRight: 6 }}>
                        {a.ann_date}
                      </span>
                      {a.url ? (
                        <a
                          href={a.url}
                          target="_blank"
                          rel="noreferrer"
                          style={{ color: '#60a5fa' }}
                        >
                          {a.title?.slice(0, 50)}
                        </a>
                      ) : (
                        a.title?.slice(0, 50)
                      )}
                    </div>
                  ))
                )}
              </div>
            ),
          },
        ]}
      />
    </div>
  );
}
