import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Modal, Spin } from 'antd';
import { api, type SectorStockRow } from '../../services/api';
import { pctColor } from './RankTable';

interface Props {
  industry: string | null;
  onClose: () => void;
  onStockClick?: (tsCode: string) => void;
}

type SortKey = 'pct_chg' | 'circ_mv';
type SortDir = 'asc' | 'desc';

function fmtVol(v: number | null | undefined): string {
  if (v == null) return '-';
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (v >= 1e4) return (v / 1e4).toFixed(1) + '万';
  return v.toFixed(0);
}

function fmtMv(v: number | null | undefined): string {
  if (v == null) return '-';
  if (v >= 10000) return (v / 10000).toFixed(1) + '亿';
  return v.toFixed(1) + '万';
}

const SORT_ARROW = { asc: ' ↑', desc: ' ↓' };

export default function SectorDetailModal({ industry, onClose, onStockClick }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['sector-stocks', industry],
    queryFn: () => api.sectorStocks(industry!),
    enabled: !!industry,
    refetchInterval: 15_000,
  });

  const [sortKey, setSortKey] = useState<SortKey>('pct_chg');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const rawStocks: SectorStockRow[] = data?.data ?? [];

  const sorted = useMemo(() => {
    const arr = [...rawStocks];
    arr.sort((a, b) => {
      const av = a[sortKey] ?? (sortDir === 'desc' ? -Infinity : Infinity);
      const bv = b[sortKey] ?? (sortDir === 'desc' ? -Infinity : Infinity);
      return sortDir === 'desc' ? (bv as number) - (av as number) : (av as number) - (bv as number);
    });
    return arr;
  }, [rawStocks, sortKey, sortDir]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const thStyle = (clickable: boolean): React.CSSProperties => ({
    padding: '6px 8px',
    color: '#64748b',
    fontWeight: 500,
    borderBottom: '1px solid rgba(148,186,215,0.10)',
    position: 'sticky',
    top: 0,
    background: 'rgba(14,28,41,0.98)',
    fontSize: 11,
    cursor: clickable ? 'pointer' : undefined,
    userSelect: 'none',
  });

  const sortLabel = (key: SortKey, label: string) =>
    sortKey === key ? label + SORT_ARROW[sortDir] : label;

  return (
    <Modal
      open={!!industry}
      onCancel={onClose}
      footer={null}
      title={
        <span style={{ color: '#d7efff', fontSize: 14 }}>
          {industry} — 成分股 ({sorted.length})
        </span>
      }
      width={600}
      styles={{
        content: {
          background: 'linear-gradient(180deg, rgba(23,42,59,0.96), rgba(8,17,25,0.98))',
          border: '1px solid rgba(148,186,215,0.18)',
          borderRadius: 22,
          padding: 0,
        },
        header: {
          background: 'transparent',
          borderBottom: '1px solid rgba(148,186,215,0.12)',
          padding: '12px 20px',
        },
        body: {
          padding: '0 4px 12px',
          maxHeight: 520,
          overflowY: 'auto',
        },
      }}
    >
      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin />
        </div>
      ) : sorted.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 40, color: '#556677', fontSize: 13 }}>
          暂无数据
        </div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr>
              <th style={{ ...thStyle(false), textAlign: 'left' }}>#</th>
              <th style={{ ...thStyle(false), textAlign: 'left' }}>代码</th>
              <th style={{ ...thStyle(false), textAlign: 'left' }}>名称</th>
              <th style={{ ...thStyle(false), textAlign: 'right' }}>现价</th>
              <th
                style={{ ...thStyle(true), textAlign: 'right', color: sortKey === 'pct_chg' ? '#60a5fa' : '#64748b' }}
                onClick={() => handleSort('pct_chg')}
              >
                {sortLabel('pct_chg', '涨跌幅')}
              </th>
              <th
                style={{ ...thStyle(true), textAlign: 'right', color: sortKey === 'circ_mv' ? '#60a5fa' : '#64748b' }}
                onClick={() => handleSort('circ_mv')}
              >
                {sortLabel('circ_mv', '流通市值')}
              </th>
              <th style={{ ...thStyle(false), textAlign: 'right' }}>成交量</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((s, i) => (
              <tr
                key={s.ts_code}
                onClick={onStockClick ? () => { onStockClick(s.ts_code); onClose(); } : undefined}
                style={{
                  borderBottom: '1px solid rgba(148,186,215,0.06)',
                  transition: 'background 0.15s',
                  cursor: onStockClick ? 'pointer' : undefined,
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(148,186,215,0.08)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = '')}
              >
                <td style={{ padding: '4px 8px', color: '#556677', fontSize: 11 }}>{i + 1}</td>
                <td style={{ padding: '4px 8px', color: '#93a9bc', fontSize: 11 }}>
                  {s.ts_code?.replace(/\.\w+$/, '')}
                </td>
                <td style={{ padding: '4px 8px', color: '#e6f1fa' }}>{s.name}</td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: pctColor(s.pct_chg) }}>
                  {s.close?.toFixed(2) ?? '-'}
                </td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: pctColor(s.pct_chg), fontWeight: 600 }}>
                  {s.pct_chg != null ? `${s.pct_chg >= 0 ? '+' : ''}${s.pct_chg.toFixed(2)}%` : '-'}
                </td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: '#93a9bc' }}>
                  {fmtMv(s.circ_mv)}
                </td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: '#93a9bc' }}>
                  {fmtVol(s.vol)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Modal>
  );
}
