import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Spin } from 'antd'
import { useAuthStore } from './store/authStore'
import MainLayout from './components/MainLayout'
import LoginPage from './pages/Login'
import GeneratePage from './pages/Generate/GeneratePage'
import BatchPage from './pages/Batch/BatchPage'
import LibraryPage from './pages/Library/LibraryPage'
import MyContributionsPage from './pages/MyContributions/MyContributionsPage'
import IntentBuilderPage from './pages/IntentBuilder/IntentBuilderPage'
import AdminTemplatesPage from './pages/Admin/AdminTemplatesPage'
import AdminContributionsPage from './pages/Admin/AdminContributionsPage'
import AdminLLMPage from './pages/Admin/AdminLLMPage'
import AdminUsersPage from './pages/Admin/AdminUsersPage'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token)
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function RequireAdmin({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user)
  if (!user) return <Navigate to="/login" replace />
  if (!['lib_admin', 'super_admin'].includes(user.role)) return <Navigate to="/" replace />
  return <>{children}</>
}

export default function App() {
  const { token, user, fetchMe } = useAuthStore()

  useEffect(() => {
    if (token && !user) fetchMe()
  }, [token, user, fetchMe])

  if (token && !user) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spin size="large" tip="加载中…" />
      </div>
    )
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<RequireAuth><MainLayout /></RequireAuth>}>
          <Route index element={<Navigate to="/generate" replace />} />
          <Route path="generate" element={<GeneratePage />} />
          <Route path="batch" element={<BatchPage />} />
          <Route path="library" element={<LibraryPage />} />
          <Route path="my-contributions" element={<MyContributionsPage />} />
          <Route path="intent-builder" element={<IntentBuilderPage />} />
          <Route path="admin/templates" element={<RequireAdmin><AdminTemplatesPage /></RequireAdmin>} />
          <Route path="admin/contributions" element={<RequireAdmin><AdminContributionsPage /></RequireAdmin>} />
          <Route path="admin/llm" element={<RequireAdmin><AdminLLMPage /></RequireAdmin>} />
          <Route path="admin/users" element={<RequireAdmin><AdminUsersPage /></RequireAdmin>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
