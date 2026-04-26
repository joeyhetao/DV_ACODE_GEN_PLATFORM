import { create } from 'zustand'
import { authApi, UserInfo } from '../api/auth'

interface AuthState {
  user: UserInfo | null
  token: string | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  fetchMe: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: localStorage.getItem('access_token'),
  loading: false,

  login: async (username, password) => {
    set({ loading: true })
    try {
      const { access_token } = await authApi.login({ username, password })
      localStorage.setItem('access_token', access_token)
      const user = await authApi.me()
      set({ token: access_token, user, loading: false })
    } catch (e: unknown) {
      set({ loading: false })
      const err = e as { response?: { data?: { detail?: string } } }
      const detail = err?.response?.data?.detail
      throw new Error(detail || '用户名或密码错误')
    }
  },

  logout: () => {
    localStorage.removeItem('access_token')
    set({ user: null, token: null })
  },

  fetchMe: async () => {
    const token = localStorage.getItem('access_token')
    if (!token) return
    try {
      const user = await authApi.me()
      set({ user })
    } catch {
      localStorage.removeItem('access_token')
      set({ user: null, token: null })
    }
  },
}))
