import { apiClient } from './client'

export interface BatchJob {
  job_id: string
  status: string
  total_rows: number
  completed_rows: number
  progress: number
  result_url?: string
  error_message?: string
}
export interface PreflightRowResult { row_id: string; estimated_confidence: number; top_match?: Record<string, unknown> }

export const batchApi = {
  upload: async (file: File, code_type: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('code_type', code_type)
    const res = await apiClient.post<{ job_id: string; total_rows: number; code_type: string; status: string }>('/batch/upload', form)
    return res.data
  },
  status: async (job_id: string) => {
    const res = await apiClient.get<BatchJob>(`/batch/${job_id}/status`)
    return res.data
  },
  download: async (job_id: string) => {
    const res = await apiClient.get(`/batch/${job_id}/download`, { responseType: 'blob' })
    const url = URL.createObjectURL(res.data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `batch_result_${job_id}.zip`
    a.click()
    URL.revokeObjectURL(url)
  },
  preflight: async (file: File, code_type: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('code_type', code_type)
    const res = await apiClient.post<{ results: PreflightRowResult[] }>('/batch/preflight', form)
    return res.data
  },
  downloadTemplate: async () => {
    const res = await apiClient.get('/batch/template', { responseType: 'blob' })
    const url = URL.createObjectURL(res.data as Blob)
    const a = document.createElement('a')
    a.href = url
    // 从 Content-Disposition 提取文件名，兼容 quoted-string 与 token 两种 RFC 6266
    // 形式（`filename="x.xlsx"` 或 `filename=x.xlsx`）；找不到时退化为客户端当前日期
    const cd = (res.headers['content-disposition'] as string) || ''
    const match = cd.match(/filename\*?=\s*"?([^";]+)"?/)
    a.download = match
      ? match[1].trim()
      : `batch_template_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.xlsx`
    a.click()
    URL.revokeObjectURL(url)
  },
}
