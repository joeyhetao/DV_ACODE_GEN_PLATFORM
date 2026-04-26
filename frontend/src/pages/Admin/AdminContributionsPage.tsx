import { useState, useEffect } from 'react'
import {
  Card, Table, Tag, Button, Space, Select, Drawer, Descriptions,
  Typography, Modal, Input, message,
} from 'antd'
import { EyeOutlined, CheckOutlined, CloseOutlined, EditOutlined } from '@ant-design/icons'
import { contributionsApi, ContributionListItem, Contribution } from '../../api/contributions'

const { Text } = Typography
const { TextArea } = Input

const statusColors: Record<string, string> = {
  pending: 'blue', approved: 'green', rejected: 'red',
  needs_revision: 'orange', withdrawn: 'gray',
}
const statusLabels: Record<string, string> = {
  pending: '待审核', approved: '已批准', rejected: '已拒绝',
  needs_revision: '需修改', withdrawn: '已撤回',
}

export default function AdminContributionsPage() {
  const [list, setList] = useState<ContributionListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState<string | undefined>('pending')
  const [detail, setDetail] = useState<Contribution | null>(null)
  const [detailVisible, setDetailVisible] = useState(false)
  const [rejectVisible, setRejectVisible] = useState(false)
  const [revisionVisible, setRevisionVisible] = useState(false)
  const [comment, setComment] = useState('')
  const [actionId, setActionId] = useState('')
  const [actionLoading, setActionLoading] = useState(false)

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
    setDetailVisible(true)
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
          {r.status === 'pending' && (
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
          <Select.Option value="pending">待审核</Select.Option>
          <Select.Option value="approved">已批准</Select.Option>
          <Select.Option value="rejected">已拒绝</Select.Option>
          <Select.Option value="needs_revision">需修改</Select.Option>
        </Select>
      }>
        <Table dataSource={list} rowKey="id" columns={columns} loading={loading} size="small" pagination={{ pageSize: 15 }} />
      </Card>

      <Drawer title="贡献详情" open={detailVisible} onClose={() => setDetailVisible(false)} width={680}>
        {detail && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="状态"><Tag color={statusColors[detail.status]}>{statusLabels[detail.status]}</Tag></Descriptions.Item>
              <Descriptions.Item label="模板名称">{detail.template_name}</Descriptions.Item>
              <Descriptions.Item label="描述">{detail.description}</Descriptions.Item>
              <Descriptions.Item label="原始意图">{detail.original_intent}</Descriptions.Item>
              <Descriptions.Item label="关键词">{detail.keywords?.join(', ') || '—'}</Descriptions.Item>
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

      <Modal title="请求修改" open={revisionVisible} onOk={handleRevision} onCancel={() => setRevisionVisible(false)} confirmLoading={actionLoading}>
        <TextArea rows={4} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="请说明需要修改的内容" />
      </Modal>

      <Modal title="拒绝贡献" open={rejectVisible} onOk={handleReject} onCancel={() => setRejectVisible(false)} confirmLoading={actionLoading} okButtonProps={{ danger: true }}>
        <TextArea rows={4} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="请说明拒绝原因" />
      </Modal>
    </>
  )
}
