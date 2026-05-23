import { useState, useEffect, useRef } from 'react'
import {
  Card, Table, Tag, Button, Space, Select, Drawer, Descriptions, Row, Col,
  Typography, Modal, Input, message, Tooltip, Alert, Collapse, Spin, List,
} from 'antd'
import {
  EyeOutlined, CheckOutlined, CloseOutlined, EditOutlined, SaveOutlined,
  WarningOutlined, CheckCircleOutlined,
} from '@ant-design/icons'
import {
  contributionsApi, ContributionListItem, Contribution, PreApproveAnalysisResult,
} from '../../api/contributions'

const { Text } = Typography
const { TextArea } = Input

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
  // v3.0 三栏审核可编辑字段
  const [editedDemoCode, setEditedDemoCode] = useState('')
  const [editedDescription, setEditedDescription] = useState('')
  const [editedParameterDefs, setEditedParameterDefs] = useState('')
  const [editedKeywords, setEditedKeywords] = useState('')
  const [editedSubcategory, setEditedSubcategory] = useState('')
  const [editedProtocol, setEditedProtocol] = useState('')
  const [savingEdit, setSavingEdit] = useState(false)
  // FEAT-4: two-step approve analysis
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [analysisResult, setAnalysisResult] = useState<PreApproveAnalysisResult | null>(null)
  const [autoApproveCountdown, setAutoApproveCountdown] = useState<number | null>(null)
  const countdownTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const load = async () => {
    setLoading(true)
    try { setList(await contributionsApi.adminList({ status })) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [status])

  // Auto-approve countdown: fires when analysis has no conflicts
  useEffect(() => {
    if (analysisResult && !analysisResult.has_conflicts && autoApproveCountdown !== null) {
      if (autoApproveCountdown <= 0) {
        // Countdown finished — auto approve
        doApprove(detail!.id, analysisResult.analysis_id)
        setAutoApproveCountdown(null)
        return
      }
      countdownTimer.current = setTimeout(() => {
        setAutoApproveCountdown(prev => (prev !== null ? prev - 1 : null))
      }, 1000)
    }
    return () => { if (countdownTimer.current) clearTimeout(countdownTimer.current) }
  }, [autoApproveCountdown, analysisResult])

  const showDetail = async (id: string) => {
    const c = await contributionsApi.get(id)
    setDetail(c)
    setEditedDemoCode(c.demo_code || '')
    setEditedDescription(c.description || '')
    setEditedParameterDefs(c.parameter_defs ? JSON.stringify(c.parameter_defs, null, 2) : '[]')
    setEditedKeywords((c.keywords || []).join(', '))
    setEditedSubcategory(c.subcategory || '')
    setEditedProtocol(c.protocol || '')
    setAnalysisResult(null)
    setAutoApproveCountdown(null)
    setDetailVisible(true)
  }

  const saveEdits = async (overrideDescription?: string, overrideKeywords?: string) => {
    if (!detail) return
    let parsedParamDefs: unknown
    try { parsedParamDefs = JSON.parse(editedParameterDefs) } catch {
      message.error('parameter_defs JSON 格式错误，请检查'); return
    }
    setSavingEdit(true)
    try {
      const updated = await contributionsApi.update(detail.id, {
        demo_code: editedDemoCode,
        description: overrideDescription ?? editedDescription,
        parameter_defs: parsedParamDefs,
        keywords: (overrideKeywords ?? editedKeywords).split(',').map(k => k.trim()).filter(Boolean),
        subcategory: editedSubcategory || null,
        protocol: editedProtocol || null,
      })
      message.success('已保存编辑')
      setDetail(updated)
      setEditedDescription(updated.description || '')
      setEditedKeywords((updated.keywords || []).join(', '))
      load()
      return updated
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err.response?.data?.detail || '保存失败')
    } finally {
      setSavingEdit(false)
    }
  }

  const doApprove = async (id: string, analysisId?: string) => {
    setActionLoading(true)
    try {
      await contributionsApi.approve(id, analysisId)
      message.success('已批准，模板已发布')
      setDetailVisible(false)
      setAnalysisResult(null)
      setAutoApproveCountdown(null)
      load()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err.response?.data?.detail || '批准失败')
    } finally {
      setActionLoading(false)
    }
  }

  // FEAT-4: two-step approve — run pre-approve-analysis first
  const handleApprove = async (id: string) => {
    setAnalysisLoading(true)
    setAnalysisResult(null)
    try {
      const result = await contributionsApi.analyzeConflicts(id)
      setAnalysisResult(result)
      if (!result.has_conflicts) {
        setAutoApproveCountdown(1)  // 1-second auto-confirm
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err.response?.data?.detail || '分析失败，请重试')
    } finally {
      setAnalysisLoading(false)
    }
  }

  const handleApplyRecommendation = async () => {
    if (!detail || !analysisResult) return
    const field = analysisResult.recommendation_field
    const text = analysisResult.recommendation_text || ''
    if (field === 'keywords') {
      const currentKw = editedKeywords ? editedKeywords + ', ' + text : text
      setEditedKeywords(currentKw)
      await saveEdits(undefined, currentKw)
    } else {
      const currentDesc = editedDescription ? editedDescription + '\n' + text : text
      setEditedDescription(currentDesc)
      await saveEdits(currentDesc, undefined)
    }
    // Re-run analysis
    await handleApprove(detail.id)
  }

  const handleCancelAutoApprove = () => {
    if (countdownTimer.current) clearTimeout(countdownTimer.current)
    setAutoApproveCountdown(null)
  }

  const handleReject = async () => {
    setActionLoading(true)
    try {
      await contributionsApi.reject(actionId, comment)
      message.success('已拒绝')
      setRejectVisible(false)
      setComment('')
      load()
    } finally { setActionLoading(false) }
  }

  const handleRevision = async () => {
    setActionLoading(true)
    try {
      await contributionsApi.requestRevision(actionId, comment)
      message.success('已请求修改')
      setRevisionVisible(false)
      setComment('')
      load()
    } finally { setActionLoading(false) }
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
                onClick={() => handleApprove(r.id)} loading={analysisLoading || actionLoading}>批准</Button>
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

  const isEditable = detail && (detail.status === 'pending_review' || detail.status === 'needs_revision')

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

      {/* v3.0 三栏对比布局 */}
      <Drawer
        title={
          <Space>
            贡献审核
            {detail && <Tag color={statusColors[detail.status]}>{statusLabels[detail.status]}</Tag>}
            {detail && <Text type="secondary" style={{ fontSize: 13 }}>{detail.template_name}</Text>}
          </Space>
        }
        open={detailVisible}
        onClose={() => { setDetailVisible(false); setAnalysisResult(null); setAutoApproveCountdown(null) }}
        width="90%"
        extra={
          isEditable ? (
            <Space>
              <Button icon={<SaveOutlined />} onClick={() => saveEdits()} loading={savingEdit}>
                保存编辑
              </Button>
              <Button icon={<CheckOutlined />} type="primary"
                onClick={() => handleApprove(detail!.id)} loading={analysisLoading || actionLoading}>
                批准并入库
              </Button>
              <Button icon={<EditOutlined />}
                onClick={() => { setActionId(detail!.id); setRevisionVisible(true) }}>
                请求修改
              </Button>
              <Button icon={<CloseOutlined />} danger
                onClick={() => { setActionId(detail!.id); setRejectVisible(true) }}>
                退回
              </Button>
            </Space>
          ) : null
        }
      >
        {detail && (
          <>
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
                    {(detail.original_row_json as { user_demo?: string } | null)?.user_demo || '（用户直接提交，未保留原始 demo）'}
                  </pre>
                </Card>
              </Col>

              {/* 中栏：LLM 反推的 Jinja2 模板（可编辑） */}
              <Col span={8}>
                <Card type="inner" size="small"
                  title={<Tooltip title="LLM 把用户代码里的真实信号名换成 {{ placeholder }} 后的版本，审核员可手改">② LLM 反推模板（可编辑）</Tooltip>}
                  style={{ height: '100%' }}>
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
                <Card type="inner" size="small"
                  title={<Tooltip title="LLM 自动识别的参数列表与分类元数据，审核员可手改">③ LLM 反推元数据（可编辑）</Tooltip>}
                  style={{ height: '100%' }}>
                  <div style={{ marginBottom: 12 }}>
                    <Text strong>场景描述</Text>
                    <TextArea
                      value={editedDescription}
                      onChange={(e) => setEditedDescription(e.target.value)}
                      rows={4}
                      style={{ marginTop: 4 }}
                    />
                  </div>
                  <div style={{ marginBottom: 12 }}>
                    <Text strong>parameters JSON</Text>
                    <TextArea
                      value={editedParameterDefs}
                      onChange={(e) => setEditedParameterDefs(e.target.value)}
                      rows={10}
                      style={{ fontFamily: 'monospace', fontSize: 12, marginTop: 4 }}
                    />
                  </div>
                  <div style={{ marginBottom: 12 }}>
                    <Text strong>关键词（逗号分隔）</Text>
                    <Input value={editedKeywords} onChange={(e) => setEditedKeywords(e.target.value)} style={{ marginTop: 4 }} />
                  </div>
                  <div style={{ marginBottom: 12 }}>
                    <Text strong>subcategory</Text>
                    <Input value={editedSubcategory} onChange={(e) => setEditedSubcategory(e.target.value)} style={{ marginTop: 4 }} />
                  </div>
                  <div>
                    <Text strong>协议</Text>
                    <Select value={editedProtocol || undefined} onChange={setEditedProtocol} style={{ width: '100%', marginTop: 4 }} allowClear>
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

            {/* FEAT-4: Analysis Panel — shown after clicking 批准并入库 */}
            {(analysisLoading || analysisResult) && (
              <div style={{ marginTop: 16 }}>
                <Collapse
                  defaultActiveKey={['analysis']}
                  items={[{
                    key: 'analysis',
                    label: analysisLoading
                      ? <Space><Spin size="small" /> 正在分析模板选择冲突…</Space>
                      : analysisResult?.has_conflicts
                        ? <Space><WarningOutlined style={{ color: '#faad14' }} /> 发现 {analysisResult.conflicts.length} 条潜在冲突</Space>
                        : <Space><CheckCircleOutlined style={{ color: '#52c41a' }} /> 未发现冲突，已生成 {analysisResult?.new_corpus_preview.length || 0} 条回归语料</Space>,
                    children: analysisLoading ? (
                      <div style={{ textAlign: 'center', padding: 24 }}><Spin tip="正在检测语义冲突并生成回归语料，约 10-20 秒…" /></div>
                    ) : analysisResult?.has_conflicts ? (
                      <Space direction="vertical" style={{ width: '100%' }} size="middle">
                        {/* Conflict list */}
                        <Alert
                          type="warning"
                          message="以下已有意图可能被新模板抢走正确命中："
                          description={
                            <List
                              size="small"
                              dataSource={analysisResult.conflicts}
                              renderItem={item => (
                                <List.Item>
                                  <Space direction="vertical" size={2}>
                                    <Text strong>已有意图：「{item.intent}」</Text>
                                    <Text type="secondary">原命中模板：{item.current_template_name}</Text>
                                    <Text type="secondary">{item.explanation}</Text>
                                  </Space>
                                </List.Item>
                              )}
                            />
                          }
                        />
                        {/* LLM analysis */}
                        {analysisResult.llm_analysis && (
                          <Alert type="info" message="大模型分析" description={analysisResult.llm_analysis} />
                        )}
                        {/* Recommendation */}
                        {analysisResult.recommendation_text && (
                          <Alert
                            type="info"
                            message={`建议修改字段：${analysisResult.recommendation_field === 'keywords' ? '关键词' : '场景描述'}`}
                            description={
                              <Space direction="vertical" style={{ width: '100%' }}>
                                <Text code>{analysisResult.recommendation_text}</Text>
                                <Button type="primary" size="small" onClick={handleApplyRecommendation} loading={savingEdit || analysisLoading}>
                                  一键应用建议修改（保存后重新分析）
                                </Button>
                              </Space>
                            }
                          />
                        )}
                        {/* Conflict actions */}
                        <Space>
                          <Button danger onClick={() => doApprove(detail.id, analysisResult.analysis_id)} loading={actionLoading}>
                            忽略冲突，直接批准
                          </Button>
                          <Button onClick={() => { setAnalysisResult(null) }}>取消</Button>
                        </Space>
                      </Space>
                    ) : (
                      // No conflicts
                      <Space direction="vertical" style={{ width: '100%' }} size="middle">
                        {analysisResult?.new_corpus_preview.length ? (
                          <Alert
                            type="success"
                            message="将写入以下回归语料（approve 后自动保存）"
                            description={
                              <List
                                size="small"
                                dataSource={analysisResult.new_corpus_preview}
                                renderItem={item => <List.Item><Text>• {item}</Text></List.Item>}
                              />
                            }
                          />
                        ) : null}
                        <Space>
                          {autoApproveCountdown !== null ? (
                            <>
                              <Button type="primary" icon={<CheckOutlined />}
                                onClick={() => doApprove(detail.id, analysisResult!.analysis_id)}
                                loading={actionLoading}>
                                确认批准（{autoApproveCountdown}s 后自动确认）
                              </Button>
                              <Button onClick={handleCancelAutoApprove}>取消</Button>
                            </>
                          ) : (
                            <Button type="primary" icon={<CheckOutlined />}
                              onClick={() => doApprove(detail.id, analysisResult!.analysis_id)}
                              loading={actionLoading}>
                              确认批准
                            </Button>
                          )}
                        </Space>
                      </Space>
                    ),
                  }]}
                />
              </div>
            )}
          </>
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
