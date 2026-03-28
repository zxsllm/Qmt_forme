import { useQuery } from '@tanstack/react-query';
import { api, type RankingRow } from '../../services/api';
import RankTable, { pctColor } from './RankTable';

interface Props {
  onStockClick?: (tsCode: string) => void;
}

export default function StockGainPanel({ onStockClick }: Props) {
  const { data } = useQuery({
    queryKey: ['market-rankings', 'gain'],
    queryFn: () => api.marketRankings('gain', 10),
    refetchInterval: 30_000,
  });

  return (
    <RankTable<RankingRow>
      title="涨幅榜 TOP10"
      data={data?.data ?? []}
      onRowClick={onStockClick ? (r) => onStockClick(r.ts_code) : undefined}
      columns={[
        { key: 'name', title: '名称', render: (r) => r.name, width: '36%' },
        {
          key: 'close',
          title: '现价',
          align: 'right',
          render: (r) => <span style={{ color: pctColor(r.pct_chg) }}>{r.close?.toFixed(2)}</span>,
        },
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
      ]}
    />
  );
}
