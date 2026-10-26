import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useEffect } from 'react';
import { Layout } from '@/components';
import { WebSocketProvider } from '@/components/WebSocketProvider';
import {
  SimulationTrading,
  Trading,
  FactorBoard,
  TradingData,
  AIAssistant,
  Settings,
  Login,
  StrategyWorkspace,
  AIAgent,
  Landing,
} from '@/pages';
import { useAuthStore } from '@/stores';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const loadUser = useAuthStore((s) => s.loadUser);

  // 恢复登录状态
  useEffect(() => {
    loadUser();
  }, [loadUser]);

  return (
    <HashRouter>
      <Routes>
        {/* 公开页面 */}
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={isAuthenticated ? <Navigate to="/app" replace /> : <Login />} />

        {/* 需认证的应用页面 */}
        <Route path="/app" element={<ProtectedRoute><WebSocketProvider><Layout /></WebSocketProvider></ProtectedRoute>}>
          <Route index element={<Navigate to="/app/ai-assistant" replace />} />
          <Route path="ai-assistant" element={<AIAssistant />} />
          <Route path="ai-agent" element={<AIAgent />} />
          <Route path="strategy-workspace" element={<StrategyWorkspace />} />
          <Route path="simulation" element={<SimulationTrading />} />
          <Route path="trading" element={<Trading />} />
          <Route path="factor-board" element={<FactorBoard />} />
          <Route path="trading-data" element={<TradingData />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/app/ai-assistant" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
