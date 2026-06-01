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
export type ParamSource = 'signal_list' | 'regex' | 'llm' | 'default' | 'semantic_fallback' | 'placeholder'
export type ConfidenceSource = 'llm_step1' | 'rag_fallback' | 'intent_cache' | 'keyword_supplement'

export interface ParamWithSource {
  value: string | number | string[]
  source: ParamSource
  required: boolean
  description: string
  type: string
  sanitized?: boolean              // 后端做过 SV 标识符清洗
  expr_type?: string               // 模板 YAML 声明的语法类型（驱动前端 dispatch 校验）
  validation_error?: string        // sv_boolean_expr / sv_bins_expr 校验失败时的错误描述
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

export type GenerationMode = 'rag' | 'llm_direct'

export interface RenderConfirmedResponse {
  code: string
  cache_hit: boolean
  generation_record_id?: string | null
  // FEAT-11 Stage 2：默认 'rag'；前端用此决定是否显示 LLM fallback 按钮
  generation_mode?: GenerationMode
}

export interface LLMFallbackResponse {
  code: string
  generation_record_id: string
  generation_mode: 'llm_direct'
  cache_hit: boolean
}

export const generateApi = {
  generate: async (req: GenerateRequest) => {
    // legacy 一步式（保留兼容用）。thinking 模型 worst case 3 次 LLM × 60s。
    const res = await apiClient.post<GenerateResponse>('/generate', req, { timeout: 300000 })
    return res.data
  },
  // 方案 3 两步式
  preview: async (req: GenerateRequest) => {
    // thinking 模型（GLM-4.7 等）单次推理 20-60s，三次累加 60-180s，给 5min 留 buffer。
    const res = await apiClient.post<PreviewResponse>('/generate/preview', req, { timeout: 300000 })
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
  // FEAT-11 Stage 2：用户点"对生成结果不满意？尝试 LLM 直接生成"时触发
  llmFallback: async (generation_record_id: string) => {
    // freeform 生成走单次 LLM 调用：GLM-4.7 thinking off p50≈3s；为兼容偏慢的
    // thinking-on 模型（曾观察到 60-120s 偶发），设 120s timeout。比 preview 端
    // 的 5min 短（preview 是三段 LLM 累加），但对单次调用足够。
    const res = await apiClient.post<LLMFallbackResponse>(
      '/generate/llm-fallback',
      { generation_record_id },
      { timeout: 120000 },
    )
    return res.data
  },
}
