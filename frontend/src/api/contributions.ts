import { apiClient } from './client'

export interface Contribution {
  id: string; contributor_id: string; code_type: string
  original_intent: string; template_name: string
  subcategory?: string; protocol?: string
  demo_code: string; description: string
  keywords?: string[]; parameter_defs?: unknown
  status: string; reviewer_comment?: string
  promoted_template_id?: string; created_at: string; updated_at: string
}
export interface ContributionListItem {
  id: string; contributor_id: string; code_type: string; template_name: string; status: string; created_at: string
}

export const contributionsApi = {
  submit: async (data: Record<string, unknown>) => {
    const res = await apiClient.post<Contribution>('/contributions', data)
    return res.data
  },
  my: async (params?: { page?: number; page_size?: number }) => {
    const res = await apiClient.get<ContributionListItem[]>('/contributions/my', { params })
    return res.data
  },
  get: async (id: string) => {
    const res = await apiClient.get<Contribution>(`/contributions/${id}`)
    return res.data
  },
  update: async (id: string, data: Record<string, unknown>) => {
    const res = await apiClient.patch<Contribution>(`/contributions/${id}`, data)
    return res.data
  },
  adminList: async (params?: { status?: string; page?: number }) => {
    const res = await apiClient.get<ContributionListItem[]>('/contributions/admin/all', { params })
    return res.data
  },
  approve: async (id: string) => {
    const res = await apiClient.post(`/contributions/${id}/approve`)
    return res.data
  },
  reject: async (id: string, comment?: string) => {
    const res = await apiClient.post(`/contributions/${id}/reject`, { comment })
    return res.data
  },
  requestRevision: async (id: string, comment?: string) => {
    const res = await apiClient.post(`/contributions/${id}/request-revision`, { comment })
    return res.data
  },
}
