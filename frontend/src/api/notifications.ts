import { apiClient } from './client'

export interface Notification {
  id: string; type: string; payload: Record<string, unknown>; is_read: boolean; created_at: string
}

export const notificationsApi = {
  list: async (params?: { unread_only?: boolean; page?: number }) => {
    const res = await apiClient.get<{ total_unread: number; notifications: Notification[] }>('/notifications', { params })
    return res.data
  },
  markRead: async (id: string) => {
    await apiClient.post(`/notifications/${id}/read`)
  },
  markAllRead: async () => {
    await apiClient.post('/notifications/read-all')
  },
}
