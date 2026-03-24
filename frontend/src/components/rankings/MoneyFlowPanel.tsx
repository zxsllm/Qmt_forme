import { useQuery } from '@tanstack/react-query';
import { api, type MoneyFlowRow } from '../../services/api';
import RankTable, { pctColor } from './RankTable';

function fmtAmount(v: number | null | undefined): string {
  if (v == null) return '-';
  const abs = Math.abs(v);
  if (abs >= 1e8) return (v / 1e8).toFixed(1) + '亿';
  if (abs >= 1e4) return (v / 1e4).toFixed(1) + '万';
  return v.toFixed(0);
}

export default function MoneyFlowPanel() {
  const { data } = useQuery({
    queryKey: ['moneyflow-top'],
    queryFn: () => api.moneyFlow(10),
    refetchInterval: 30_000,
  });

  return (
    <RankTable<MoneyFlowRow>
      title="主力净流入 TOP10"
      data={data?.data ?? []}
      columns={[
        { key: 'name', title: '名称', render: (r) => r.name, width: '40%' },
        {
          key: 'net',
          title: '净流入',
          align: 'right',
          render: (r) => (
            <span style={{ color: pctColor(r.net_mf_amount) }}>
              {fmtAmount(r.net_mf_amount)}
            </span>
          ),
        },
      ]}
    />
  );
}
