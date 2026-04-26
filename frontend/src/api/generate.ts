import { apiClient } from './client'

export interface SignalInfo { name: string; width: number; role: string }
export interface GenerateRequest {
  text: string
  code_type: string
  protocol?: string
  clk?: string
  rst?: string
  rst_polarity?: string
  signals?: SignalInfo[]
}
export interface RAGCandidate { template_id: string; name: string; score: number }
export interface GenerateResponse {
  status: string
  confidence: number
  template_id: string
  template_version: string
  cache_hit: boolean
  intent_cache_hit: boolean
  rag_candidates: RAGCandidate[]
  params_used: Record<string, unknown>
  code: string
}

export const generateApi = {
  generate: async (req: GenerateRequest) => {
    const res = await apiClient.post<GenerateResponse>('/generate', req)
    return res.data
  },
  render: async (template_id: string, template_version: string, params: Record<string, unknown>) => {
    const res = await apiClient.post<{ code: string }>('/generate/render', { template_id, template_version, params })
    return res.data
  },
  codeTypes: async () => {
    const res = await apiClient.get<{ id: string; display_name: string }[]>('/generate/code-types')
    return res.data
  },
}
