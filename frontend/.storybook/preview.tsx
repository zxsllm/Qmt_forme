import React from 'react';
import type { Preview } from '@storybook/react-vite';
import { ConfigProvider, theme } from 'antd';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import '../src/index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: Infinity, retry: false },
  },
});

const preview: Preview = {
  parameters: {
    layout: 'fullscreen',
  },
  decorators: [
    (Story) => (
      <QueryClientProvider client={queryClient}>
        <ConfigProvider
          theme={{
            algorithm: theme.darkAlgorithm,
            token: {
              colorBgContainer: '#0e1c29',
              colorBgElevated: '#102231',
              colorBorder: 'rgba(148,186,215,0.18)',
              colorPrimary: '#6bc7ff',
              borderRadius: 14,
            },
          }}
        >
          <div
            style={{
              background: 'linear-gradient(160deg, #041019 0%, #081a27 42%, #09131c 100%)',
              color: '#e6f1fa',
              minHeight: '100vh',
              padding: 24,
            }}
          >
            <Story />
          </div>
        </ConfigProvider>
      </QueryClientProvider>
    ),
  ],
};

export default preview;
