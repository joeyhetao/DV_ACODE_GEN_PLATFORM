import { apiClient } from './client'

export interface TemplateListItem {
  id: string; name: string; code_type: string; subcategory?: string
  protocol?: string[]; description: string; maturity: string
  is_active: boolean; updated_at: string
}
export interface Template extends TemplateListItem {
  version: string; tags?: string[]; keywords?: string[]
  parameters: Record<string, unknown>[]; template_body: string
  sync_status: string; created_at: string; related_ids?: string[]
}

export const templatesApi = {
  list: async (params?: { code_type?: string; keyword?: string; page?: number; page_size?: number }) => {
    const res = await apiClient.get<TemplateListItem[]>('/templates', { params })
    return res.data
  },
  get: async (id: string) => {
    const res = await apiClient.get<Template>(`/templates/${id}`)
    return res.data
  },
  create: async (data: Record<string, unknown>, force = false) => {
    const res = await apiClient.post(`/templates?force=${force}`, data)
    return res.data
  },
  update: async (id: string, data: Record<string, unknown>) => {
    const res = await apiClient.patch<Template>(`/templates/${id}`, data)
    return res.data
  },
  delete: async (id: string) => {
    await apiClient.delete(`/templates/${id}`)
  },
  versions: async (id: string) => {
    const res = await apiClient.get<unknown[]>(`/templates/${id}/versions`)
    return res.data
  },
}
