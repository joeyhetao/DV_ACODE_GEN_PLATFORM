import { useState, useEffect } from 'react'
import { useNavigate, NavigateFunction, useLocation, useSearchParams } from 'react-router-dom'
import {
  Card, Form, Input, Select, Button, Row, Col, Space, Tag,
  Statistic, Divider, Typography, Table, Collapse, message, Modal, Spin,
} from 'antd'
import {
  ThunderboltOutlined, CopyOutlined, SendOutlined, PlusOutlined, DeleteOutlined,
  LoadingOutlined,
} from '@ant-design/icons'
import Editor from '@monaco-editor/react'
import { generateApi, PreviewResponse, SignalInfo } from '../../api/generate'
import ConfirmationPanel from '../../components/ConfirmationPanel'

const { TextArea } = Input
const { Text } = Typography

type SignalRow = SignalInfo & { _key: string }

let _signalCounter = 0
const newSignalKey = () => `sig_${++_signalCounter}`

// 方案 3 状态机
type GenerateState =
  | { phase: 'idle' }
  | { phase: 'previewing' }
  | { phase: 'confirming'; preview: PreviewResponse }
  | { phase: 'rendering' }
  | { phase: 'result'; result: ResultDisplay }

interface ResultDisplay {
  code: string
  cache_hit: boolean
  template_id: string
  template_version: string
  template_name: string
  confidence: number
  confidence_source: string
  rag_candidates: Array<{ template_id: string; name: string; score: number }>
}

interface IntentBuilderReturnState {
  prefillText?: string
  prefillCodeType?: string
  source?: string
}

