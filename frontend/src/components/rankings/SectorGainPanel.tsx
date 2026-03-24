import { useQuery } from '@tanstack/react-query';
import { api, type SectorRankRow } from '../../services/api';
import RankTable, { pctColor } from './RankTable';

export default function SectorGainPanel() {
  const { data } = useQuery({
    queryKey: ['sector-rankings'],
    queryFn: () => api.sectorRankings(30),
    refetchInterval: 30_000,
  });

  const rows = (data?.data ?? []).slice(0, 10);

  return (
    <RankTable<SectorRankRow>
      title="板块涨幅榜"
      data={rows}
      columns={[
        { key: 'name', title: '板块', render: (r) => r.industry, width: '60%' },
        {
          key: 'chg',
          title: '涨幅',
          align: 'right',
          render: (r) => (
            <span style={{ color: pctColor(r.avg_pct_chg) }}>
              {r.avg_pct_chg >= 0 ? '+' : ''}{r.avg_pct_chg?.toFixed(2)}%
            </span>
          ),
        },
      ]}
    />
  );
}
