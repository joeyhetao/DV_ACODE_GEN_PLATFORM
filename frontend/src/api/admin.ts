import { apiClient } from './client'

export interface LLMConfig {
  id: string; name: string; provider: string; base_url?: string
  api_key_masked: string; model_id: string; output_mode: string
  temperature: number; max_tokens: number; is_active: boolean
  is_default: boolean; created_at: string; updated_at: string
}

export const adminApi = {
  users: {
    list: async (params?: { page?: number; page_size?: number }) => {
      const res = await apiClient.get('/admin/users', { params })
      return res.data
    },
    setRole: async (user_id: string, role: string) => {
      const res = await apiClient.patch(`/admin/users/${user_id}/role`, { role })
      return res.data
    },
    setActive: async (user_id: string, active: boolean) => {
      const res = await apiClient.patch(`/admin/users/${user_id}/activate`, null, { params: { active } })
      return res.data
    },
  },
  stats: async () => {
    const res = await apiClient.get('/admin/stats')
    return res.data
  },
  auditLogs: async (params?: { action?: string; operator_id?: string; page?: number }) => {
    const res = await apiClient.get('/admin/audit-logs', { params })
    return res.data
  },
  backup: async () => {
    const res = await apiClient.post('/admin/backup')
    return res.data
  },
  llm: {
    list: async () => {
      const res = await apiClient.get<LLMConfig[]>('/admin/llm/configs')
      return res.data
    },
    create: async (data: Record<string, unknown>) => {
      const res = await apiClient.post<LLMConfig>('/admin/llm/configs', data)
      return res.data
    },
    update: async (id: string, data: Record<string, unknown>) => {
      const res = await apiClient.patch<LLMConfig>(`/admin/llm/configs/${id}`, data)
      return res.data
    },
    delete: async (id: string) => {
      await apiClient.delete(`/admin/llm/configs/${id}`)
    },
    setDefault: async (id: string) => {
      const res = await apiClient.post(`/admin/llm/configs/${id}/set-default`)
      return res.data
    },
    test: async (id: string) => {
      const res = await apiClient.post(`/admin/llm/configs/${id}/test`, { test_type: 'basic' })
      return res.data
    },
  },
}
