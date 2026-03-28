import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, type SectorRankRow } from '../../services/api';
import RankTable, { pctColor } from './RankTable';
import SectorDetailModal from './SectorDetailModal';

interface Props {
  onStockClick?: (tsCode: string) => void;
}

export default function SectorLosePanel({ onStockClick }: Props) {
  const { data } = useQuery({
    queryKey: ['sector-rankings'],
    queryFn: () => api.sectorRankings(30),
    refetchInterval: 30_000,
  });

  const [selected, setSelected] = useState<string | null>(null);
  const all = data?.data ?? [];
  const rows = [...all].reverse().slice(0, 10);

  return (
    <>
      <RankTable<SectorRankRow>
        title="板块跌幅榜"
        data={rows}
        onRowClick={(r) => setSelected(r.industry)}
        columns={[
          { key: 'name', title: '板块', render: (r) => r.industry, width: '60%' },
          {
            key: 'chg',
            title: '跌幅',
            align: 'right',
            render: (r) => (
              <span style={{ color: pctColor(r.avg_pct_chg) }}>
                {r.avg_pct_chg >= 0 ? '+' : ''}{r.avg_pct_chg?.toFixed(2)}%
              </span>
            ),
          },
        ]}
      />
      <SectorDetailModal industry={selected} onClose={() => setSelected(null)} onStockClick={onStockClick} />
    </>
  );
}
