import axios from 'axios'

export const apiClient = axios.create({
  baseURL: '/api/v1',
  // 全局默认 5min；个别端点（如 /generate/preview）可在 generateApi 里覆盖。
  // thinking 模型 (GLM-4.7 等) 单次推理可达 60s，三次累加可能 180s。
  timeout: 300000,
})

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

apiClient.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('access_token')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)
