import { apiClient } from './client'

export interface Contribution {
  id: string; contributor_id: string; code_type: string
  original_intent: string; template_name: string
  subcategory?: string; protocol?: string
  demo_code: string; description: string
  keywords?: string[]; parameter_defs?: unknown
  status: string; reviewer_comment?: string
  promoted_template_id?: string; created_at: string; updated_at: string
  original_row_json?: Record<string, unknown> | null  // v3.0: 保留用户原始 demo
  use_immediately_available?: boolean  // FEAT-10: 前端用于判断是否展示"立即使用"按钮
}

// FEAT-10: 预览端点响应（LLM 基于 original_intent + code_type 一次性生成的 5 字段）
export interface ContributionPreview {
  template_name: string
  description: string
  demo_code: string
  parameter_defs: Array<Record<string, unknown>>
  keywords: string[]
  name_conflict: boolean
}
export interface ContributionListItem {
  id: string; contributor_id: string; code_type: string; template_name: string; status: string; created_at: string
}

// FEAT-4 Layer 3b/c: pre-approve-analysis types
export interface ConflictItem {
  intent: string
  current_template_name: string
  explanation: string
}

export interface PreApproveAnalysisResult {
  has_conflicts: boolean
  conflicts: ConflictItem[]
  new_corpus_preview: string[]
  llm_analysis: string | null
  recommendation_field: string | null
  recommendation_text: string | null
  confidence: number | null
  analysis_id: string
}

export const contributionsApi = {
  submit: async (data: Record<string, unknown>) => {
    const res = await apiClient.post<Contribution>('/contributions', data)
    return res.data
  },
  // FEAT-10: 仅基于 original_intent + code_type 让 LLM 生成预览（不入库）
  preview: async (data: { original_intent: string; code_type: string }) => {
    const res = await apiClient.post<ContributionPreview>('/contributions/preview', data)
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
  analyzeConflicts: async (id: string): Promise<PreApproveAnalysisResult> => {
    const res = await apiClient.post<PreApproveAnalysisResult>(`/contributions/${id}/pre-approve-analysis`)
    return res.data
  },
  approve: async (id: string, analysisId?: string) => {
    const params = analysisId ? { analysis_id: analysisId } : undefined
    const res = await apiClient.post(`/contributions/${id}/approve`, undefined, { params })
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
