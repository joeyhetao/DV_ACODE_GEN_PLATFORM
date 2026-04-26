import { apiClient } from './client'

export interface LoginParams { username: string; password: string }
export interface UserInfo { id: string; username: string; email: string; role: string; is_active: boolean }

export const authApi = {
  login: async (params: LoginParams) => {
    const form = new FormData()
    form.append('username', params.username)
    form.append('password', params.password)
    const res = await apiClient.post<{ access_token: string; token_type: string }>('/auth/login', form)
    return res.data
  },
  me: async () => {
    const res = await apiClient.get<UserInfo>('/auth/me')
    return res.data
  },
  register: async (data: { username: string; email: string; password: string }) => {
    const res = await apiClient.post<UserInfo>('/auth/register', data)
    return res.data
  },
}
