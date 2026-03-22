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
          colorBgContainer: '#151b23',
          colorBgElevated: '#1e2530',
          colorBorder: '#1e2530',
          colorPrimary: '#3b82f6',
          borderRadius: 6,
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
