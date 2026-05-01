import { useState, useEffect } from 'react'
import { Card, Table, Tag, Button, Space, Popconfirm, Select, Input, message, Modal, Form } from 'antd'
import { SearchOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { templatesApi, TemplateListItem } from '../../api/templates'

const maturityColors: Record<string, string> = { draft: 'blue', stable: 'green', deprecated: 'gray' }

export default function AdminTemplatesPage() {
  const [templates, setTemplates] = useState<TemplateListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [codeType, setCodeType] = useState<string | undefined>()
  const [editVisible, setEditVisible] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm] = Form.useForm()

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

  const columns = [
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: '类型', dataIndex: 'code_type', width: 100, render: (v: string) => <Tag>{v}</Tag> },
    { title: '子类', dataIndex: 'subcategory', width: 120, render: (v: string) => v || '—' },
    { title: '成熟度', dataIndex: 'maturity', width: 90, render: (v: string) => <Tag color={maturityColors[v]}>{v}</Tag> },
    { title: '激活', dataIndex: 'is_active', width: 70, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '是' : '否'}</Tag> },
    { title: '更新时间', dataIndex: 'updated_at', width: 160, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
    {
      title: '操作', width: 100,
      render: (_: unknown, r: TemplateListItem) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r.id)} />
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
