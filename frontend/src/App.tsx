import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ConfigProvider, theme } from 'antd';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import MainLayout from './layouts/MainLayout';
import Dashboard from './pages/Dashboard';
import TradingPage from './pages/TradingPage';
import StrategyPage from './pages/StrategyPage';
import SystemPage from './pages/SystemPage';
import NewsPage from './pages/NewsPage';
import SentimentPage from './pages/SentimentPage';
import FundamentalPage from './pages/FundamentalPage';
import MonitorPage from './pages/MonitorPage';
import CommandCenter from './pages/CommandCenter';

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
});

export default function App() {
  return (
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
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Routes>
            <Route element={<MainLayout />}>
              <Route index element={<Dashboard />} />
              <Route path="/command" element={<CommandCenter />} />
              <Route path="/trading" element={<TradingPage />} />
              <Route path="/strategy" element={<StrategyPage />} />
              <Route path="/system" element={<SystemPage />} />
              <Route path="/news" element={<NewsPage />} />
              <Route path="/sentiment" element={<SentimentPage />} />
              <Route path="/fundamental" element={<FundamentalPage />} />
              <Route path="/monitor" element={<MonitorPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </ConfigProvider>
  );
}
