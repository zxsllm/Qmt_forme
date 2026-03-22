import type { Preview } from '@storybook/react-vite';
import { ConfigProvider, theme } from 'antd';
import '../src/index.css';

const preview: Preview = {
  parameters: {
    layout: 'fullscreen',
  },
  decorators: [
    (Story) => (
      <ConfigProvider
        theme={{
          algorithm: theme.darkAlgorithm,
          token: {
            colorBgContainer: '#151b23',
            colorBgElevated: '#1e2530',
            colorBorder: '#1e2530',
            colorPrimary: '#3b82f6',
            borderRadius: 6,
          },
        }}
      >
        <div style={{ background: '#0d1117', color: '#e2e8f0', minHeight: '100vh', padding: 24 }}>
          <Story />
        </div>
      </ConfigProvider>
    ),
  ],
};

export default preview;
