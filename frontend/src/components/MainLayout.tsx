import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Avatar, Dropdown, Space, Typography } from 'antd'
import {
  CodeOutlined, UploadOutlined, BookOutlined, BulbOutlined,
  ContainerOutlined, SettingOutlined, UserOutlined, LogoutOutlined,
  ThunderboltOutlined, TeamOutlined, RobotOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '../store/authStore'

const { Header, Sider, Content } = Layout
const { Text } = Typography

const menuItems = [
  { key: '/generate', icon: <ThunderboltOutlined />, label: '代码生成' },
  { key: '/batch', icon: <UploadOutlined />, label: '批量处理' },
  { key: '/library', icon: <BookOutlined />, label: '模板库' },
  { key: '/intent-builder', icon: <BulbOutlined />, label: '意图构建器' },
  { key: '/my-contributions', icon: <ContainerOutlined />, label: '我的贡献' },
  {
    key: 'admin',
    icon: <SettingOutlined />,
    label: '管理',
    children: [
      { key: '/admin/templates', icon: <CodeOutlined />, label: '模板管理' },
      { key: '/admin/contributions', icon: <ContainerOutlined />, label: '贡献审核' },
      { key: '/admin/llm', icon: <RobotOutlined />, label: 'LLM 配置' },
      { key: '/admin/users', icon: <TeamOutlined />, label: '用户管理' },
    ],
  },
]

export default function MainLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuthStore()
  const [collapsed, setCollapsed] = useState(false)

  const isAdmin = user && ['lib_admin', 'super_admin'].includes(user.role)

  const visibleItems = isAdmin ? menuItems : menuItems.filter((i) => i.key !== 'admin')

  const userMenu = [
    { key: 'info', label: <Text type="secondary">{user?.email}</Text>, disabled: true },
    { type: 'divider' as const },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', danger: true },
  ]

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} theme="dark">
        <div style={{ height: 56, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 700, fontSize: collapsed ? 14 : 16, whiteSpace: 'nowrap', overflow: 'hidden', padding: '0 8px' }}>
          {collapsed ? 'DV' : 'DV ACODE'}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          defaultOpenKeys={['admin']}
          items={visibleItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'flex-end', boxShadow: '0 1px 4px rgba(0,21,41,.08)' }}>
          <Dropdown menu={{ items: userMenu, onClick: ({ key }) => key === 'logout' && logout() }}>
            <Space style={{ cursor: 'pointer' }}>
              <Avatar size="small" icon={<UserOutlined />} />
              <Text>{user?.username}</Text>
            </Space>
          </Dropdown>
        </Header>
        <Content style={{ margin: 24, minHeight: 280 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
