import { useState, useEffect } from 'react'
import {
  Card, Table, Tag, Button, Space, Modal, Form, Input, Select,
  Switch, InputNumber, Popconfirm, message, Alert,
} from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined, StarOutlined, ExperimentOutlined } from '@ant-design/icons'
import { adminApi, LLMConfig } from '../../api/admin'


export default function AdminLLMPage() {
  const [configs, setConfigs] = useState<LLMConfig[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form] = Form.useForm()
  const [testResult, setTestResult] = useState<Record<string, unknown> | null>(null)
  const [testLoading, setTestLoading] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      setConfigs(await adminApi.llm.list())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const openCreate = () => {
    setEditingId(null)
    form.resetFields()
    setModalVisible(true)
  }

  const openEdit = (c: LLMConfig) => {
    setEditingId(c.id)
    form.setFieldsValue({ ...c, api_key: '' })
    setModalVisible(true)
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    try {
      if (editingId) {
        const update: Record<string, unknown> = { ...values }
        if (!update.api_key) delete update.api_key
        await adminApi.llm.update(editingId, update)
        message.success('更新成功')
      } else {
        await adminApi.llm.create(values)
        message.success('创建成功')
      }
      setModalVisible(false)
      load()
    } catch {
      message.error('操作失败')
    }
  }

  const handleDelete = async (id: string) => {
    await adminApi.llm.delete(id)
    message.success('已删除')
    load()
  }

  const handleSetDefault = async (id: string) => {
    await adminApi.llm.setDefault(id)
    message.success('已设为默认')
    load()
  }

  const handleTest = async (id: string) => {
    setTestLoading(id)
    try {
      const res = await adminApi.llm.test(id)
      setTestResult(res)
    } finally {
      setTestLoading(null)
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name' },
    { title: '提供商', dataIndex: 'provider', width: 140, render: (v: string) => <Tag>{v}</Tag> },
    { title: '模型', dataIndex: 'model_id', width: 180 },
    { title: '模式', dataIndex: 'output_mode', width: 120, render: (v: string) => <Tag color="purple">{v}</Tag> },
    { title: '默认', dataIndex: 'is_default', width: 70, render: (v: boolean) => v ? <Tag color="gold">默认</Tag> : '—' },
    { title: '激活', dataIndex: 'is_active', width: 70, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '是' : '否'}</Tag> },
    {
      title: '操作', width: 220,
      render: (_: unknown, r: LLMConfig) => (
        <Space size="small">
          <Button size="small" icon={<ExperimentOutlined />} loading={testLoading === r.id} onClick={() => handleTest(r.id)}>测试</Button>
          <Button size="small" icon={<StarOutlined />} onClick={() => handleSetDefault(r.id)} disabled={r.is_default}>设默认</Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} />
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" icon={<DeleteOutlined />} danger />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <>
      <Card title="LLM 配置" extra={<Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>添加配置</Button>}>
        {testResult && (
          <Alert
            type={(testResult.success as boolean) ? 'success' : 'error'}
            message={`测试${(testResult.success as boolean) ? '成功' : '失败'} · 延迟 ${testResult.latency_ms as number}ms`}
            description={(testResult.result as string) || (testResult.error as string)}
            closable
            onClose={() => setTestResult(null)}
            style={{ marginBottom: 16 }}
          />
        )}
        <Table dataSource={configs} rowKey="id" columns={columns} loading={loading} size="small" pagination={false} />
      </Card>

      <Modal
        title={editingId ? '编辑配置' : '新建 LLM 配置'}
        open={modalVisible}
        onOk={handleSave}
        onCancel={() => setModalVisible(false)}
        width={560}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="配置名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="provider" label="提供商" rules={[{ required: true }]}>
            <Select>
              <Select.Option value="anthropic">Anthropic</Select.Option>
              <Select.Option value="openai_compatible">OpenAI Compatible</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="base_url" label="Base URL (OpenAI Compatible 填写)" extra="常用：智谱 https://open.bigmodel.cn/api/paas/v4/  · DeepSeek https://api.deepseek.com/v1  · Ollama http://host.docker.internal:11434/v1"><Input placeholder="https://open.bigmodel.cn/api/paas/v4/" /></Form.Item>
          <Form.Item name="api_key" label={editingId ? 'API Key（留空不更新）' : 'API Key'} rules={editingId ? [] : [{ required: true }]}>
            <Input.Password placeholder={editingId ? '留空不修改' : 'sk-...'} />
          </Form.Item>
          <Form.Item name="model_id" label="模型 ID" rules={[{ required: true }]}><Input placeholder="claude-opus-4-7" /></Form.Item>
          <Form.Item name="output_mode" label="输出模式" initialValue="tool_calling">
            <Select>
              <Select.Option value="tool_calling">Tool Calling</Select.Option>
              <Select.Option value="json_mode">JSON Mode</Select.Option>
              <Select.Option value="prompt_json">Prompt JSON</Select.Option>
            </Select>
          </Form.Item>
          <Space>
            <Form.Item name="temperature" label="Temperature" initialValue={0.0}>
              <InputNumber min={0} max={1} step={0.1} style={{ width: 100 }} />
            </Form.Item>
            <Form.Item name="max_tokens" label="Max Tokens" initialValue={2048}>
              <InputNumber min={128} max={4096} step={128} style={{ width: 120 }} />
            </Form.Item>
          </Space>
          <Form.Item name="is_active" label="激活" valuePropName="checked" initialValue={true}>
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
