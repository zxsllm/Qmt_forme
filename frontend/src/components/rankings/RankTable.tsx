import type { ReactNode } from 'react';

interface Column<T> {
  key: string;
  title: string;
  render: (row: T, idx: number) => ReactNode;
  align?: 'left' | 'right';
  width?: string;
}

interface Props<T> {
  title: string;
  data: T[];
  columns: Column<T>[];
}

function pctColor(v: number | null | undefined): string {
  if (v == null) return '#93a9bc';
  return v >= 0 ? '#ff6f91' : '#4ade80';
}

export { pctColor };

export default function RankTable<T>({ title, data, columns }: Props<T>) {
  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        background: 'linear-gradient(180deg, rgba(23,42,59,0.88), rgba(8,17,25,0.92))',
        border: '1px solid rgba(148,186,215,0.18)',
        borderRadius: 18,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        backdropFilter: 'blur(10px)',
        boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.04), 0 12px 32px rgba(0,0,0,0.28)',
      }}
    >
      <div
        style={{
          padding: '8px 14px',
          fontSize: 13,
          fontWeight: 700,
          letterSpacing: '0.04em',
          color: '#d7efff',
          borderBottom: '1px solid rgba(148,186,215,0.12)',
          flexShrink: 0,
        }}
      >
        {title}
      </div>
      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  style={{
                    padding: '5px 8px',
                    textAlign: col.align || 'left',
                    color: '#64748b',
                    fontWeight: 500,
                    borderBottom: '1px solid rgba(148,186,215,0.10)',
                    position: 'sticky',
                    top: 0,
                    background: 'rgba(14,28,41,0.95)',
                    width: col.width,
                  }}
                >
                  {col.title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((row, idx) => (
              <tr
                key={idx}
                style={{ borderBottom: '1px solid rgba(148,186,215,0.06)' }}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    style={{
                      padding: '4px 8px',
                      textAlign: col.align || 'left',
                      color: '#e6f1fa',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      maxWidth: 0,
                    }}
                  >
                    {col.render(row, idx)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
