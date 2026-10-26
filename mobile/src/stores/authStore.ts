import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface User {
  id: number;
  username: string;
  email: string;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  token: string | null;
  login: (username: string, password: string) => Promise<string | null>;
  register: (username: string, email: string, password: string) => Promise<string | null>;
  logout: () => void;
  loadUser: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      isAuthenticated: false,
      token: null,

      login: async (username, password) => {
        try {
          const res = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
          });

          if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: '登录失败' }));
            return err.detail || `登录失败 (${res.status})`;
          }

          const data = await res.json();
          set({ token: data.access_token, isAuthenticated: true });

          const userRes = await fetch('/api/auth/me', {
            headers: { Authorization: `Bearer ${data.access_token}` },
          });
          if (userRes.ok) {
            const u = await userRes.json();
            set({ user: { id: u.id, username: u.username, email: u.email } });
          }
          return null;
        } catch (e: any) {
          return e.message || '登录失败';
        }
      },

      register: async (username, email, password) => {
        try {
          const res = await fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, email, password }),
          });

          if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: '注册失败' }));
            return err.detail || `注册失败 (${res.status})`;
          }

          const data = await res.json();
          set({ token: data.access_token, isAuthenticated: true });

          const userRes = await fetch('/api/auth/me', {
            headers: { Authorization: `Bearer ${data.access_token}` },
          });
          if (userRes.ok) {
            const u = await userRes.json();
            set({ user: { id: u.id, username: u.username, email: u.email } });
          }
          return null;
        } catch (e: any) {
          return e.message || '注册失败';
        }
      },

      logout: () => {
        set({ user: null, isAuthenticated: false, token: null });
      },

      loadUser: async () => {
        const { token } = get();
        if (!token) return;
        try {
          const res = await fetch('/api/auth/me', {
            headers: { Authorization: `Bearer ${token}` },
          });
          if (!res.ok) {
            set({ user: null, isAuthenticated: false, token: null });
            return;
          }
          const u = await res.json();
          set({ user: { id: u.id, username: u.username, email: u.email }, isAuthenticated: true });
        } catch {
          set({ user: null, isAuthenticated: false, token: null });
        }
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({ token: state.token }),
    }
  )
);
