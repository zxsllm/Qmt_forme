import Panel from '../components/Panel';
import AccountCard from '../components/AccountCard';
import PositionTable from '../components/PositionTable';

export default function PositionsPage() {
  return (
    <div className="flex flex-col h-full bg-bg-base" style={{ padding: 16, gap: 10 }}>
      <AccountCard />
      <Panel title="持仓明细" className="flex-1" noPadding>
        <PositionTable />
      </Panel>
    </div>
  );
}
