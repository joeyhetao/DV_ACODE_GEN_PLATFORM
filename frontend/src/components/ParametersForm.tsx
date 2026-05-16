import { Form, Input, Tag, Tooltip, Typography } from 'antd'
import type { ParamSource, ParamWithSource } from '../api/generate'
import { validateParamValue } from '../utils/validateParam'

const { Text } = Typography

/** 6 类参数源的视觉元数据。
 * 主路径下 placeholder / semantic_fallback 已被 under_specified 闸早返 422，
 * 但在闸关闭 / 单参数被改写时仍可能出现，所以视觉规则保留。 */
export const SOURCE_META: Record<ParamSource, { color: string; emoji: string; label: string }> = {
  signal_list:       { color: 'green',   emoji: '🟢', label: '信号列表 role-hint' },
  regex:             { color: 'gold',    emoji: '🟡', label: '从描述正则提取' },
  llm:               { color: 'orange',  emoji: '🟠', label: 'LLM 推断' },
  default:           { color: 'default', emoji: '⚪', label: '模板默认值' },
  semantic_fallback: { color: 'red',     emoji: '🔴', label: '⚠ 系统按经验猜的，请描述里明确' },
  placeholder:       { color: 'red',     emoji: '🔴', label: '⚠ 必须填写（占位符）' },
}

export function SourceBadge({ source }: { source: ParamSource }) {
  const meta = SOURCE_META[source]
  return (
    <Tooltip title={meta.label}>
      <Tag color={meta.color} style={{ cursor: 'help', minWidth: 30, textAlign: 'center' }}>
        {meta.emoji}
      </Tag>
    </Tooltip>
  )
}

interface Props {
  params: Record<string, ParamWithSource>
  onChange: (paramName: string, newValue: string) => void
}

export default function ParametersForm({ params, onChange }: Props) {
  const entries = Object.entries(params)

  if (entries.length === 0) {
    return <Text type="secondary">该模板无可填充参数</Text>
  }

  return (
    <Form layout="vertical" size="small">
      {entries.map(([name, meta]) => {
        const valueStr = Array.isArray(meta.value) ? meta.value.join(', ') : String(meta.value)
        // 优先：后端 expr_validator 已经报错（sv_boolean_expr / sv_bins_expr），直接显示
        // 次之：前端按 expr_type / 白名单走本地校验
        const errorMsg = meta.validation_error || validateParamValue(name, meta.type, meta.value, meta.expr_type)
        // placeholder / semantic_fallback 都是"系统猜的"——主路径已被 under_specified 闸早返，
        // 这里残留的渲染只在闸关 / 单参数改写场景下出现。两者视觉行为一致。
        const isLowConf = meta.source === 'placeholder' || meta.source === 'semantic_fallback'
        const lowConfHelp =
          meta.source === 'placeholder'
            ? '占位符值"' + valueStr + '" — 请改为实际信号名/数值'
            : meta.source === 'semantic_fallback'
              ? '系统按经验猜的"' + valueStr + '" — 请改为实际值'
              : undefined

        return (
          <Form.Item
            key={name}
            label={
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <SourceBadge source={meta.source} />
                <Tooltip title={meta.description || '无描述'}>
                  <span style={{ fontWeight: 500 }}>
                    {name}
                    {meta.required && <span style={{ color: '#ff4d4f', marginLeft: 4 }}>*</span>}
                  </span>
                </Tooltip>
                <Text type="secondary" style={{ fontSize: 11 }}>{meta.type}</Text>
              </span>
            }
            validateStatus={errorMsg || isLowConf ? 'error' : undefined}
            help={errorMsg || lowConfHelp}
            style={{ marginBottom: 12 }}
          >
            <Input
              value={valueStr}
              onChange={(e) => onChange(name, e.target.value)}
              placeholder={meta.description || `输入 ${name} 的值`}
              status={errorMsg || isLowConf ? 'error' : undefined}
            />
          </Form.Item>
        )
      })}
    </Form>
  )
}
