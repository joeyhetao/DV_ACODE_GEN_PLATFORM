import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Form, Input, Button, Card, Typography, Alert, Space, Tabs } from 'antd'
import { UserOutlined, LockOutlined, MailOutlined } from '@ant-design/icons'
import { useAuthStore } from '../store/authStore'
import { authApi } from '../api/auth'

const { Title, Text } = Typography

export default function LoginPage() {
  const navigate = useNavigate()
  const { login, loading, token } = useAuthStore()
  const [loginForm] = Form.useForm()
  const [registerForm] = Form.useForm()
  const [error, setError] = useState('')
  const [registerLoading, setRegisterLoading] = useState(false)
  const [activeTab, setActiveTab] = useState('login')

  useEffect(() => {
    if (token) navigate('/', { replace: true })
  }, [token, navigate])

  const handleLogin = async (values: { username: string; password: string }) => {
    setError('')
    try {
      await login(values.username, values.password)
      navigate('/', { replace: true })
    } catch {
      setError('用户名或密码错误')
    }
  }

  const handleRegister = async (values: { username: string; email: string; password: string; confirm: string }) => {
    setError('')
    setRegisterLoading(true)
    try {
      await authApi.register({ username: values.username, email: values.email, password: values.password })
      registerForm.resetFields()
      setActiveTab('login')
      loginForm.setFieldsValue({ username: values.username })
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || '注册失败，用户名或邮箱已存在')
    } finally {
      setRegisterLoading(false)
    }
  }

  const handleTabChange = (key: string) => {
    setError('')
    setActiveTab(key)
  }

  const loginTab = (
    <Form form={loginForm} onFinish={handleLogin} layout="vertical" size="large">
      <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
        <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
      </Form.Item>
      <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
        <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
      </Form.Item>
      <Form.Item>
        <Button type="primary" htmlType="submit" block loading={loading}>登录</Button>
      </Form.Item>
    </Form>
  )

  const registerTab = (
    <Form form={registerForm} onFinish={handleRegister} layout="vertical" size="large">
      <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }, { min: 3, message: '至少 3 个字符' }]}>
        <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
      </Form.Item>
      <Form.Item name="email" rules={[{ required: true, message: '请输入邮箱' }, { type: 'email', message: '邮箱格式不正确' }]}>
        <Input prefix={<MailOutlined />} placeholder="邮箱" autoComplete="email" />
      </Form.Item>
      <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }, { min: 6, message: '至少 6 个字符' }]}>
        <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="new-password" />
      </Form.Item>
      <Form.Item
        name="confirm"
        dependencies={['password']}
        rules={[
          { required: true, message: '请确认密码' },
          ({ getFieldValue }) => ({
            validator(_, value) {
              if (!value || getFieldValue('password') === value) return Promise.resolve()
              return Promise.reject(new Error('两次密码不一致'))
            },
          }),
        ]}
      >
        <Input.Password prefix={<LockOutlined />} placeholder="确认密码" autoComplete="new-password" />
      </Form.Item>
      <Form.Item>
        <Button type="primary" htmlType="submit" block loading={registerLoading}>注册</Button>
      </Form.Item>
    </Form>
  )

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f0f2f5' }}>
      <Card style={{ width: 420 }}>
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div style={{ textAlign: 'center' }}>
            <Title level={3} style={{ margin: 0 }}>DV ACODE GEN</Title>
            <Text type="secondary">IC 验证辅助代码生成平台</Text>
          </div>
          {error && <Alert type="error" message={error} showIcon closable onClose={() => setError('')} />}
          <Tabs
            activeKey={activeTab}
            onChange={handleTabChange}
            centered
            items={[
              { key: 'login', label: '登录', children: loginTab },
              { key: 'register', label: '注册', children: registerTab },
            ]}
          />
        </Space>
      </Card>
    </div>
  )
}
