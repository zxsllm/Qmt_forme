import { useState, type CSSProperties } from 'react';
import { Tabs, Empty, Modal } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { api, type IrmQaItem } from '../services/api';

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

  const exchange = tsCode.split('.')[1]?.toUpperCase() ?? '';
  const { data: irmData } = useQuery({
    queryKey: ['stock-irm-qa', tsCode],
    queryFn: () => api.stockIrmQa(tsCode),
    enabled: !!tsCode && (exchange === 'SH' || exchange === 'SZ'),
    staleTime: 5 * 60_000,
  });

  const newsItems = newsData?.data ?? [];
  const annsItems = annsData?.data ?? [];
  const irmItems: IrmQaItem[] = irmData?.data ?? [];

  const [selectedQa, setSelectedQa] = useState<IrmQaItem | null>(null);

  const listStyle: CSSProperties = {
    overflowY: 'auto',
    height: height - 40,
    padding: '4px 12px',
  };

  const rowStyle: CSSProperties = {
    fontSize: 12,
    lineHeight: '22px',
    color: '#93a9bc',
    borderBottom: '1px solid rgba(148,186,215,0.08)',
    padding: '4px 6px',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  };

  const dateStyle: CSSProperties = {
    color: '#556677',
    marginRight: 6,
    fontSize: 11,
  };

  return (
    <div style={{ height, borderTop: '1px solid rgba(148,186,215,0.12)', padding: '0 14px' }}>
      <Tabs
        size="small"
        defaultActiveKey="news"
        style={{ height: '100%' }}
        tabBarStyle={{ marginBottom: 4 }}
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
                      <span style={dateStyle}>
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
                      <span style={dateStyle}>
                        {a.ann_date}
                      </span>
                      {a.url ? (
                        <a
                          href={a.url}
                          target="_blank"
                          rel="noreferrer"
                          style={{ color: '#6bc7ff' }}
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
          {
            key: 'irm',
            label: '互动问答',
            children: (
              <div style={listStyle}>
                {irmItems.length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无问答" />
                ) : (
                  irmItems.map((item, idx) => (
                    <div
                      key={`${item.ts_code}-${item.pub_time}-${idx}`}
                      style={{
                        ...rowStyle,
                        cursor: 'pointer',
                        whiteSpace: 'nowrap',
                      }}
                      title={`Q: ${item.q}\nA: ${item.a}`}
                      onClick={() => setSelectedQa(item)}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.color = '#e6f1fa'; }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.color = '#93a9bc'; }}
                    >
                      <span style={dateStyle}>
                        {item.pub_time?.slice(0, 10) || item.trade_date}
                      </span>
                      Q: {item.q?.slice(0, 50)}
                    </div>
                  ))
                )}
              </div>
            ),
          },
        ]}
      />

      <Modal
        open={!!selectedQa}
        onCancel={() => setSelectedQa(null)}
        footer={null}
        title={
          <span style={{ color: '#d7efff', fontSize: 14 }}>
            {selectedQa?.name} 互动问答
          </span>
        }
        width={600}
        styles={{
          content: {
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
        {selectedQa && (
          <div style={{ color: '#e6f1fa', fontSize: 13, lineHeight: 1.8 }}>
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 11, color: '#6bc7ff', fontWeight: 600, marginBottom: 4 }}>
                提问
              </div>
              <div style={{ whiteSpace: 'pre-wrap' }}>{selectedQa.q}</div>
            </div>
            <div style={{
              padding: '12px 14px',
              background: 'rgba(255,255,255,0.03)',
              borderRadius: 14,
              border: '1px solid rgba(148,186,215,0.10)',
            }}>
              <div style={{ fontSize: 11, color: '#b48cff', fontWeight: 600, marginBottom: 4 }}>
                回复
              </div>
              <div style={{ whiteSpace: 'pre-wrap' }}>{selectedQa.a}</div>
            </div>
            <div style={{ marginTop: 10, fontSize: 11, color: '#556677', display: 'flex', gap: 16 }}>
              <span>回复时间: {selectedQa.pub_time || selectedQa.trade_date}</span>
              {selectedQa.industry && <span>行业: {selectedQa.industry}</span>}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
