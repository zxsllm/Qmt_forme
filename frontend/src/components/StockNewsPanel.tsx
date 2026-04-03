import { useState, type CSSProperties } from 'react';
import { Empty, Modal } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { api, type IrmQaItem } from '../services/api';

export interface ExtraTab {
  key: string;
  label: string;
  node: React.ReactNode;
}

interface Props {
  tsCode: string;
  height?: number;
  extraTabs?: ExtraTab[];
}

export default function StockNewsPanel({ tsCode, height = 160, extraTabs }: Props) {
  const [activeKey, setActiveKey] = useState<string | number>('news');

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

  const [selectedNews, setSelectedNews] = useState<(typeof newsItems)[number] | null>(null);
  const [selectedQa, setSelectedQa] = useState<IrmQaItem | null>(null);

  const listStyle: CSSProperties = {
    overflowY: 'auto',
    height: height - 36,
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

  const builtinTabs: { key: string; label: string; node: React.ReactNode }[] = [
    {
      key: 'news',
      label: '个股新闻',
      node: (
        <div style={listStyle}>
          {newsItems.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无新闻" />
          ) : (
            newsItems.map((n) => (
              <div
                key={n.id}
                style={{ ...rowStyle, cursor: 'pointer' }}
                onClick={() => setSelectedNews(n)}
                onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.color = '#e6f1fa'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.color = '#93a9bc'; }}
              >
                <span style={dateStyle}>{n.datetime?.slice(0, 10)}</span>
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
      node: (
        <div style={listStyle}>
          {annsItems.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无公告" />
          ) : (
            annsItems.map((a) => (
              <div key={a.id} style={rowStyle} title={a.title}>
                <span style={dateStyle}>{a.ann_date}</span>
                {a.url ? (
                  <a href={a.url} target="_blank" rel="noreferrer" style={{ color: '#6bc7ff' }}>
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
      node: (
        <div style={listStyle}>
          {irmItems.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无问答" />
          ) : (
            irmItems.map((item, idx) => (
              <div
                key={`${item.ts_code}-${item.pub_time}-${idx}`}
                style={{ ...rowStyle, cursor: 'pointer', whiteSpace: 'nowrap' }}
                title={`Q: ${item.q}\nA: ${item.a}`}
                onClick={() => setSelectedQa(item)}
                onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.color = '#e6f1fa'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.color = '#93a9bc'; }}
              >
                <span style={dateStyle}>{item.pub_time?.slice(0, 10) || item.trade_date}</span>
                Q: {item.q?.slice(0, 50)}
              </div>
            ))
          )}
        </div>
      ),
    },
  ];

  const allTabs = [...builtinTabs, ...(extraTabs ?? [])];
  const activeTab = allTabs.find(t => t.key === activeKey) ?? allTabs[0];

  return (
    <div style={{ height, padding: '0 14px' }}>
      <div style={{ display: 'flex', gap: 4, padding: '5px 0 3px' }}>
        {allTabs.map((t) => {
          const active = t.key === activeKey;
          return (
            <button
              key={t.key}
              onClick={() => setActiveKey(t.key)}
              style={{
                border: `1px solid ${active ? 'rgba(121,200,246,0.50)' : 'rgba(255,255,255,0.08)'}`,
                background: active
                  ? 'rgba(32,74,103,0.48)'
                  : 'rgba(255,255,255,0.03)',
                borderRadius: 999,
                padding: '3px 12px',
                fontSize: 11,
                fontWeight: active ? 600 : 400,
                color: active ? '#7ce1f2' : '#93a9bc',
                cursor: 'pointer',
                transition: 'all 120ms ease',
                backdropFilter: active ? 'blur(6px)' : 'none',
                lineHeight: '18px',
              }}
              onMouseEnter={(e) => {
                if (!active) {
                  e.currentTarget.style.borderColor = 'rgba(150,217,255,0.24)';
                  e.currentTarget.style.background = 'rgba(255,255,255,0.05)';
                }
              }}
              onMouseLeave={(e) => {
                if (!active) {
                  e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)';
                  e.currentTarget.style.background = 'rgba(255,255,255,0.03)';
                }
              }}
            >
              {t.label}
            </button>
          );
        })}
      </div>
      {activeTab?.node}

      <Modal
        open={!!selectedNews}
        onCancel={() => setSelectedNews(null)}
        footer={null}
        title={
          <span style={{ color: '#d7efff', fontSize: 14 }}>
            {selectedNews?.datetime?.slice(0, 16) || '新闻详情'}
          </span>
        }
        width={560}
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
        {selectedNews && (
          <div style={{ color: '#e6f1fa', fontSize: 13, lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
            {selectedNews.content}
            {selectedNews.channels && (
              <div style={{ marginTop: 12, fontSize: 11, color: '#556677' }}>
                频道: {selectedNews.channels}
              </div>
            )}
          </div>
        )}
      </Modal>

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
              <div style={{ fontSize: 11, color: '#6bc7ff', fontWeight: 600, marginBottom: 4 }}>提问</div>
              <div style={{ whiteSpace: 'pre-wrap' }}>{selectedQa.q}</div>
            </div>
            <div style={{
              padding: '12px 14px',
              background: 'rgba(255,255,255,0.03)',
              borderRadius: 14,
              border: '1px solid rgba(148,186,215,0.10)',
            }}>
              <div style={{ fontSize: 11, color: '#b48cff', fontWeight: 600, marginBottom: 4 }}>回复</div>
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