export default function GeneratePage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  // P2-17：URL query 优先于 location.state——刷新页面 location.state 会丢但 URL 不会
  const returnState = (location.state || {}) as IntentBuilderReturnState
  const queryPrefill = searchParams.get('prefill') || ''
  const queryCodeType = searchParams.get('code_type') || ''
  const querySource = searchParams.get('source') || ''
  const initialSource = querySource || returnState.source || 'direct'
  const [form] = Form.useForm()
  const [state, setState] = useState<GenerateState>({ phase: 'idle' })
  const [codeTypes, setCodeTypes] = useState<{ id: string; display_name: string }[]>([])
  // v3.0：source 用于区分 direct vs intent_builder 回流（仅用于上报 PipelineInput.source 字段）
  const [requestSource, setRequestSource] = useState<string>(initialSource)
  const [signals, setSignals] = useState<SignalRow[]>([])

  useEffect(() => {
    generateApi.codeTypes().then(setCodeTypes).catch(() => {})
  }, [])

  // v3.0 + P2-17：从 IntentBuilder 回流时自动 prefill TextArea + code_type
  // URL query 优先（刷新可恢复），location.state 作为 fallback
  useEffect(() => {
    const text = queryPrefill || returnState.prefillText
    const codeType = queryCodeType || returnState.prefillCodeType
    if (text) {
      form.setFieldsValue({
        text,
        code_type: codeType || form.getFieldValue('code_type'),
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryPrefill, returnState.prefillText])

  // ── 步骤 1：分析（preview）──────────────────────────────────────
  const handleAnalyze = async (values: Record<string, unknown>) => {
    setState({ phase: 'previewing' })
    const signalsForApi = signals.map(({ _key: _, ...s }) => s)
    const reqBody = {
      text: values.text as string,
      code_type: values.code_type as string,
      protocol: values.protocol as string | undefined,
      clk: (values.clk as string) || 'clk',
      rst: (values.rst as string) || 'rst_n',
      rst_polarity: (values.rst_polarity as string) || '低有效',
      signals: signalsForApi,
      source: requestSource,  // v3.0：direct 或 intent_builder（回流），仅供后端日志
    }
    try {
      const preview = await generateApi.preview(reqBody)
      // P2-16：只在**成功**后才把 source 清零回 'direct'——失败重试时保留原 source，
      // 不丢失 IntentBuilder 回流统计标签。
      if (requestSource !== 'direct') setRequestSource('direct')
      // 缓存命中：跳过确认面板，直接渲染
      if (preview.quick_render) {
        await runRender(preview, preview.template_id, extractValueDict(preview), reqBody)
        return
      }
      setState({ phase: 'confirming', preview })
    } catch (e: unknown) {
      handleApiError(e, '分析失败，请重试', navigate)
      setState({ phase: 'idle' })
    }
  }

  // ── 步骤 2：用户确认后渲染 ────────────────────────────────────
  const handleConfirm = async (selectedTemplateId: string, finalParams: Record<string, unknown>) => {
    if (state.phase !== 'confirming') return
    const preview = state.preview
    // 用户可能切换了模板：以 selectedTemplateId 为准
    const tplId = selectedTemplateId
    const tplVersion = tplId === preview.template_id
      ? preview.template_version
      : '1.0.0' // RAGCandidateWithParams 没透传 version，默认 1.0.0；以后可在后端补
    const formValues = form.getFieldsValue()
    await runRender(preview, tplId, finalParams, {
      text: formValues.text as string,
      code_type: formValues.code_type as string,
    }, tplVersion)
  }

  // 共享的 render 调用
  const runRender = async (
    preview: PreviewResponse,
    templateId: string,
    params: Record<string, unknown>,
    formCtx: { text: string; code_type: string },
    tplVersion?: string,
  ) => {
    setState({ phase: 'rendering' })
    try {
      const res = await generateApi.renderConfirmed({
        template_id: templateId,
        template_version: tplVersion || preview.template_version,
        params,
        intent_hash: preview.intent_hash,
        confidence: preview.confidence,
        confidence_source: preview.confidence_source,
        normalized_intent: preview.normalized_intent,
        original_intent: formCtx.text,
        rag_candidates: preview.rag_candidates.map((c) => ({
          template_id: c.template_id,
          name: c.name,
          score: c.score,
        })),
        code_type: formCtx.code_type,
      })
      const tplName = templateId === preview.template_id
        ? preview.template_name
        : (preview.rag_candidates.find((c) => c.template_id === templateId)?.name ?? templateId)
      setState({
        phase: 'result',
        result: {
          code: res.code,
          cache_hit: res.cache_hit,
          template_id: templateId,
          template_version: tplVersion || preview.template_version,
          template_name: tplName,
          confidence: preview.confidence,
          confidence_source: preview.confidence_source,
          rag_candidates: preview.rag_candidates.map((c) => ({
            template_id: c.template_id, name: c.name, score: c.score,
          })),
        },
      })
    } catch (e: unknown) {
      handleApiError(e, '渲染失败，请重试', navigate)
      setState({ phase: 'idle' })
    }
  }

  const handleCancel = () => setState({ phase: 'idle' })
  const handleReset = () => setState({ phase: 'idle' })

  const copyCode = () => {
    if (state.phase === 'result' && state.result.code) {
      navigator.clipboard.writeText(state.result.code)
      message.success('已复制到剪贴板')
    }
  }

  const addSignal = () => setSignals((prev) => [...prev, { name: '', width: 1, role: 'other', _key: newSignalKey() }])
  const removeSignal = (key: string) => setSignals((prev) => prev.filter((s) => s._key !== key))
  const updateSignal = (key: string, field: keyof SignalInfo, value: string | number) => {
    setSignals((prev) => prev.map((s) => s._key === key ? { ...s, [field]: value } : s))
  }

  const isBusy = state.phase === 'previewing' || state.phase === 'rendering'

  return (
    <Row gutter={24}>
      {/* Left: input panel */}
      <Col span={10}>
        <Card title={<><ThunderboltOutlined /> 意图描述</>}>
          <Form form={form} layout="vertical" onFinish={handleAnalyze}>
            <Form.Item name="text" label="功能描述" rules={[{ required: true, message: '请输入功能描述' }]}>
              <TextArea rows={5} placeholder="描述你想生成的验证代码功能，例如：寄存器写保护场景的数据完整性断言：模块名为 reg_block，当写使能无效时数据信号不被意外修改" />
            </Form.Item>
            <Row gutter={12}>
              <Col span={12}>
                <Form.Item name="code_type" label="代码类型" rules={[{ required: true }]}>
                  <Select placeholder="选择代码类型">
                    {codeTypes.map((ct) => (
                      <Select.Option key={ct.id} value={ct.id}>{ct.display_name}</Select.Option>
                    ))}
                  </Select>
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="protocol" label="协议">
                  <Select placeholder="可选" allowClear>
                    <Select.Option value="AXI4">AXI4</Select.Option>
                    <Select.Option value="AXI4-Lite">AXI4-Lite</Select.Option>
                    <Select.Option value="AXI4-Stream">AXI4-Stream</Select.Option>
                  </Select>
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={12}>
              <Col span={12}>
                <Form.Item name="clk" label="时钟信号">
                  <Input placeholder="clk" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="rst" label="复位信号">
                  <Input placeholder="rst_n" />
                </Form.Item>
              </Col>
            </Row>

            <Divider orientation="left" plain>信号列表（可选；assertion 模板强烈推荐）</Divider>
            {signals.map((sig) => (
              <Row key={sig._key} gutter={8} style={{ marginBottom: 8 }}>
                <Col span={9}>
                  <Input placeholder="信号名" value={sig.name} onChange={(e) => updateSignal(sig._key, 'name', e.target.value)} />
                </Col>
                <Col span={5}>
                  <Input type="number" min={1} placeholder="位宽" value={sig.width}
                    onChange={(e) => updateSignal(sig._key, 'width', parseInt(e.target.value) || 1)} />
                </Col>
                <Col span={8}>
                  <Select value={sig.role} onChange={(v) => updateSignal(sig._key, 'role', v)} style={{ width: '100%' }}>
                    {['valid', 'ready', 'data', 'enable', 'state', 'control', 'other'].map((r) => (
                      <Select.Option key={r} value={r}>{r}</Select.Option>
                    ))}
                  </Select>
                </Col>
                <Col span={2}>
                  <Button icon={<DeleteOutlined />} danger size="small" onClick={() => removeSignal(sig._key)} />
                </Col>
              </Row>
            ))}
            <Button icon={<PlusOutlined />} onClick={addSignal} size="small" style={{ marginBottom: 16 }}>添加信号</Button>

            <Form.Item>
              <Button type="primary" htmlType="submit" loading={isBusy} icon={<SendOutlined />} block size="large">
                {state.phase === 'previewing' ? '正在分析...' : (state.phase === 'rendering' ? '正在渲染...' : '分析意图')}
              </Button>
            </Form.Item>
          </Form>
        </Card>
      </Col>

      {/* Right: phase-aware panel */}
      <Col span={14}>
        {state.phase === 'idle' && (
          <Card style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ textAlign: 'center', color: '#bbb', padding: '80px 0' }}>
              <ThunderboltOutlined style={{ fontSize: 48 }} />
              <div style={{ marginTop: 16 }}>输入意图描述，点击「分析意图」</div>
              <div style={{ marginTop: 8, fontSize: 12 }}>系统会推荐模板并预填充参数，用户确认后再渲染代码</div>
            </div>
          </Card>
        )}

        {state.phase === 'previewing' && (
          <Card style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ textAlign: 'center', padding: '80px 0' }}>
              <Spin indicator={<LoadingOutlined style={{ fontSize: 48 }} spin />} />
              <div style={{ marginTop: 24, color: '#666' }}>正在分析意图...</div>
              <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>
                normalize_intent → RAG → LLM 选模板 → 预填充参数（5-30 秒）
              </div>
            </div>
          </Card>
        )}

        {state.phase === 'confirming' && (
          <ConfirmationPanel
            preview={state.preview}
            signals={signals.map(({ _key: _, ...s }) => s)}
            onCancel={handleCancel}
            onConfirm={handleConfirm}
          />
        )}

        {state.phase === 'rendering' && (
          <Card style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ textAlign: 'center', padding: '80px 0' }}>
              <Spin indicator={<LoadingOutlined style={{ fontSize: 48 }} spin />} />
              <div style={{ marginTop: 24, color: '#666' }}>正在渲染代码...</div>
              <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>Jinja2 渲染（&lt; 1 秒）</div>
            </div>
          </Card>
        )}

        {state.phase === 'result' && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Card size="small">
              <Row gutter={16}>
                <Col span={6}>
                  <Statistic
                    title="置信度"
                    value={`${(state.result.confidence * 100).toFixed(1)}%`}
                    valueStyle={{ color: state.result.confidence >= 0.85 ? '#52c41a' : '#fa8c16' }}
                  />
                </Col>
                <Col span={6}>
                  <Statistic title="命中缓存" value={state.result.cache_hit ? '是' : '否'} />
                </Col>
                <Col span={12}>
                  <Text type="secondary">模板: </Text>
                  <Text code>{state.result.template_id}</Text>
                  <Tag color="cyan" style={{ marginLeft: 8 }}>{state.result.confidence_source}</Tag>
                </Col>
              </Row>
            </Card>

            <Card
              title={<>生成代码 <Text type="secondary" style={{ fontSize: 12, fontWeight: 'normal' }}>— {state.result.template_name}</Text></>}
              extra={
                <Space>
                  <Button icon={<CopyOutlined />} onClick={copyCode}>复制</Button>
                  <Button onClick={handleReset}>重新输入</Button>
                </Space>
              }
            >
              <div className="code-editor-wrap">
                <Editor
                  height="420px"
                  language="systemverilog"
                  value={state.result.code}
                  options={{ readOnly: true, minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false }}
                  theme="vs"
                />
              </div>
            </Card>

            {state.result.rag_candidates.length > 0 && (
              <Collapse size="small" items={[{
                key: '1',
                label: `RAG 候选模板 (Top ${state.result.rag_candidates.length})`,
                children: (
                  <Table
                    dataSource={state.result.rag_candidates}
                    rowKey="template_id"
                    size="small"
                    pagination={false}
                    columns={[
                      { title: '模板ID', dataIndex: 'template_id', width: 220 },
                      { title: '名称', dataIndex: 'name' },
                      { title: '分数', dataIndex: 'score', width: 80, render: (v: number) => v.toFixed(4) },
                    ]}
                  />
                ),
              }]} />
            )}
          </Space>
        )}
      </Col>
    </Row>
  )
}

