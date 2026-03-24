import Panel from '../components/Panel';
import AccountCard from '../components/AccountCard';
import PositionTable from '../components/PositionTable';

export default function PositionsPage() {
  return (
    <div className="flex flex-col h-full" style={{ padding: 18, gap: 12 }}>
      <AccountCard />
      <Panel title="持仓明细" className="flex-1" noPadding>
        <PositionTable />
      </Panel>
    </div>
  );
}
