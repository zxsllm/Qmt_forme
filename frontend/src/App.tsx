import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ConfigProvider, theme } from 'antd';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import MainLayout from './layouts/MainLayout';
import Dashboard from './pages/Dashboard';
import KlinePage from './pages/KlinePage';
import PositionsPage from './pages/PositionsPage';
import OrdersPage from './pages/OrdersPage';
import HistoryPage from './pages/HistoryPage';
import RiskPage from './pages/RiskPage';
import StrategyPage from './pages/StrategyPage';
import BacktestPage from './pages/BacktestPage';

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
              <Route path="/kline" element={<KlinePage />} />
              <Route path="/positions" element={<PositionsPage />} />
              <Route path="/orders" element={<OrdersPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/risk" element={<RiskPage />} />
              <Route path="/strategy" element={<StrategyPage />} />
              <Route path="/backtest" element={<BacktestPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </ConfigProvider>
  );
}