/** 提取 PreviewResponse.params 中的 value 字段（缓存命中走 quick_render 时用）。 */
function extractValueDict(preview: PreviewResponse): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [name, meta] of Object.entries(preview.params)) {
    out[name] = meta.value
  }
  return out
}

/** 解析 FastAPI 错误响应。detail 可能是字符串或结构化对象（off_topic / code_type_mismatch 等）。 */
type OffTopicDetail = {
  type: 'off_topic'
  message: string
  detector?: string
  top_dense_score?: number
  threshold?: number
  redirect_to?: string | null
}
type CodeTypeMismatchDetail = {
  type: 'code_type_mismatch'
  message: string
  detector?: string
  selected_code_type: string
  suggested_code_type: string
  selected_score: number
  suggested_score: number
  redirect_to?: string | null
}
type MissingParam = {
  name: string
  description: string
  expr_type?: string
  role_hint?: string
}
type UnderSpecifiedDetail = {
  type: 'under_specified'
  message: string
  detector?: string
  template_id: string
  template_name: string
  missing_params: MissingParam[]
  redirect_to?: string | null
}
type NoMatchingTemplateDetail = {
  type: 'no_matching_template'
  message: string
  top_score: number
  redirect_to: string
}
type ApiErrorDetail = string | OffTopicDetail | CodeTypeMismatchDetail | UnderSpecifiedDetail | NoMatchingTemplateDetail | undefined

