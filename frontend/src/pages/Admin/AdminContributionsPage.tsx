import { useState, useEffect } from 'react'
import {
  Card, Table, Tag, Button, Space, Select, Drawer, Descriptions, Row, Col,
  Typography, Modal, Input, message, Tooltip,
} from 'antd'
import { EyeOutlined, CheckOutlined, CloseOutlined, EditOutlined, SaveOutlined } from '@ant-design/icons'
import { contributionsApi, ContributionListItem, Contribution } from '../../api/contributions'

const { Text } = Typography
const { TextArea } = Input

// v3.0 ↔ DB Enum 对齐：(pending_review, under_review, needs_revision, approved, rejected)
const statusColors: Record<string, string> = {
  pending_review: 'blue', under_review: 'cyan', approved: 'green', rejected: 'red',
  needs_revision: 'orange',
}
const statusLabels: Record<string, string> = {
  pending_review: '待审核', under_review: '审核中', approved: '已批准', rejected: '已拒绝',
  needs_revision: '需修改',
}

export default function AdminContributionsPage() {
  const [list, setList] = useState<ContributionListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState<string | undefined>('pending_review')
  const [detail, setDetail] = useState<Contribution | null>(null)
  const [detailVisible, setDetailVisible] = useState(false)
  const [rejectVisible, setRejectVisible] = useState(false)
  const [revisionVisible, setRevisionVisible] = useState(false)
  const [comment, setComment] = useState('')
  const [actionId, setActionId] = useState('')
  const [actionLoading, setActionLoading] = useState(false)
  // v3.0 三栏审核：可编辑的中/右栏字段（左栏=用户原始提交是只读）
  const [editedDemoCode, setEditedDemoCode] = useState('')
  const [editedParameterDefs, setEditedParameterDefs] = useState('')
  const [editedKeywords, setEditedKeywords] = useState('')
  const [editedSubcategory, setEditedSubcategory] = useState('')
  const [editedProtocol, setEditedProtocol] = useState('')
  const [savingEdit, setSavingEdit] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const res = await contributionsApi.adminList({ status })
      setList(res)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [status])

  const showDetail = async (id: string) => {
    const c = await contributionsApi.get(id)
    setDetail(c)
    setEditedDemoCode(c.demo_code || '')
    setEditedParameterDefs(c.parameter_defs ? JSON.stringify(c.parameter_defs, null, 2) : '[]')
    setEditedKeywords((c.keywords || []).join(', '))
    setEditedSubcategory(c.subcategory || '')
    setEditedProtocol(c.protocol || '')
    setDetailVisible(true)
  }

  const saveEdits = async () => {
    if (!detail) return
    // parameter_defs 是 JSON 字符串——保存前 parse 一下，失败给提示
    let parsedParamDefs: unknown
    try {
      parsedParamDefs = JSON.parse(editedParameterDefs)
    } catch {
      message.error('parameter_defs JSON 格式错误，请检查')
      return
    }
    setSavingEdit(true)
    try {
      const updated = await contributionsApi.update(detail.id, {
        demo_code: editedDemoCode,
        parameter_defs: parsedParamDefs,
        keywords: editedKeywords.split(',').map(k => k.trim()).filter(Boolean),
        subcategory: editedSubcategory || null,
        protocol: editedProtocol || null,
      })
      message.success('已保存编辑')
      setDetail(updated)
      load()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err.response?.data?.detail || '保存失败')
    } finally {
      setSavingEdit(false)
    }
  }

  const handleApprove = async (id: string) => {
    setActionLoading(true)
    try {
      await contributionsApi.approve(id)
      message.success('已批准，模板已发布')
      load()
    } finally {
      setActionLoading(false)
    }
  }

  const handleReject = async () => {
    setActionLoading(true)
    try {
      await contributionsApi.reject(actionId, comment)
      message.success('已拒绝')
      setRejectVisible(false)
      setComment('')
      load()
    } finally {
      setActionLoading(false)
    }
  }

  const handleRevision = async () => {
    setActionLoading(true)
    try {
      await contributionsApi.requestRevision(actionId, comment)
      message.success('已请求修改')
      setRevisionVisible(false)
      setComment('')
      load()
    } finally {
      setActionLoading(false)
    }
  }

  const columns = [
    { title: '模板名称', dataIndex: 'template_name', ellipsis: true },
    { title: '代码类型', dataIndex: 'code_type', width: 100, render: (v: string) => <Tag>{v}</Tag> },
    { title: '贡献者', dataIndex: 'contributor_id', width: 200, ellipsis: true },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v: string) => <Tag color={statusColors[v]}>{statusLabels[v] || v}</Tag>,
    },
    { title: '提交时间', dataIndex: 'created_at', width: 160, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
    {
      title: '操作', width: 200,
      render: (_: unknown, r: ContributionListItem) => (
        <Space size="small">
          <Button size="small" icon={<EyeOutlined />} onClick={() => showDetail(r.id)}>详情</Button>
          {r.status === 'pending_review' && (
            <>
              <Button size="small" icon={<CheckOutlined />} type="primary"
                onClick={() => handleApprove(r.id)} loading={actionLoading}>批准</Button>
              <Button size="small" icon={<EditOutlined />}
                onClick={() => { setActionId(r.id); setRevisionVisible(true) }}>修改</Button>
              <Button size="small" icon={<CloseOutlined />} danger
                onClick={() => { setActionId(r.id); setRejectVisible(true) }}>拒绝</Button>
            </>
          )}
        </Space>
      ),
    },
  ]

  return (
    <>
      <Card title="贡献审核" extra={
        <Select value={status} onChange={setStatus} style={{ width: 140 }} allowClear placeholder="全部状态">
          <Select.Option value="pending_review">待审核</Select.Option>
          <Select.Option value="under_review">审核中</Select.Option>
          <Select.Option value="approved">已批准</Select.Option>
          <Select.Option value="rejected">已拒绝</Select.Option>
          <Select.Option value="needs_revision">需修改</Select.Option>
        </Select>
      }>
        <Table dataSource={list} rowKey="id" columns={columns} loading={loading} size="small" pagination={{ pageSize: 15 }} />
      </Card>

      {/* v3.0 三栏对比布局：左只读用户提交 / 中可编辑 Jinja2 模板 / 右可编辑元数据 */}
      <Drawer
        title={
          <Space>
            贡献审核
            {detail && <Tag color={statusColors[detail.status]}>{statusLabels[detail.status]}</Tag>}
            {detail && <Text type="secondary" style={{ fontSize: 13 }}>{detail.template_name}</Text>}
          </Space>
        }
        open={detailVisible}
        onClose={() => setDetailVisible(false)}
        width="90%"
        extra={
          detail && (detail.status === 'pending_review' || detail.status === 'needs_revision') ? (
            <Space>
              <Button icon={<SaveOutlined />} onClick={saveEdits} loading={savingEdit}>
                保存编辑
              </Button>
              <Button icon={<CheckOutlined />} type="primary"
                onClick={() => handleApprove(detail.id)} loading={actionLoading}>
                批准并入库
              </Button>
              <Button icon={<EditOutlined />}
                onClick={() => { setActionId(detail.id); setRevisionVisible(true) }}>
                请求修改
              </Button>
              <Button icon={<CloseOutlined />} danger
                onClick={() => { setActionId(detail.id); setRejectVisible(true) }}>
                退回
              </Button>
            </Space>
          ) : null
        }
      >
        {detail && (
          <Row gutter={16}>
            {/* 左栏：用户提交（只读） */}
            <Col span={8}>
              <Card type="inner" size="small" title="① 用户提交（只读）" style={{ height: '100%' }}>
                <Descriptions size="small" column={1} bordered>
                  <Descriptions.Item label="模板名称">{detail.template_name}</Descriptions.Item>
                  <Descriptions.Item label="代码类型"><Tag>{detail.code_type}</Tag></Descriptions.Item>
                  <Descriptions.Item label="场景描述">{detail.description}</Descriptions.Item>
                  <Descriptions.Item label="原始意图">{detail.original_intent || '（未提供）'}</Descriptions.Item>
                </Descriptions>
                <Text strong style={{ display: 'block', marginTop: 12 }}>用户原始代码示例</Text>
                <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 6, marginTop: 4, overflow: 'auto', fontSize: 12, maxHeight: 360 }}>
                  {(detail.original_row_json as { user_demo?: string } | null)?.user_demo
                    || '（用户直接提交，未保留原始 demo）'}
                </pre>
              </Card>
            </Col>

            {/* 中栏：LLM 反推的 Jinja2 模板（可编辑） */}
            <Col span={8}>
              <Card
                type="inner"
                size="small"
                title={
                  <Tooltip title="LLM 把用户代码里的真实信号名换成 {{ placeholder }} 后的版本，审核员可手改">
                    ② LLM 反推模板（可编辑）
                  </Tooltip>
                }
                style={{ height: '100%' }}
              >
                <TextArea
                  value={editedDemoCode}
                  onChange={(e) => setEditedDemoCode(e.target.value)}
                  rows={20}
                  style={{ fontFamily: 'monospace', fontSize: 12 }}
                />
              </Card>
            </Col>

            {/* 右栏：LLM 反推的 parameters JSON + 元数据（可编辑） */}
            <Col span={8}>
              <Card
                type="inner"
                size="small"
                title={
                  <Tooltip title="LLM 自动识别的参数列表与分类元数据，审核员可手改">
                    ③ LLM 反推元数据（可编辑）
                  </Tooltip>
                }
                style={{ height: '100%' }}
              >
                <div style={{ marginBottom: 12 }}>
                  <Text strong>parameters JSON</Text>
                  <TextArea
                    value={editedParameterDefs}
                    onChange={(e) => setEditedParameterDefs(e.target.value)}
                    rows={12}
                    style={{ fontFamily: 'monospace', fontSize: 12, marginTop: 4 }}
                  />
                </div>
                <div style={{ marginBottom: 12 }}>
                  <Text strong>关键词（逗号分隔）</Text>
                  <Input
                    value={editedKeywords}
                    onChange={(e) => setEditedKeywords(e.target.value)}
                    style={{ marginTop: 4 }}
                  />
                </div>
                <div style={{ marginBottom: 12 }}>
                  <Text strong>subcategory</Text>
                  <Input
                    value={editedSubcategory}
                    onChange={(e) => setEditedSubcategory(e.target.value)}
                    style={{ marginTop: 4 }}
                  />
                </div>
                <div>
                  <Text strong>协议</Text>
                  <Select
                    value={editedProtocol || undefined}
                    onChange={setEditedProtocol}
                    style={{ width: '100%', marginTop: 4 }}
                    allowClear
                  >
                    <Select.Option value="AXI4">AXI4</Select.Option>
                    <Select.Option value="AXI4-Lite">AXI4-Lite</Select.Option>
                    <Select.Option value="AXI4-Stream">AXI4-Stream</Select.Option>
                    <Select.Option value="AHB">AHB</Select.Option>
                    <Select.Option value="APB">APB</Select.Option>
                  </Select>
                </div>
              </Card>
            </Col>
          </Row>
        )}
      </Drawer>

      <Modal title="请求修改" open={revisionVisible} onOk={handleRevision} onCancel={() => setRevisionVisible(false)} confirmLoading={actionLoading}>
        <TextArea rows={4} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="请说明需要修改的内容" />
      </Modal>

      <Modal title="拒绝贡献" open={rejectVisible} onOk={handleReject} onCancel={() => setRejectVisible(false)} confirmLoading={actionLoading} okButtonProps={{ danger: true }}>
        <TextArea rows={4} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="请说明拒绝原因" />
      </Modal>
    </>
  )
}
