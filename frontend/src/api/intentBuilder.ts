import { apiClient } from './client'

// ── v3.0 多轮对话 schema ──────────────────────────────────────────────
export interface RAGCandidateBrief {
  template_id: string
  name: string
  description: string
  score: number
}

export interface IntentBuilderChatRequest {
  session_id: string                    // 空字符串 = 首轮（后端 mint 新 id）
  user_message: string
  code_type: string
}

export interface IntentBuilderChatResponse {
  session_id: string                    // 永远填充
  assistant_message: string             // 已剥离 <<intent>>...<<end>> 段
  accumulated_intent: string            // LLM 累计的标准化意图
  rag_candidates: RAGCandidateBrief[]
  suggest_contribute: boolean           // True 时前端展示「贡献新模板」入口
  turn_count: number
}

// v2 scenarios / build 端点已退役（v3.0 PRD §3.8.4），后端返 410 Gone；前端 v3.0 之后
// 无任何调用方——P1-12 删除导出避免遗留依赖。
export const intentBuilderApi = {
  chat: async (req: IntentBuilderChatRequest) => {
    const res = await apiClient.post<IntentBuilderChatResponse>('/intent-builder/chat', req)
    return res.data
  },
}
