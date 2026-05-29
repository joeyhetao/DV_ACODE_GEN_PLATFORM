import { apiClient } from './client'

export type ReasonTag =
  | 'wrong_template'
  | 'hallucinated_signal'
  | 'syntax_error'
  | 'semantic_error'
  | 'style_bad'
  | 'missing_disable_iff'
  | 'other'

export interface FeedbackPayload {
  rating: 1 | 2 | 3
  reason_tags?: ReasonTag[]
  comment?: string
}

export const feedbackApi = {
  submit: async (generationRecordId: string, payload: FeedbackPayload): Promise<void> => {
    await apiClient.post(`/feedback/${generationRecordId}`, payload)
  },
}

export const REASON_TAG_OPTIONS: { value: ReasonTag; label: string }[] = [
  { value: 'wrong_template', label: '模板选错' },
  { value: 'hallucinated_signal', label: '幻觉信号名' },
  { value: 'syntax_error', label: '语法错误' },
  { value: 'semantic_error', label: '语义错误' },
  { value: 'style_bad', label: '风格不佳' },
  { value: 'missing_disable_iff', label: '缺少 disable iff' },
  { value: 'other', label: '其他' },
]
