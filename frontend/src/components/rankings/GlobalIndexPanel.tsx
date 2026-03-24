import { useQuery } from '@tanstack/react-query';
import { api, type GlobalIndexRow } from '../../services/api';
import RankTable, { pctColor } from './RankTable';

export default function GlobalIndexPanel() {
  const { data } = useQuery({
    queryKey: ['global-indices'],
    queryFn: () => api.globalIndices(),
    refetchInterval: 30_000,
  });

  return (
    <RankTable<GlobalIndexRow>
      title="全球指数"
      data={data?.data ?? []}
      columns={[
        { key: 'name', title: '指数', render: (r) => r.name, width: '36%' },
        {
          key: 'close',
          title: '点位',
          align: 'right',
          render: (r) => r.close?.toFixed(2),
        },
        {
          key: 'chg',
          title: '涨跌',
          align: 'right',
          render: (r) => (
            <span style={{ color: pctColor(r.pct_chg) }}>
              {r.pct_chg >= 0 ? '+' : ''}{r.pct_chg?.toFixed(2)}%
            </span>
          ),
        },
      ]}
    />
  );
}
