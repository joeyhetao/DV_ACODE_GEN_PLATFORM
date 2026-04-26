import { useState, useEffect } from 'react'
import { Card, Table, Tag, Button, Space, Select, Popconfirm, message, Typography } from 'antd'
import { adminApi } from '../../api/admin'

interface User { id: string; username: string; email: string; role: string; is_active: boolean; created_at: string }

const roleColors: Record<string, string> = { user: 'blue', lib_admin: 'purple', super_admin: 'red' }
const roleLabels: Record<string, string> = { user: '普通用户', lib_admin: '库管理员', super_admin: '超级管理员' }

export default function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const res = await adminApi.users.list()
      setUsers(res)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleRoleChange = async (user_id: string, role: string) => {
    await adminApi.users.setRole(user_id, role)
    message.success('角色已更新')
    load()
  }

  const handleToggleActive = async (user_id: string, active: boolean) => {
    await adminApi.users.setActive(user_id, !active)
    message.success(active ? '已禁用' : '已启用')
    load()
  }

  const columns = [
    { title: '用户名', dataIndex: 'username' },
    { title: '邮箱', dataIndex: 'email', ellipsis: true },
    {
      title: '角色', dataIndex: 'role', width: 160,
      render: (v: string, r: User) => (
        <Select size="small" value={v} style={{ width: 130 }}
          onChange={(role) => handleRoleChange(r.id, role)}>
          {Object.entries(roleLabels).map(([val, label]) => (
            <Select.Option key={val} value={val}><Tag color={roleColors[val]}>{label}</Tag></Select.Option>
          ))}
        </Select>
      ),
    },
    {
      title: '状态', dataIndex: 'is_active', width: 90,
      render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '正常' : '禁用'}</Tag>,
    },
    { title: '注册时间', dataIndex: 'created_at', width: 160, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
    {
      title: '操作', width: 100,
      render: (_: unknown, r: User) => (
        <Popconfirm title={r.is_active ? '确认禁用该用户？' : '确认启用该用户？'} onConfirm={() => handleToggleActive(r.id, r.is_active)}>
          <Button size="small" danger={r.is_active}>{r.is_active ? '禁用' : '启用'}</Button>
        </Popconfirm>
      ),
    },
  ]

  return (
    <Card title="用户管理">
      <Table dataSource={users} rowKey="id" columns={columns} loading={loading} size="small" pagination={{ pageSize: 20 }} />
    </Card>
  )
}
