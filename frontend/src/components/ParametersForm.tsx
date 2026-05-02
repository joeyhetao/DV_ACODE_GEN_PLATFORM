import { Form, Input, Tag, Tooltip, Typography } from 'antd'
import type { ParamSource, ParamWithSource } from '../api/generate'
import { validateParamValue } from '../utils/validateParam'

const { Text } = Typography

/** 5 类参数源的视觉元数据 */
export const SOURCE_META: Record<ParamSource, { color: string; emoji: string; label: string }> = {
  signal_list: { color: 'green',   emoji: '🟢', label: '信号列表 role-hint' },
  regex:       { color: 'gold',    emoji: '🟡', label: '从描述正则提取' },
  llm:         { color: 'orange',  emoji: '🟠', label: 'LLM 推断' },
  default:     { color: 'default', emoji: '⚪', label: '模板默认值' },
  placeholder: { color: 'red',     emoji: '🔴', label: '⚠ 必须填写（占位符）' },
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
        const errorMsg = validateParamValue(name, meta.type, meta.value)
        const isPlaceholder = meta.source === 'placeholder'

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
            validateStatus={errorMsg || isPlaceholder ? 'error' : undefined}
            help={errorMsg || (isPlaceholder ? '占位符值"' + valueStr + '" — 请改为实际信号名/数值' : undefined)}
            style={{ marginBottom: 12 }}
          >
            <Input
              value={valueStr}
              onChange={(e) => onChange(name, e.target.value)}
              placeholder={meta.description || `输入 ${name} 的值`}
              status={errorMsg || isPlaceholder ? 'error' : undefined}
            />
          </Form.Item>
        )
      })}
    </Form>
  )
}
