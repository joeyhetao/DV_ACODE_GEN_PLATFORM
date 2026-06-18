import { apiClient } from './client'

export type ReportCategory =
  | 'wrong_template'
  | 'wrong_params'
  | 'poor_style'
  | 'other'

export type ReportStatus = 'pending' | 'in_review' | 'resolved'

export const REPORT_CATEGORY_OPTIONS: { value: ReportCategory; label: string }[] = [
  { value: 'wrong_template', label: '模板选错' },
  { value: 'wrong_params', label: '参数映射错' },
  { value: 'poor_style', label: '代码风格差' },
  { value: 'other', label: '其他' },
]

export const STATUS_LABELS: Record<ReportStatus, string> = {
  pending: '待审',
  in_review: '审阅中',
  resolved: '已处理',
}

export const STATUS_COLORS: Record<ReportStatus, string> = {
  pending: 'orange',
  in_review: 'blue',
  resolved: 'green',
}

export const CATEGORY_LABELS: Record<ReportCategory, string> = {
  wrong_template: '模板选错',
  wrong_params: '参数映射错',
  poor_style: '代码风格差',
  other: '其他',
}

export interface ImprovementReportCreatePayload {
  rag_record_id: string
  llm_direct_record_id: string
  report_categories?: ReportCategory[]
  reporter_note?: string
}

export interface ImprovementReportCreated {
  id: string
  status: ReportStatus
}

export interface CheckExistsResponse {
  exists: boolean
  report_id: string | null
}

export interface GenerationRecordForReport {
  id: string
  output_code: string | null
  template_id: string | null
  template_name: string | null
  params_used: Record<string, unknown> | null
  original_intent: string | null
  generation_mode: string | null
  cache_hit: boolean
}

export interface ImprovementReportAdminListItem {
  id: string
  status: ReportStatus
  reporter_username: string | null
  rag_template_id: string | null
  rag_template_name: string | null
  categories: string[] | null
  created_at: string
}

export interface ImprovementReportDetail {
  id: string
  status: ReportStatus
  reporter_user_id: string
  reporter_username: string | null
  report_categories: string[] | null
  reporter_note: string | null
  admin_note: string | null
  rag_record: GenerationRecordForReport
  llm_direct_record: GenerationRecordForReport
  created_at: string
  updated_at: string
}

export interface ImprovementReportPatchPayload {
  status?: ReportStatus
  admin_note?: string
}

export const improvementReportsApi = {
  create: async (payload: ImprovementReportCreatePayload) => {
    const res = await apiClient.post<ImprovementReportCreated>('/improvement-reports', payload)
    return res.data
  },
  check: async (rag_record_id: string, llm_direct_record_id: string) => {
    const res = await apiClient.get<CheckExistsResponse>('/improvement-reports/check', {
      params: { rag_record_id, llm_direct_record_id },
    })
    return res.data
  },
  adminList: async (params?: {
    status?: ReportStatus
    categories?: ReportCategory[]
    page?: number
    page_size?: number
  }) => {
    // FastAPI Query(list) 期望 ?categories=a&categories=b 重复 key 形式；
    // 显式 paramsSerializer 防止 axios 默认 categories[]=a 形式
    const res = await apiClient.get<ImprovementReportAdminListItem[]>(
      '/admin/improvement-reports',
      {
        params,
        paramsSerializer: {
          indexes: null,
        },
      },
    )
    return res.data
  },
  adminGet: async (id: string) => {
    const res = await apiClient.get<ImprovementReportDetail>(`/admin/improvement-reports/${id}`)
    return res.data
  },
  adminPatch: async (id: string, payload: ImprovementReportPatchPayload) => {
    const res = await apiClient.patch<ImprovementReportDetail>(
      `/admin/improvement-reports/${id}`,
      payload,
    )
    return res.data
  },
}
