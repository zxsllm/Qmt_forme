import { useQuery } from '@tanstack/react-query';
import { api, type RankingRow } from '../../services/api';
import RankTable, { pctColor } from './RankTable';

export default function TurnoverPanel() {
  const { data } = useQuery({
    queryKey: ['market-rankings', 'turnover'],
    queryFn: () => api.marketRankings('turnover', 10),
    refetchInterval: 30_000,
  });

  return (
    <RankTable<RankingRow>
      title="换手率榜 TOP10"
      data={data?.data ?? []}
      columns={[
        { key: 'name', title: '名称', render: (r) => r.name, width: '36%' },
        {
          key: 'chg',
          title: '涨幅',
          align: 'right',
          render: (r) => (
            <span style={{ color: pctColor(r.pct_chg) }}>
              {r.pct_chg >= 0 ? '+' : ''}{r.pct_chg?.toFixed(2)}%
            </span>
          ),
        },
        {
          key: 'turnover',
          title: '换手率',
          align: 'right',
          render: (r) => `${r.turnover_rate?.toFixed(1) ?? '-'}%`,
        },
      ]}
    />
  );
}
