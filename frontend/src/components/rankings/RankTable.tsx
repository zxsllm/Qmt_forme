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
  if (v == null) return '#94a3b8';
  return v >= 0 ? '#f87171' : '#4ade80';
}

export { pctColor };

export default function RankTable<T>({ title, data, columns }: Props<T>) {
  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        background: '#0d1117',
        border: '1px solid #1e2530',
        borderRadius: 6,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          padding: '6px 10px',
          fontSize: 12,
          fontWeight: 600,
          color: '#94a3b8',
          borderBottom: '1px solid #1e2530',
          background: '#151b23',
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
                    padding: '4px 6px',
                    textAlign: col.align || 'left',
                    color: '#475569',
                    fontWeight: 500,
                    borderBottom: '1px solid #1e2530',
                    position: 'sticky',
                    top: 0,
                    background: '#0d1117',
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
                style={{ borderBottom: '1px solid #1e2530' }}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    style={{
                      padding: '3px 6px',
                      textAlign: col.align || 'left',
                      color: '#cbd5e1',
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
