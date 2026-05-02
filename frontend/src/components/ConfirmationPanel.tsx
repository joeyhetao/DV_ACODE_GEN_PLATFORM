import { useMemo, useState } from 'react'
import { Card, Select, Button, Space, Tag, Typography, Alert, Tooltip } from 'antd'
import { CheckOutlined, RollbackOutlined, InfoCircleOutlined } from '@ant-design/icons'
import type {
  ConfidenceSource,
  ParamWithSource,
  PreviewResponse,
  RAGCandidateWithParams,
  SignalInfo,
} from '../api/generate'
import ParametersForm from './ParametersForm'
import { validateParamValue } from '../utils/validateParam'

const { Text } = Typography

interface Props {
  preview: PreviewResponse
  signals: SignalInfo[]
  onCancel: () => void
  onConfirm: (selectedTemplateId: string, finalParams: Record<string, unknown>) => void
}

const CONFIDENCE_SOURCE_LABEL: Record<ConfidenceSource, { label: string; color: string; tip: string }> = {
  llm_step1:    { label: 'LLM 主动选中', color: 'green',  tip: 'LLM Step1 在 RAG 候选中明确选了此模板，confidence=0.9 是固定值' },
  rag_fallback: { label: 'RAG 兜底',     color: 'orange', tip: 'LLM Step1 选不出（返回空 / 选了不存在的 ID），自动取 RAG 第一名；confidence 是 RAG 排序分数' },
  intent_cache: { label: '历史缓存',     color: 'blue',   tip: '同样意图之前已成功生成过，直接复用历史决策（应当走 quick_render 跳过本面板）' },
}

/**
 * 切换模板时重新映射参数（前端轻量版，不调 LLM）。
 *
 * 策略：
 * - 已编辑的同名参数值保留（避免用户工作丢失）
 * - 新模板的 parameters 列表中：
 *   - 如果原 params 里有同名值，标 source 为 'llm'（即"沿用之前的"）
 *   - 否则按 signal-list role-hint / default 等规则填，标 source 对应类别
 *   - required 但仍空 → placeholder
 */
function reMapParamsForNewTemplate(
  newTemplate: RAGCandidateWithParams,
  signals: SignalInfo[],
  oldParams: Record<string, ParamWithSource>,
): Record<string, ParamWithSource> {
  const result: Record<string, ParamWithSource> = {}
  const signalsByRole: Record<string, SignalInfo[]> = {}
  signals.forEach((s) => {
    if (!signalsByRole[s.role]) signalsByRole[s.role] = []
    signalsByRole[s.role].push(s)
  })

  for (const paramDef of newTemplate.parameters || []) {
    const name = paramDef.name as string
    if (!name) continue
    const required = (paramDef.required as boolean) ?? false
    const description = (paramDef.description as string) ?? ''
    const type = (paramDef.type as string) ?? 'string'

    // 1. 沿用旧值（用户可能已编辑）
    if (oldParams[name]) {
      result[name] = { ...oldParams[name], required, description, type }
      continue
    }

    // 2. signal-list role-hint
    const roleHint = paramDef.role_hint as string | null | undefined
    if (roleHint && signalsByRole[roleHint]) {
      const matched = signalsByRole[roleHint]
      const value = matched.length === 1 ? matched[0].name : matched.map((m) => m.name)
      result[name] = { value, source: 'signal_list', required, description, type }
      continue
    }

    // 3. template default
    if (paramDef.default !== undefined && paramDef.default !== null) {
      result[name] = { value: paramDef.default as string, source: 'default', required, description, type }
      continue
    }

    // 4. placeholder（required）
    if (required) {
      result[name] = { value: name, source: 'placeholder', required, description, type }
    }
  }
  return result
}

