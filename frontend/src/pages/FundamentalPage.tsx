import { Empty } from 'antd';
import Panel from '../components/Panel';

export default function FundamentalPage() {
  return (
    <div className="flex flex-col h-full items-center justify-center" style={{ padding: 18, gap: 12 }}>
      <Panel className="w-full max-w-lg" style={{ textAlign: 'center', padding: '48px 24px' }}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <div>
              <div style={{ color: '#e6f1fa', fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
                基本面分析
              </div>
              <div style={{ color: '#93a9bc', fontSize: 13 }}>
                行业画像 · 公司筛选器 · 财务评分
              </div>
              <div style={{ color: '#64748b', fontSize: 12, marginTop: 12 }}>
                待 B-Step4 完成后上线
              </div>
            </div>
          }
        />
      </Panel>
    </div>
  );
}