function handleApiError(e: unknown, fallbackMsg: string, navigate?: NavigateFunction): void {
  const err = e as { response?: { status?: number; data?: { detail?: ApiErrorDetail } } }
  const detail = err.response?.data?.detail
  const status = err.response?.status

  // 第五道闸：库内无匹配模板，先提示再跳贡献页（在通用 redirect_to 检查之前处理，以便显示 toast）
  if (detail && typeof detail === 'object' && detail.type === 'no_matching_template') {
    message.info('库内暂无匹配模板，跳转至贡献页面帮助完善模板库')
    if (navigate && 'redirect_to' in detail && detail.redirect_to) navigate(detail.redirect_to)
    return
  }

  // v3.0：detail.redirect_to 优先于一切——后端明示前端应跳转的路由，前端无脑 router.push
  // off_topic / code_type_mismatch / empty_retrieval 三种 detail.redirect_to=null 不触发本分支
  // 用 in 操作符做 type guard，避免 TS 在联合类型上窄化失败
  if (
    detail
    && typeof detail === 'object'
    && 'redirect_to' in detail
    && typeof detail.redirect_to === 'string'
    && detail.redirect_to.length > 0
    && navigate
  ) {
    navigate(detail.redirect_to)
    return
  }

  if (detail && typeof detail === 'object' && detail.type === 'off_topic') {
    const diag =
      detail.top_dense_score !== undefined && detail.threshold !== undefined
        ? `（输入与模板库的最高相似度 ${detail.top_dense_score} 低于阈值 ${detail.threshold}）`
        : ''
    Modal.warning({
      title: '检测到非验证请求',
      content: `${detail.message}\n\n${diag}\n\n如果你确认这是 IC 验证请求被误拒，请补充信号名、协议、要验证的属性等更多上下文重试。`,
      width: 520,
    })
    return
  }
  if (detail && typeof detail === 'object' && detail.type === 'code_type_mismatch') {
    Modal.warning({
      title: '代码类型选错了',
      content:
        `${detail.message}\n\n` +
        `语义匹配度对比：\n` +
        `  · 当前选择「${detail.selected_code_type}」 ${detail.selected_score}\n` +
        `  · 建议改为「${detail.suggested_code_type}」 ${detail.suggested_score}\n\n` +
        `先在左侧「代码类型」下拉框切换到「${detail.suggested_code_type}」再重试。`,
      width: 520,
    })
    return
  }
  if (detail && typeof detail === 'object' && detail.type === 'under_specified') {
    const lines = detail.missing_params.map((p) => {
      const desc = p.description ? ` — ${p.description}` : ''
      return `  · ${p.name}${desc}`
    })
    Modal.warning({
      title: '描述信息不完整',
      content:
        `已识别推荐模板「${detail.template_name}」(${detail.template_id})，但下列必填参数无法从你的描述中提取：\n\n` +
        lines.join('\n') +
        `\n\n请在意图描述里补充这些信息再重试。例如把"生成一个 FSM 转换覆盖率"改成` +
        `"对状态信号 cur_state 做 FSM 转换覆盖率，状态包括 IDLE, ACTIVE, DONE"。`,
      width: 600,
    })
    return
  }
  // Fallback：detail 不是已知结构化 type 也不是字符串时（如 FastAPI 默认 500 / 网络错误），
  // 把 HTTP 状态 + detail 摘要拼进消息，避免黑盒"生成失败"难定位
  const detailStr =
    typeof detail === 'string'
      ? detail
      : detail
        ? JSON.stringify(detail).slice(0, 200)
        : ''
  const suffix = status
    ? `（HTTP ${status}${detailStr ? `: ${detailStr}` : ''}）`
    : detailStr
      ? `：${detailStr}`
      : ''
  message.error(`${fallbackMsg}${suffix}`)
}
