import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { User } from '@/types';
import { authApi } from '@/api';

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
          const res = await authApi.login(username, password);
          set({ token: res.access_token, isAuthenticated: true });

          // 获取用户信息
          const userRes = await authApi.me();
          set({
            user: {
              id: userRes.id,
              username: userRes.username,
              email: userRes.email,
              avatar: userRes.avatar || undefined,
              createdAt: userRes.created_at,
            },
          });
          return null;
        } catch (e: any) {
          return e.message || '登录失败';
        }
      },

      register: async (username, email, password) => {
        try {
          const res = await authApi.register(username, email, password);
          set({ token: res.access_token, isAuthenticated: true });

          const userRes = await authApi.me();
          set({
            user: {
              id: userRes.id,
              username: userRes.username,
              email: userRes.email,
              avatar: userRes.avatar || undefined,
              createdAt: userRes.created_at,
            },
          });
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
          const userRes = await authApi.me();
          set({
            user: {
              id: userRes.id,
              username: userRes.username,
              email: userRes.email,
              avatar: userRes.avatar || undefined,
              createdAt: userRes.created_at,
            },
            isAuthenticated: true,
          });
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
