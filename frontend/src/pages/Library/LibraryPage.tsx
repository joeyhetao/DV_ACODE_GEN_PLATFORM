import { useState, useEffect } from 'react'
import {
  Card, Table, Input, Select, Tag, Button, Space, Modal, Descriptions,
  Typography, Drawer, Form, message, Popconfirm,
} from 'antd'
import { SearchOutlined, EyeOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import Editor from '@monaco-editor/react'
import { templatesApi, Template, TemplateListItem } from '../../api/templates'
import { useAuthStore } from '../../store/authStore'

const { Text } = Typography

const maturityColors: Record<string, string> = { draft: 'blue', stable: 'green', deprecated: 'gray' }

export default function LibraryPage() {
  const user = useAuthStore((s) => s.user)
  const isAdmin = user && ['lib_admin', 'super_admin'].includes(user.role)
  const [templates, setTemplates] = useState<TemplateListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [codeType, setCodeType] = useState<string | undefined>()
  const [detail, setDetail] = useState<Template | null>(null)
  const [detailVisible, setDetailVisible] = useState(false)
  const [editVisible, setEditVisible] = useState(false)
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

  const showDetail = async (id: string) => {
    const t = await templatesApi.get(id)
    setDetail(t)
    setDetailVisible(true)
  }

  const showEdit = async (id: string) => {
    const t = await templatesApi.get(id)
    setDetail(t)
    editForm.setFieldsValue({ ...t, template_body: t.template_body })
    setEditVisible(true)
  }

  const handleDelete = async (id: string) => {
    await templatesApi.delete(id)
    message.success('已停用')
    load()
  }

  const handleEditSave = async () => {
    const values = await editForm.validateFields()
    await templatesApi.update(detail!.id, { ...values, change_note: '手动编辑' })
    message.success('更新成功')
    setEditVisible(false)
    load()
  }

  const columns = [
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: '类型', dataIndex: 'code_type', width: 100, render: (v: string) => <Tag>{v}</Tag> },
    { title: '子类', dataIndex: 'subcategory', width: 120, render: (v: string) => v || '—' },
    { title: '成熟度', dataIndex: 'maturity', width: 90, render: (v: string) => <Tag color={maturityColors[v]}>{v}</Tag> },
    { title: '更新时间', dataIndex: 'updated_at', width: 160, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
    {
      title: '操作', width: 120, render: (_: unknown, record: TemplateListItem) => (
        <Space size="small">
          <Button size="small" icon={<EyeOutlined />} onClick={() => showDetail(record.id)} />
          {isAdmin && <Button size="small" icon={<EditOutlined />} onClick={() => showEdit(record.id)} />}
          {isAdmin && (
            <Popconfirm title="确认停用该模板？" onConfirm={() => handleDelete(record.id)}>
              <Button size="small" icon={<DeleteOutlined />} danger />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <>
      <Card title="模板库" extra={
        <Space>
          <Select placeholder="代码类型" allowClear value={codeType} onChange={setCodeType} style={{ width: 140 }}>
            <Select.Option value="assertion">断言</Select.Option>
            <Select.Option value="coverage">覆盖率</Select.Option>
          </Select>
          <Input.Search
            placeholder="搜索关键词"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onSearch={load}
            allowClear
            style={{ width: 220 }}
            enterButton={<SearchOutlined />}
          />
        </Space>
      }>
        <Table
          dataSource={templates}
          rowKey="id"
          columns={columns}
          loading={loading}
          size="small"
          pagination={{ pageSize: 15 }}
        />
      </Card>

      {/* Detail Drawer */}
      <Drawer title="模板详情" open={detailVisible} onClose={() => setDetailVisible(false)} width={720}>
        {detail && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="ID" span={2}><Text code>{detail.id}</Text></Descriptions.Item>
              <Descriptions.Item label="名称" span={2}>{detail.name}</Descriptions.Item>
              <Descriptions.Item label="代码类型">{detail.code_type}</Descriptions.Item>
              <Descriptions.Item label="子类别">{detail.subcategory || '—'}</Descriptions.Item>
              <Descriptions.Item label="成熟度"><Tag color={maturityColors[detail.maturity]}>{detail.maturity}</Tag></Descriptions.Item>
              <Descriptions.Item label="版本">{detail.version}</Descriptions.Item>
              <Descriptions.Item label="协议" span={2}>{detail.protocol?.join(', ') || '—'}</Descriptions.Item>
              <Descriptions.Item label="关键词" span={2}>{detail.keywords?.map(k => <Tag key={k}>{k}</Tag>)}</Descriptions.Item>
              <Descriptions.Item label="描述" span={2}>{detail.description}</Descriptions.Item>
            </Descriptions>
            <div>
              <Text strong>模板代码</Text>
              <div className="code-editor-wrap" style={{ marginTop: 8 }}>
                <Editor height="400px" language="systemverilog" value={detail.template_body}
                  options={{ readOnly: true, minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false }} theme="vs" />
              </div>
            </div>
          </Space>
        )}
      </Drawer>

      {/* Edit Modal */}
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
            <Input.TextArea rows={10} style={{ fontFamily: 'monospace' }} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
