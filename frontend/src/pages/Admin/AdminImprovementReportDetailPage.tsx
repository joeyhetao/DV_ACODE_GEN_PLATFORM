import { useEffect, useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Row, Col, Tag, Button, Space, Input, Typography, Spin, message, Descriptions, Divider } from 'antd'
import { ArrowLeftOutlined, CheckCircleOutlined } from '@ant-design/icons'
import Editor from '@monaco-editor/react'
import {
  improvementReportsApi,
  ImprovementReportDetail,
  ReportCategory,
  ReportStatus,
  STATUS_COLORS,
  STATUS_LABELS,
  CATEGORY_LABELS,
  GenerationRecordForReport,
} from '../../api/improvementReports'

const { Text, Title } = Typography
const { TextArea } = Input

export default function AdminImprovementReportDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [report, setReport] = useState<ImprovementReportDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [adminNote, setAdminNote] = useState('')
  const [saving, setSaving] = useState(false)
  // 防止 StrictMode dev 双重 mount 导致重复 PATCH
  const autoTransitionedRef = useRef(false)

  useEffect(() => {
    if (!id) return
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const detail = await improvementReportsApi.adminGet(id)
        if (cancelled) return
        setReport(detail)
        setAdminNote(detail.admin_note || '')

        // mount 时若 status=pending，自动 PATCH→in_review（无需 admin 主动点击）
        if (detail.status === 'pending' && !autoTransitionedRef.current) {
          autoTransitionedRef.current = true
          try {
            const updated = await improvementReportsApi.adminPatch(id, { status: 'in_review' })
            if (!cancelled) setReport(updated)
          } catch {
            // 自动跳转失败不阻塞展示——但要提示 admin，否则 "标记已处理" 会触发
            // pending→resolved 跳转被后端 422 拒绝（非法状态），admin 困惑。
            if (!cancelled) {
              message.warning('自动切换状态失败，请刷新页面后再试')
            }
          }
        }
      } catch {
        if (!cancelled) message.error('加载详情失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [id])

  const handleSaveAdminNote = async () => {
    if (!id || !report) return
    setSaving(true)
    try {
      const updated = await improvementReportsApi.adminPatch(id, { admin_note: adminNote })
      setReport(updated)
      message.success('已保存')
    } catch {
      message.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleMarkResolved = async () => {
    if (!id || !report) return
    if (report.status === 'resolved') return
    setSaving(true)
    try {
      // 先把 admin_note 一起带上
      const updated = await improvementReportsApi.adminPatch(id, {
        status: 'resolved',
        admin_note: adminNote || undefined,
      })
      setReport(updated)
      message.success('已标记为处理完成')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: { type?: string; message?: string } } } }
      const detail = err.response?.data?.detail
      if (detail?.type === 'illegal_status_transition') {
        message.error(detail.message || '非法状态跳转')
      } else {
        message.error('保存失败')
      }
    } finally {
      setSaving(false)
    }
  }

  if (loading || !report) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    )
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card size="small">
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/improvement-reports')}>
              返回列表
            </Button>
            <Title level={4} style={{ margin: 0 }}>对比报告详情</Title>
            <Tag color={STATUS_COLORS[report.status]}>{STATUS_LABELS[report.status]}</Tag>
          </Space>
          <Space>
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              onClick={handleMarkResolved}
              disabled={report.status === 'resolved'}
              loading={saving}
            >
              标记已处理
            </Button>
          </Space>
        </Space>
      </Card>

      <Row gutter={16}>
        <Col span={9}>
          <Card title={<><Tag color="cyan">RAG</Tag> 默认生成结果</>} size="small">
            <RecordColumn record={report.rag_record} />
          </Card>
        </Col>
        <Col span={9}>
          <Card title={<><Tag color="orange">LLM 直接生成</Tag> 兜底结果</>} size="small">
            <RecordColumn record={report.llm_direct_record} />
          </Card>
        </Col>
        <Col span={6}>
          <Card title="用户提交内容 / Admin 处理" size="small">
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="提交人">{report.reporter_username || report.reporter_user_id}</Descriptions.Item>
              <Descriptions.Item label="提交时间">{new Date(report.created_at).toLocaleString()}</Descriptions.Item>
              <Descriptions.Item label="分类">
                {report.report_categories && report.report_categories.length > 0 ? (
                  <Space wrap size={4}>
                    {report.report_categories.map((slug) => (
                      <Tag key={slug}>{CATEGORY_LABELS[slug as ReportCategory] || slug}</Tag>
                    ))}
                  </Space>
                ) : (
                  <Text type="secondary">未选</Text>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="用户备注">
                {report.reporter_note || <Text type="secondary">无</Text>}
              </Descriptions.Item>
            </Descriptions>
            <Divider style={{ margin: '12px 0' }} />
            <div style={{ marginBottom: 8 }}>
              <Text>Admin Note：</Text>
            </div>
            <TextArea
              rows={6}
              value={adminNote}
              onChange={(e) => setAdminNote(e.target.value)}
              placeholder="审阅备注（可单独保存，不改变状态）"
              maxLength={8192}
            />
            <Button
              style={{ marginTop: 8 }}
              size="small"
              onClick={handleSaveAdminNote}
              loading={saving}
              block
            >
              保存 Admin Note
            </Button>
          </Card>
        </Col>
      </Row>
    </Space>
  )
}

function RecordColumn({ record }: { record: GenerationRecordForReport }) {
  if (!record.id) {
    return <Text type="secondary">该记录已被删除</Text>
  }
  return (
    <Space direction="vertical" size="small" style={{ width: '100%' }}>
      <Descriptions column={1} size="small">
        <Descriptions.Item label="模板">
          {record.template_name || <Text type="secondary">-</Text>}
          {record.template_id && (
            <Text type="secondary" code style={{ marginLeft: 6 }}>
              {record.template_id}
            </Text>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="生成模式">
          {record.generation_mode || '-'}
          {record.cache_hit && <Tag color="green" style={{ marginLeft: 8 }}>缓存命中</Tag>}
        </Descriptions.Item>
        <Descriptions.Item label="原始意图">
          <Text style={{ fontSize: 12 }}>{record.original_intent || '-'}</Text>
        </Descriptions.Item>
      </Descriptions>
      {record.params_used && (
        <details>
          <summary style={{ cursor: 'pointer', fontSize: 12, color: '#666' }}>params_used JSON</summary>
          <pre style={{ background: '#f5f5f5', padding: 8, fontSize: 11, maxHeight: 160, overflow: 'auto' }}>
            {JSON.stringify(record.params_used, null, 2)}
          </pre>
        </details>
      )}
      <div>
        <Text type="secondary" style={{ fontSize: 12 }}>生成代码：</Text>
        <div className="code-editor-wrap" style={{ marginTop: 4 }}>
          <Editor
            height="320px"
            language="systemverilog"
            value={record.output_code || ''}
            options={{ readOnly: true, minimap: { enabled: false }, fontSize: 12, scrollBeyondLastLine: false }}
            theme="vs"
          />
        </div>
      </div>
    </Space>
  )
}
