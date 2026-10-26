/**
 * HTTP 请求客户端
 * 基于 fetch 的轻量级 API 客户端，支持 JWT 认证
 */
import { useAuthStore } from '@/stores';

const API_BASE = '/api';

interface ApiError {
  detail: string;
}

class RequestClient {
  private getToken(): string | null {
    return useAuthStore.getState().token;
  }

  private async request<T>(
    path: string,
    options: RequestInit = {}
  ): Promise<T> {
    const token = this.getToken();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string>),
    };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
    });

    if (res.status === 401) {
      useAuthStore.getState().logout();
      window.location.hash = '#/login';
      throw new Error('登录已过期，请重新登录');
    }

    if (!res.ok) {
      const err: ApiError = await res.json().catch(() => ({ detail: '请求失败' }));
      throw Object.assign(new Error(err.detail || `请求失败 (${res.status})`), {
        response: { data: err, status: res.status },
      });
    }

    // 204 No Content
    if (res.status === 204) return undefined as T;
    return res.json();
  }

  get<T>(path: string, params?: Record<string, string>) {
    const query = params ? '?' + new URLSearchParams(params).toString() : '';
    return this.request<T>(path + query);
  }

  post<T>(path: string, body?: unknown) {
    return this.request<T>(path, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  put<T>(path: string, body?: unknown) {
    return this.request<T>(path, {
      method: 'PUT',
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  delete<T>(path: string) {
    return this.request<T>(path, { method: 'DELETE' });
  }
}

export const request = new RequestClient();
export default request;