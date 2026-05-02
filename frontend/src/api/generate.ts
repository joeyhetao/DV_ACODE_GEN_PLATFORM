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

// ── 方案 3 两步式 schema ────────────────────────────────────────────
export type ParamSource = 'signal_list' | 'regex' | 'llm' | 'default' | 'placeholder'
export type ConfidenceSource = 'llm_step1' | 'rag_fallback' | 'intent_cache'

export interface ParamWithSource {
  value: string | number | string[]
  source: ParamSource
  required: boolean
  description: string
  type: string
}

export interface RAGCandidateWithParams {
  template_id: string
  name: string
  score: number
  parameters: Array<Record<string, unknown>>
}

export interface PreviewResponse {
  template_id: string
  template_name: string
  template_version: string
  confidence: number
  confidence_source: ConfidenceSource
  rag_candidates: RAGCandidateWithParams[]
  params: Record<string, ParamWithSource>
  intent_hash: string
  normalized_intent: string
  quick_render: boolean
}

export interface RenderConfirmedRequest {
  template_id: string
  template_version: string
  params: Record<string, unknown>
  intent_hash: string
  confidence: number
  confidence_source: ConfidenceSource
  normalized_intent: string
  original_intent: string
  rag_candidates: Array<{ template_id: string; name: string; score: number }>
  code_type: string
}

export interface RenderConfirmedResponse {
  code: string
  cache_hit: boolean
}

export const generateApi = {
  generate: async (req: GenerateRequest) => {
    // legacy 一步式（保留兼容用）
    const res = await apiClient.post<GenerateResponse>('/generate', req, { timeout: 180000 })
    return res.data
  },
  // 方案 3 两步式
  preview: async (req: GenerateRequest) => {
    // GLM 调用慢，给 3min 超时
    const res = await apiClient.post<PreviewResponse>('/generate/preview', req, { timeout: 180000 })
    return res.data
  },
  renderConfirmed: async (req: RenderConfirmedRequest) => {
    // 渲染只调 Jinja2，<1s；用户参数可能略慢但不会超 30s
    const res = await apiClient.post<RenderConfirmedResponse>('/generate/render', req, { timeout: 30000 })
    return res.data
  },
  // legacy 重渲染（仅渲染不写库，不传 intent_hash）
  render: async (template_id: string, template_version: string, params: Record<string, unknown>) => {
    const res = await apiClient.post<{ code: string }>('/generate/render', { template_id, template_version, params })
    return res.data
  },
  codeTypes: async () => {
    const res = await apiClient.get<{ id: string; display_name: string }[]>('/generate/code-types')
    return res.data
  },
}
