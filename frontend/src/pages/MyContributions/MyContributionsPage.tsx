import { useState, useEffect } from 'react'
import {
  Card, Table, Tag, Button, Space, Modal, Form, Input, Select,
  Drawer, Descriptions, Typography, message, Alert, Steps, Spin,
} from 'antd'
import { PlusOutlined, EyeOutlined, CopyOutlined } from '@ant-design/icons'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import {
  contributionsApi, ContributionListItem, Contribution, ContributionPreview,
} from '../../api/contributions'
import { generateApi } from '../../api/generate'

const { TextArea } = Input
const { Text } = Typography

// v3.0 ↔ DB Enum 对齐：(pending_review, under_review, needs_revision, approved, rejected)
const statusColors: Record<string, string> = {
  pending_review: 'blue', under_review: 'cyan', approved: 'green', rejected: 'red',
  needs_revision: 'orange',
}
const statusLabels: Record<string, string> = {
  pending_review: '待审核', under_review: '审核中', approved: '已批准', rejected: '已拒绝',
  needs_revision: '需修改',
}

interface PrefillState {
  prefillDescription?: string
  prefillCodeType?: string
}

interface SubmitErrorDetail {
  type?: string
  stage?: string
  reason?: string
  message?: string
}

export default function MyContributionsPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  // P2-17：URL query 优先（刷新恢复），location.state 作为 fallback
  const prefillFromState = (location.state || {}) as PrefillState
  const prefill: PrefillState = {
    prefillDescription:
      searchParams.get('description') || prefillFromState.prefillDescription,
    prefillCodeType:
      searchParams.get('code_type') || prefillFromState.prefillCodeType,
  }
  const [list, setList] = useState<ContributionListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [submitVisible, setSubmitVisible] = useState(false)
  const [detailVisible, setDetailVisible] = useState(false)
  const [detail, setDetail] = useState<Contribution | null>(null)
  const [codeTypes, setCodeTypes] = useState<{ id: string; display_name: string }[]>([])

  // FEAT-10: 两步流状态
  const [step, setStep] = useState<0 | 1>(0)
  const [step0Form] = Form.useForm()
  const [step1Form] = Form.useForm()
  const [previewLoading, setPreviewLoading] = useState(false)
  const [submittingReview, setSubmittingReview] = useState(false)
  const [submittingImmediate, setSubmittingImmediate] = useState(false)
  const [previewData, setPreviewData] = useState<ContributionPreview | null>(null)
  const [parseError, setParseError] = useState<{ stage: string; reason: string } | null>(null)
  const [submittedDemoCode, setSubmittedDemoCode] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const res = await contributionsApi.my()
      setList(res)
    } finally {
      setLoading(false)
    }
  }

  const resetModal = () => {
    setSubmitVisible(false)
    setStep(0)
    setPreviewData(null)
    setParseError(null)
    setSubmittedDemoCode(null)
    step0Form.resetFields()
    step1Form.resetFields()
  }

  useEffect(() => {
    load()
    generateApi.codeTypes().then(setCodeTypes).catch(() => {})
  }, [])

  // v3.0：从 IntentBuilder 跳过来时，自动打开提交 Modal 并预填 description / code_type 到 Step 0
  useEffect(() => {
    if (prefill.prefillDescription || prefill.prefillCodeType) {
      step0Form.setFieldsValue({
        original_intent: prefill.prefillDescription || '',
        code_type: prefill.prefillCodeType || 'assertion',
      })
      setSubmitVisible(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill.prefillDescription, prefill.prefillCodeType])

  const showDetail = async (id: string) => {
    const c = await contributionsApi.get(id)
    setDetail(c)
    setDetailVisible(true)
  }

  const extractParseError = (e: unknown): SubmitErrorDetail | null => {
    const err = e as { response?: { data?: { detail?: SubmitErrorDetail | string } } }
    const d = err.response?.data?.detail
    if (d && typeof d === 'object') return d
    return null
  }

  // FEAT-10 Step 0 → Step 1：调 /preview 让 LLM 生成完整模板
  const handlePreview = async () => {
    const values = await step0Form.validateFields()
    setPreviewLoading(true)
    setParseError(null)
    try {
      const preview = await contributionsApi.preview({
        original_intent: values.original_intent,
        code_type: values.code_type,
      })
      setPreviewData(preview)
      step1Form.setFieldsValue({
        template_name: preview.template_name,
        description: preview.description,
        demo_code: preview.demo_code,
      })
      setStep(1)
    } catch (e: unknown) {
      const d = extractParseError(e)
      if (d?.type === 'contribution_parse_failed') {
        setParseError({ stage: d.stage || 'unknown', reason: d.reason || '' })
      } else {
        message.error(d?.message || '预览生成失败')
      }
    } finally {
      setPreviewLoading(false)
    }
  }

  // 共用 submit：Step 1 内点"提交审核"或"立即使用"都走这个
  const submitCurrent = async (
    setLoading: (v: boolean) => void,
  ): Promise<Contribution | null> => {
    const intent = step0Form.getFieldValue('original_intent') as string
    const codeType = step0Form.getFieldValue('code_type') as string
    const values = await step1Form.validateFields()
    setLoading(true)
    setParseError(null)
    try {
      const created = await contributionsApi.submit({
        original_intent: intent,
        code_type: codeType,
        template_name: values.template_name,
        description: values.description,
        demo_code: values.demo_code,
      })
      return created
    } catch (e: unknown) {
      const d = extractParseError(e)
      if (d?.type === 'contribution_parse_failed') {
        setParseError({ stage: d.stage || 'unknown', reason: d.reason || '' })
      } else if (d?.type === 'contribution_name_duplicate') {
        message.error(d.message || '模板名重复，请修改后再提交')
      } else {
        message.error(d?.message || '提交失败')
      }
      return null
    } finally {
      setLoading(false)
    }
  }

  const handleSubmitForReview = async () => {
    const created = await submitCurrent(setSubmittingReview)
    if (created) {
      message.success('提交成功，等待管理员审核')
      resetModal()
      load()
    }
  }

  const handleUseImmediately = async () => {
    const created = await submitCurrent(setSubmittingImmediate)
    if (created) {
      // Step 1 页面内展示可复制代码框（用 Step 1 表单里用户最终确认的 demo_code）
      const code = step1Form.getFieldValue('demo_code') as string
      setSubmittedDemoCode(code)
      message.success('提交成功，模板已进入审核队列')
      load()
    }
  }

  const handleCopy = async () => {
    if (!submittedDemoCode) return
    try {
      await navigator.clipboard.writeText(submittedDemoCode)
      message.success('已复制到剪贴板')
    } catch {
      message.error('复制失败，请手动选中代码块')
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

      {/* FEAT-10 两步提交流 */}
      <Modal
        title="提交模板贡献"
        open={submitVisible}
        onCancel={resetModal}
        width={820}
        destroyOnClose
        footer={renderFooter()}
      >
        <Steps
          current={step}
          size="small"
          style={{ marginBottom: 24 }}
          items={[
            { title: '描述意图' },
            { title: '预览并提交' },
          ]}
        />

        {parseError && (
          <Alert
            type="error"
            showIcon
            closable
            onClose={() => setParseError(null)}
            message={`AI 解析失败（阶段：${parseError.stage}）`}
            description={
              <>
                {parseError.reason}
                <br />
                <Text type="secondary">请完善意图描述或调整字段后重试。</Text>
              </>
            }
            style={{ marginBottom: 16 }}
          />
        )}

        {step === 0 && (
          <>
            <Alert
              type="info"
              showIcon
              message="只需填两件事，剩下的 AI 会自动生成"
              description="后端会基于你的意图描述与代码类型，让 LLM 生成模板名、场景描述、完整 SystemVerilog 示例代码，以及参数列表。下一步可编辑。"
              style={{ marginBottom: 16 }}
            />
            <Spin spinning={previewLoading} tip="AI 生成中（约 5-15 秒）...">
              <Form form={step0Form} layout="vertical">
                <Form.Item
                  name="original_intent"
                  label="验证意图描述"
                  rules={[{ required: true, message: '必填' }]}
                  extra="用自然语言描述你想验证什么；越具体越好，AI 生成的模板会更贴合。"
                >
                  <TextArea
                    rows={4}
                    placeholder="如：检测 AXI valid-ready 握手期间，地址 awaddr 必须保持稳定，直到握手完成"
                  />
                </Form.Item>
                <Form.Item name="code_type" label="代码类型" rules={[{ required: true, message: '必填' }]}>
                  <Select placeholder="选择代码类型">
                    {codeTypes.map((ct) => (
                      <Select.Option key={ct.id} value={ct.id}>{ct.display_name}</Select.Option>
                    ))}
                  </Select>
                </Form.Item>
              </Form>
            </Spin>
          </>
        )}

        {step === 1 && (
          <>
            {previewData?.name_conflict && (
              <Alert
                type={previewData.is_semantic_duplicate ? 'info' : 'warning'}
                showIcon
                message={previewData.is_semantic_duplicate ? '库中已有相同场景模板' : '模板名称已被占用'}
                description={
                  previewData.is_semantic_duplicate ? (
                    <>
                      库中已存在名为「{previewData.template_name}」且场景相同的模板，无需重复提交。
                      <br />
                      <Button
                        type="link"
                        size="small"
                        style={{ padding: 0, marginTop: 4 }}
                        onClick={() => { resetModal(); navigate('/generate') }}
                      >
                        前往代码生成页直接使用 →
                      </Button>
                    </>
                  ) : (
                    <>
                      AI 生成的名称「{previewData.template_name}」已被库中另一个不同场景的模板占用，
                      请在下方手动修改模板名称后再提交。
                    </>
                  )
                }
                style={{ marginBottom: 16 }}
              />
            )}
            {submittedDemoCode ? (
              <>
                <Alert
                  type="success"
                  showIcon
                  message="代码已就绪，可直接复制使用"
                  description="模板已提交审核，审核通过后将加入模板库。"
                  style={{ marginBottom: 16 }}
                />
                <div style={{ marginBottom: 8 }}>
                  <Button icon={<CopyOutlined />} onClick={handleCopy}>复制代码</Button>
                </div>
                <pre
                  style={{
                    background: '#f5f5f5',
                    padding: 12,
                    borderRadius: 6,
                    overflow: 'auto',
                    fontSize: 13,
                    fontFamily: 'monospace',
                    maxHeight: 480,
                  }}
                >
                  {submittedDemoCode}
                </pre>
              </>
            ) : (
              <Form form={step1Form} layout="vertical">
                <Form.Item
                  name="template_name"
                  label="模板名称"
                  rules={[{ required: true, message: '必填' }]}
                  extra="命名规范：sva_<scenario>_v<N> 或 cov_<scenario>_v<N>"
                >
                  <Input />
                </Form.Item>
                <Form.Item
                  name="description"
                  label="场景描述"
                  rules={[{ required: true, message: '必填' }]}
                >
                  <TextArea rows={3} />
                </Form.Item>
                <Form.Item
                  name="demo_code"
                  label="代码示例"
                  rules={[{ required: true, message: '必填' }]}
                  extra="可编辑——这是 AI 基于你的意图生成的 SystemVerilog 代码"
                >
                  <TextArea
                    rows={12}
                    style={{ fontFamily: 'monospace', fontSize: 13 }}
                  />
                </Form.Item>
              </Form>
            )}
          </>
        )}
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

  function renderFooter() {
    if (step === 0) {
      return [
        <Button key="cancel" onClick={resetModal}>取消</Button>,
        <Button key="preview" type="primary" loading={previewLoading} onClick={handlePreview}>
          生成预览
        </Button>,
      ]
    }
    // Step 1
    if (submittedDemoCode) {
      // 已"立即使用"提交完成——只展示关闭按钮
      return [<Button key="close" type="primary" onClick={resetModal}>关闭</Button>]
    }
    return [
      <Button key="back" onClick={() => setStep(0)} disabled={submittingReview || submittingImmediate}>上一步</Button>,
      <Button key="submit" loading={submittingReview} disabled={submittingImmediate} onClick={handleSubmitForReview}>提交审核</Button>,
      <Button key="immediate" type="primary" loading={submittingImmediate} disabled={submittingReview} onClick={handleUseImmediately}>
        立即使用
      </Button>,
    ]
  }
}
