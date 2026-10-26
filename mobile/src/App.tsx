import { useEffect, useState } from 'react';
import { AIAssistant } from '@/pages/AIAssistant';
import { useAuthStore } from '@/stores/authStore';

// ── 登录/注册弹窗 ──────────────────────────────────────────────────────────
function AuthModal() {
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const login = useAuthStore((s) => s.login);
  const register = useAuthStore((s) => s.register);

  const switchMode = () => {
    setIsRegister(!isRegister);
    setError('');
  };

  const handleSubmit = async () => {
    if (!username.trim() || !password.trim()) {
      setError('请输入用户名和密码');
      return;
    }
    if (isRegister && !email.trim()) {
      setError('请输入邮箱');
      return;
    }
    setLoading(true);
    setError('');
    const err = isRegister
      ? await register(username, email, password)
      : await login(username, password);
    if (err) setError(err);
    setLoading(false);
  };

  return (
    <div className="flex flex-col items-center justify-center h-screen h-[100dvh] bg-gray-50 px-6">
      <div className="w-14 h-14 rounded-2xl bg-primary-600 flex items-center justify-center mb-4 shadow-lg shadow-primary-600/20">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 2L2 7l10 5 10-5-10-5z" />
          <path d="M2 17l10 5 10-5" />
          <path d="M2 12l10 5 10-5" />
        </svg>
      </div>
      <h1 className="text-xl font-bold text-gray-900 mb-1">AI股票研究助手</h1>
      <p className="text-xs text-gray-400 mb-8">{isRegister ? '创建账号' : '登录后即可使用'}</p>

      <div className="w-full max-w-xs space-y-3">
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="用户名"
          className="w-full px-4 py-2.5 bg-white border border-gray-200 rounded-xl text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-shadow"
          autoComplete="username"
        />
        {isRegister && (
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="邮箱"
            className="w-full px-4 py-2.5 bg-white border border-gray-200 rounded-xl text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-shadow"
            autoComplete="email"
          />
        )}
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="密码"
          className="w-full px-4 py-2.5 bg-white border border-gray-200 rounded-xl text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 transition-shadow"
          autoComplete={isRegister ? 'new-password' : 'current-password'}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
        />
        {error && <p className="text-xs text-red-500 text-center">{error}</p>}
        <button
          onClick={handleSubmit}
          disabled={loading}
          className="w-full py-2.5 bg-primary-600 text-white font-semibold rounded-xl text-sm disabled:opacity-50 active:bg-primary-700 transition-colors shadow-sm shadow-primary-600/20"
        >
          {loading ? '请稍候…' : isRegister ? '注册' : '登录'}
        </button>
        <button
          onClick={switchMode}
          className="w-full py-2 text-xs text-primary-600 font-medium"
        >
          {isRegister ? '已有账号？去登录' : '没有账号？去注册'}
        </button>
      </div>
    </div>
  );
}

export function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const loadUser = useAuthStore((s) => s.loadUser);

  useEffect(() => {
    loadUser();
  }, [loadUser]);

  if (!isAuthenticated) {
    return <AuthModal />;
  }

  return <AIAssistant />;
}
