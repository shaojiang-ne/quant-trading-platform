import { api } from './client';

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface UserResponse {
  id: string;
  username: string;
  email: string;
  avatar: string | null;
  created_at: string;
}

export const authApi = {
  login: (username: string, password: string) =>
    api.post<LoginResponse>('/auth/login', { username, password }),

  register: (username: string, email: string, password: string) =>
    api.post<LoginResponse>('/auth/register', { username, email, password }),

  me: () => api.get<UserResponse>('/auth/me'),
};
