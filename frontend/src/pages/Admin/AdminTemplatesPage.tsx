import { useState, useEffect } from 'react'
import { Card, Table, Tag, Button, Space, Popconfirm, Select, Input, message, Modal, Form } from 'antd'
import { SearchOutlined, EditOutlined, DeleteOutlined, ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons'
import { templatesApi, TemplateListItem } from '../../api/templates'
import { useAuthStore } from '../../store/authStore'

const maturityColors: Record<string, string> = { draft: 'blue', stable: 'green', deprecated: 'gray' }

// FEAT-13：生产门控等级配色与"开发成熟度"（maturity）配色独立，避免视觉混淆。
const maturityLevelColors: Record<string, string> = {
  production: 'green',
  experimental: 'orange',
  draft: 'blue',
}

export default function AdminTemplatesPage() {
  const [templates, setTemplates] = useState<TemplateListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [codeType, setCodeType] = useState<string | undefined>()
  const [editVisible, setEditVisible] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm] = Form.useForm()
  const currentUserRole = useAuthStore((s) => s.user?.role)
  const isSuperAdmin = currentUserRole === 'super_admin'

  const load = async () => {
    setLoading(true)
    try {
      const res = await templatesApi.list({ keyword: keyword || undefined, code_type: codeType })
      setTemplates(res)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [codeType])

  const handleDelete = async (id: string) => {
    await templatesApi.delete(id)
    message.success('已停用')
    load()
  }

  const openEdit = async (id: string) => {
    const t = await templatesApi.get(id)
    editForm.setFieldsValue(t)
    setEditingId(id)
    setEditVisible(true)
  }

  const handleEditSave = async () => {
    const values = await editForm.validateFields()
    await templatesApi.update(editingId!, { ...values, change_note: '管理员编辑' })
    message.success('更新成功')
    setEditVisible(false)
    load()
  }

  const handlePromote = async (id: string) => {
    try {
      await templatesApi.update(id, { maturity_level: 'production', change_note: '升级到 production' })
      message.success('已升级到 production')
      load()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err?.response?.data?.detail || '升级失败')
    }
  }

  const handleDemote = async (id: string) => {
    try {
      await templatesApi.update(id, { maturity_level: 'experimental', change_note: '降级到 experimental' })
      message.success('已降级到 experimental')
      load()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err?.response?.data?.detail || '降级失败')
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: '类型', dataIndex: 'code_type', width: 100, render: (v: string) => <Tag>{v}</Tag> },
    { title: '子类', dataIndex: 'subcategory', width: 120, render: (v: string) => v || '—' },
    { title: '成熟度', dataIndex: 'maturity', width: 90, render: (v: string) => <Tag color={maturityColors[v]}>{v}</Tag> },
    {
      title: '生产门控',
      dataIndex: 'maturity_level',
      width: 110,
      render: (v: string) => <Tag color={maturityLevelColors[v] || 'default'}>{v}</Tag>,
    },
    { title: '激活', dataIndex: 'is_active', width: 70, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '是' : '否'}</Tag> },
    { title: '更新时间', dataIndex: 'updated_at', width: 160, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
    {
      title: '操作',
      width: isSuperAdmin ? 220 : 100,
      render: (_: unknown, r: TemplateListItem) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r.id)} />
          {isSuperAdmin && r.maturity_level !== 'production' && (
            <Popconfirm
              title="升级到 production？将进入 RAG 召回主库"
              onConfirm={() => handlePromote(r.id)}
            >
              <Button size="small" icon={<ArrowUpOutlined />} type="primary" ghost>
                升 prod
              </Button>
            </Popconfirm>
          )}
          {isSuperAdmin && r.maturity_level === 'production' && (
            <Popconfirm
              title="降级到 experimental？将退出 RAG 召回主库"
              onConfirm={() => handleDemote(r.id)}
            >
              <Button size="small" icon={<ArrowDownOutlined />} danger>
                降 exp
              </Button>
            </Popconfirm>
          )}
          <Popconfirm title="确认停用？" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" icon={<DeleteOutlined />} danger />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <>
      <Card title="模板管理" extra={
        <Space>
          <Select placeholder="代码类型" allowClear value={codeType} onChange={setCodeType} style={{ width: 140 }}>
            <Select.Option value="assertion">断言</Select.Option>
            <Select.Option value="coverage">覆盖率</Select.Option>
          </Select>
          <Input.Search
            placeholder="关键词"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onSearch={load}
            allowClear
            enterButton={<SearchOutlined />}
            style={{ width: 200 }}
          />
        </Space>
      }>
        <Table dataSource={templates} rowKey="id" columns={columns} loading={loading} size="small" pagination={{ pageSize: 20 }} />
      </Card>

      <Modal title="编辑模板" open={editVisible} onOk={handleEditSave} onCancel={() => setEditVisible(false)} width={800} destroyOnClose>
        <Form form={editForm} layout="vertical">
          <Form.Item name="description" label="描述"><Input.TextArea rows={3} /></Form.Item>
          <Form.Item name="maturity" label="成熟度">
            <Select>
              <Select.Option value="draft">draft</Select.Option>
              <Select.Option value="stable">stable</Select.Option>
              <Select.Option value="deprecated">deprecated</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="template_body" label="模板代码">
            <Input.TextArea rows={12} style={{ fontFamily: 'monospace' }} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
