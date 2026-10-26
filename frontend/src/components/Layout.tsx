import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/stores';
import {
  FlaskConical,
  Settings,
  TrendingUp,
  Cpu,
  BarChart3,
  LogOut,
  Sparkles,
  Brain,
  ChevronsLeft,
  ChevronsRight,
  Database,
} from 'lucide-react';

export function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const mainRef = useRef<HTMLElement>(null);
  const { user, logout } = useAuthStore();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    mainRef.current?.scrollTo(0, 0);
  }, [location.pathname]);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };
  const navItems = [
    { path: '/app/ai-assistant', icon: Sparkles, label: 'AI分析' },
    { path: '/app/ai-agent', icon: Brain, label: 'AI智能体' },
    { path: '/app/factor-board', icon: BarChart3, label: '因子看板' },
    { path: '/app/strategy-workspace', icon: FlaskConical, label: '策略与回测' },
    { path: '/app/simulation', icon: Cpu, label: '模拟交易' },
    { path: '/app/trading', icon: TrendingUp, label: '实盘交易' },
    { path: '/app/trading-data', icon: Database, label: '数据源' },
    { path: '/app/settings', icon: Settings, label: '系统设置' },
  ];

  return (
    <div className="flex h-screen bg-gray-50">
      {/* 侧边栏 */}
      <aside
        className={`${collapsed ? 'w-16' : 'w-64'} bg-white border-r border-gray-200 flex flex-col transition-all duration-300`}
      >
        <div className="p-4 border-b border-gray-200">
          <h1 className="text-xl font-bold text-primary-600 flex items-center gap-2">
            <TrendingUp className="w-6 h-6 shrink-0" />
            {!collapsed && (
              <span className="overflow-hidden whitespace-nowrap transition-opacity duration-200">
                量化交易平台
              </span>
            )}
          </h1>
          {!collapsed && (
            <p className="text-xs text-gray-500 mt-1 overflow-hidden whitespace-nowrap transition-opacity duration-200">
              Quant Trading Pro
            </p>
          )}
        </div>

        <nav className="flex-1 p-2">
          <ul className="space-y-1">
            {navItems.map((item) => (
              <li key={item.path}>
                <NavLink
                  to={item.path}
                  title={collapsed ? item.label : undefined}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3 py-3 rounded-lg transition-colors ${
                      isActive
                        ? 'bg-primary-50 text-primary-600 font-medium'
                        : 'text-gray-600 hover:bg-gray-100'
                    } ${collapsed ? 'justify-center' : ''}`
                  }
                >
                  <item.icon className="w-5 h-5 shrink-0" />
                  {!collapsed && (
                    <span className="overflow-hidden whitespace-nowrap transition-opacity duration-200">
                      {item.label}
                    </span>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="p-2 border-t border-gray-200">
          <div className={`flex items-center gap-3 px-2 py-2 ${collapsed ? 'justify-center' : ''}`}>
            <div className="w-8 h-8 rounded-full bg-primary-100 flex items-center justify-center shrink-0">
              <span className="text-sm font-medium text-primary-600">{user?.username?.[0]?.toUpperCase() || 'U'}</span>
            </div>
            {!collapsed && (
              <>
                <div className="flex-1 min-w-0 overflow-hidden">
                  <p className="text-sm font-medium text-gray-900 truncate">{user?.username || '用户'}</p>
                  <p className="text-xs text-gray-500">Pro 版本</p>
                </div>
                <button
                  onClick={handleLogout}
                  className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
                  title="退出登录"
                >
                  <LogOut className="w-4 h-4" />
                </button>
              </>
            )}
          </div>
        </div>

        {/* 收起/展开按钮 */}
        <div className="p-2 border-t border-gray-200">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className={`flex items-center gap-3 w-full px-3 py-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors ${collapsed ? 'justify-center' : ''}`}
            title={collapsed ? '展开菜单' : '收起菜单'}
          >
            {collapsed ? (
              <ChevronsRight className="w-5 h-5 shrink-0" />
            ) : (
              <>
                <ChevronsLeft className="w-5 h-5 shrink-0" />
                <span className="text-sm overflow-hidden whitespace-nowrap transition-opacity duration-200">收起菜单</span>
              </>
            )}
          </button>
        </div>
      </aside>

      {/* 主内容区 */}
      <main ref={mainRef} className="flex-1 overflow-auto flex flex-col">
        <div className="p-8 flex-1 min-h-0">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