export default function ConfirmationPanel({ preview, signals, onCancel, onConfirm }: Props) {
  const [selectedTemplateId, setSelectedTemplateId] = useState(preview.template_id)
  const [editedParams, setEditedParams] = useState<Record<string, ParamWithSource>>(preview.params)

  // 切换模板时重映射参数
  const handleSwitchTemplate = (newTid: string) => {
    setSelectedTemplateId(newTid)
    if (newTid === preview.template_id) {
      // 切回原推荐：恢复原 params
      setEditedParams(preview.params)
      return
    }
    const newCandidate = preview.rag_candidates.find((c) => c.template_id === newTid)
    if (!newCandidate) return
    setEditedParams(reMapParamsForNewTemplate(newCandidate, signals, editedParams))
  }

  // 用户编辑某个参数
  const handleParamChange = (name: string, newValue: string) => {
    setEditedParams((prev) => ({
      ...prev,
      [name]: { ...prev[name], value: newValue, source: 'llm' as const },
      // 注：用户编辑后 source 标 'llm' 表示"用户/外部确认值"，徽标变橙色
    }))
  }

  // 校验：是否有 required 且仍是 placeholder 的参数
  const blockingErrors = useMemo(() => {
    const issues: string[] = []
    for (const [name, meta] of Object.entries(editedParams)) {
      if (meta.required && meta.source === 'placeholder') {
        issues.push(`参数 "${name}" 仍是占位符，请改为实际值`)
      }
      const validationErr = validateParamValue(name, meta.type, meta.value)
      if (validationErr) {
        issues.push(`参数 "${name}": ${validationErr}`)
      }
    }
    return issues
  }, [editedParams])

  const canSubmit = blockingErrors.length === 0

  // 当前选中的模板信息
  const currentCandidate = preview.rag_candidates.find((c) => c.template_id === selectedTemplateId)
  const currentName = selectedTemplateId === preview.template_id
    ? preview.template_name
    : (currentCandidate?.name ?? selectedTemplateId)

  const handleSubmit = () => {
    if (!canSubmit) return
    const finalParams: Record<string, unknown> = {}
    for (const [name, meta] of Object.entries(editedParams)) {
      finalParams[name] = meta.value
    }
    onConfirm(selectedTemplateId, finalParams)
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      {/* 推荐模板 */}
      <Card size="small" title={<><InfoCircleOutlined /> 系统推荐模板</>}>
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          <div>
            <Text type="secondary">置信度来源：</Text>
            <Tooltip title={CONFIDENCE_SOURCE_LABEL[preview.confidence_source].tip}>
              <Tag color={CONFIDENCE_SOURCE_LABEL[preview.confidence_source].color}>
                {CONFIDENCE_SOURCE_LABEL[preview.confidence_source].label}
              </Tag>
            </Tooltip>
            <Text>{`${(preview.confidence * 100).toFixed(1)}%`}</Text>
          </div>
          <div>
            <Text type="secondary" style={{ marginRight: 8 }}>选择模板：</Text>
            <Select
              value={selectedTemplateId}
              onChange={handleSwitchTemplate}
              style={{ minWidth: 350 }}
              options={preview.rag_candidates.map((c) => ({
                value: c.template_id,
                label: (
                  <span>
                    {c.template_id === preview.template_id && <Tag color="green" style={{ marginRight: 4 }}>推荐</Tag>}
                    {c.name} <Text type="secondary" style={{ fontSize: 11 }}>({c.template_id}, score={c.score.toFixed(2)})</Text>
                  </span>
                ),
              }))}
            />
          </div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            当前选中：<Text code>{selectedTemplateId}</Text> — {currentName}
          </Text>
        </Space>
      </Card>

      {/* 参数表单 */}
      <Card
        size="small"
        title={<>参数预填充 <Text type="secondary" style={{ fontSize: 12, fontWeight: 'normal' }}>（可编辑）</Text></>}
        extra={
          <Space size={4}>
            <Tag color="green">🟢 信号列表</Tag>
            <Tag color="gold">🟡 正则</Tag>
            <Tag color="orange">🟠 LLM</Tag>
            <Tag color="default">⚪ 默认</Tag>
            <Tag color="red">🔴 占位符</Tag>
          </Space>
        }
      >
        <ParametersForm params={editedParams} onChange={handleParamChange} />
      </Card>

      {/* 校验提示 */}
      {!canSubmit && (
        <Alert
          type="error"
          showIcon
          message="无法生成代码，请处理以下问题："
          description={
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {blockingErrors.map((err, i) => <li key={i}>{err}</li>)}
            </ul>
          }
        />
      )}

      {/* 操作栏 */}
      <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
        <Button icon={<RollbackOutlined />} onClick={onCancel}>取消</Button>
        <Button
          type="primary"
          icon={<CheckOutlined />}
          disabled={!canSubmit}
          onClick={handleSubmit}
          size="large"
        >
          确认并生成代码
        </Button>
      </Space>
    </Space>
  )
}
