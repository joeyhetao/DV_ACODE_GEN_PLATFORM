import { useState, useEffect } from 'react'
import {
  Card, Table, Tag, Button, Space, Modal, Form, Input, Select,
  Drawer, Descriptions, Typography, message,
} from 'antd'
import { PlusOutlined, EyeOutlined } from '@ant-design/icons'
import { contributionsApi, ContributionListItem, Contribution } from '../../api/contributions'
import { generateApi } from '../../api/generate'

const { TextArea } = Input
const { Text } = Typography

const statusColors: Record<string, string> = {
  pending: 'blue', approved: 'green', rejected: 'red',
  needs_revision: 'orange', withdrawn: 'gray',
}
const statusLabels: Record<string, string> = {
  pending: '待审核', approved: '已批准', rejected: '已拒绝',
  needs_revision: '需修改', withdrawn: '已撤回',
}

export default function MyContributionsPage() {
  const [list, setList] = useState<ContributionListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [submitVisible, setSubmitVisible] = useState(false)
  const [detailVisible, setDetailVisible] = useState(false)
  const [detail, setDetail] = useState<Contribution | null>(null)
  const [submitForm] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const [codeTypes, setCodeTypes] = useState<{ id: string; display_name: string }[]>([])

  const load = async () => {
    setLoading(true)
    try {
      const res = await contributionsApi.my()
      setList(res)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    generateApi.codeTypes().then(setCodeTypes).catch(() => {})
  }, [])

  const showDetail = async (id: string) => {
    const c = await contributionsApi.get(id)
    setDetail(c)
    setDetailVisible(true)
  }

  const handleSubmit = async () => {
    const values = await submitForm.validateFields()
    setSubmitting(true)
    try {
      await contributionsApi.submit({ ...values, keywords: values.keywords?.split(',').map((k: string) => k.trim()).filter(Boolean) })
      message.success('提交成功，等待管理员审核')
      setSubmitVisible(false)
      submitForm.resetFields()
      load()
    } catch {
      message.error('提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  const columns = [
    { title: '模板名称', dataIndex: 'template_name', ellipsis: true },
    { title: '代码类型', dataIndex: 'code_type', width: 100, render: (v: string) => <Tag>{v}</Tag> },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v: string) => <Tag color={statusColors[v]}>{statusLabels[v] || v}</Tag>,
    },
    { title: '提交时间', dataIndex: 'created_at', width: 160, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
    {
      title: '操作', width: 80, render: (_: unknown, r: ContributionListItem) => (
        <Button size="small" icon={<EyeOutlined />} onClick={() => showDetail(r.id)}>详情</Button>
      ),
    },
  ]

  return (
    <>
      <Card
        title="我的贡献"
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setSubmitVisible(true)}>提交贡献</Button>}
      >
        <Table dataSource={list} rowKey="id" columns={columns} loading={loading} size="small" pagination={{ pageSize: 15 }} />
      </Card>

      {/* Submit Modal */}
      <Modal
        title="提交模板贡献"
        open={submitVisible}
        onOk={handleSubmit}
        onCancel={() => setSubmitVisible(false)}
        width={720}
        confirmLoading={submitting}
        destroyOnClose
      >
        <Form form={submitForm} layout="vertical">
          <Form.Item name="template_name" label="模板名称" rules={[{ required: true }]}>
            <Input placeholder="简洁、唯一的模板名称" />
          </Form.Item>
          <Form.Item name="code_type" label="代码类型" rules={[{ required: true }]}>
            <Select>
              {codeTypes.map((ct) => (
                <Select.Option key={ct.id} value={ct.id}>{ct.display_name}</Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="original_intent" label="原始意图描述" rules={[{ required: true }]}>
            <TextArea rows={2} placeholder="描述该模板所解决的验证场景" />
          </Form.Item>
          <Form.Item name="description" label="详细描述" rules={[{ required: true }]}>
            <TextArea rows={3} />
          </Form.Item>
          <Form.Item name="demo_code" label="模板代码 (Jinja2)" rules={[{ required: true }]}>
            <TextArea rows={10} style={{ fontFamily: 'monospace' }} placeholder="支持 Jinja2 语法，变量用 {{ var_name }} 表示" />
          </Form.Item>
          <Form.Item name="keywords" label="关键词（逗号分隔）">
            <Input placeholder="如: valid, ready, 握手" />
          </Form.Item>
          <Form.Item name="protocol" label="协议">
            <Select allowClear>
              <Select.Option value="AXI4">AXI4</Select.Option>
              <Select.Option value="AXI4-Lite">AXI4-Lite</Select.Option>
              <Select.Option value="AXI4-Stream">AXI4-Stream</Select.Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail Drawer */}
      <Drawer title="贡献详情" open={detailVisible} onClose={() => setDetailVisible(false)} width={680}>
        {detail && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="状态">
                <Tag color={statusColors[detail.status]}>{statusLabels[detail.status]}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="模板名称">{detail.template_name}</Descriptions.Item>
              <Descriptions.Item label="代码类型">{detail.code_type}</Descriptions.Item>
              <Descriptions.Item label="描述">{detail.description}</Descriptions.Item>
              {detail.reviewer_comment && (
                <Descriptions.Item label="审核意见">
                  <Text type="warning">{detail.reviewer_comment}</Text>
                </Descriptions.Item>
              )}
              {detail.promoted_template_id && (
                <Descriptions.Item label="发布模板ID">
                  <Text code>{detail.promoted_template_id}</Text>
                </Descriptions.Item>
              )}
            </Descriptions>
            <div>
              <Text strong>模板代码</Text>
              <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 6, marginTop: 8, overflow: 'auto', fontSize: 13 }}>
                {detail.demo_code}
              </pre>
            </div>
          </Space>
        )}
      </Drawer>
    </>
  )
}
