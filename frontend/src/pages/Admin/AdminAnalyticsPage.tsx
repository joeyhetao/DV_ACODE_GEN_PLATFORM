import { useState, useEffect, useCallback } from 'react'
import {
  Card, Row, Col, Statistic, Table, Select, Space, Typography, Button, message, Spin, Tag,
} from 'antd'
import { CopyOutlined, ReloadOutlined } from '@ant-design/icons'
import { Line } from '@ant-design/charts'
import { adminApi } from '../../api/admin'

const { Text } = Typography

interface FeedbackSummary {
  days: number
  total_generations: number
  total_feedbacks: number
  feedback_rate: number
  bad_rate: number
  no_match_rate: number
}
interface TemplateIssueRow {
  template_id: string
  total_count: number
  bad_count: number
  bad_rate: number
}
interface IntentConfusionRow {
  intent: string
  expected_template: string
  actual_template: string
  code_type: string | null
  count: number
}
interface NoMatchRow {
  date: string
  total: number
  no_match_count: number
  no_match_rate: number
}

const WINDOW_OPTIONS = [
  { value: 1, label: '最近 1 天' },
  { value: 7, label: '最近 7 天' },
  { value: 30, label: '最近 30 天' },
  { value: 90, label: '最近 90 天' },
]

export default function AdminAnalyticsPage() {
  const [days, setDays] = useState<number>(7)
  const [summary, setSummary] = useState<FeedbackSummary | null>(null)
  const [issues, setIssues] = useState<TemplateIssueRow[]>([])
  const [confusion, setConfusion] = useState<IntentConfusionRow[]>([])
  const [noMatch, setNoMatch] = useState<NoMatchRow[]>([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [s, i, c, n] = await Promise.all([
        adminApi.analytics.feedbackSummary(days),
        adminApi.analytics.templateIssues(days, 10),
        adminApi.analytics.intentConfusion(days, 20),
        adminApi.analytics.noMatchRate(days),
      ])
      setSummary(s)
      setIssues(i)
      setConfusion(c)
      setNoMatch(n)
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { detail?: unknown } } }
      message.error(`加载失败（HTTP ${err.response?.status ?? '?'}）`)
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => { load() }, [load])

  const copyAsCorpusEntry = (row: IntentConfusionRow) => {
    const id = `confusion_${Date.now()}_${row.expected_template}_vs_${row.actual_template}`
    const note = `From production confusion log: intent classified as ${row.actual_template} but expected ${row.expected_template} (count=${row.count})`
    // code_type 由后端 join templates 表填好，前端不再硬编码。null 时用占位 + 提示。
    const codeTypeLine = row.code_type
      ? `    code_type: ${row.code_type}\n`
      : `    code_type: ""  # template not found — please fill manually\n`
    const yaml =
      `  - id: ${id}\n` +
      `    intent: ${JSON.stringify(row.intent)}\n` +
      codeTypeLine +
      `    expected_template: ${row.expected_template}\n` +
      `    note: ${JSON.stringify(note)}\n`
    navigator.clipboard.writeText(yaml).then(
      () => message.success('已复制为 corpus 条目，可粘贴到 template_selection_corpus.yaml'),
      () => message.error('复制失败：剪贴板不可用'),
    )
  }

  const fmtPct = (v: number) => `${(v * 100).toFixed(2)}%`

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card
        size="small"
        title="L4 反馈与门控分析"
        extra={
          <Space>
            <Select
              value={days}
              onChange={setDays}
              options={WINDOW_OPTIONS}
              style={{ width: 140 }}
            />
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
          </Space>
        }
      >
        <Spin spinning={loading}>
          <Row gutter={16}>
            <Col span={6}>
              <Statistic title="总生成数" value={summary?.total_generations ?? 0} />
            </Col>
            <Col span={6}>
              <Statistic
                title="反馈率"
                value={summary ? fmtPct(summary.feedback_rate) : '0.00%'}
                valueStyle={{ color: '#1677ff' }}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="差评率"
                value={summary ? fmtPct(summary.bad_rate) : '0.00%'}
                valueStyle={{ color: (summary?.bad_rate ?? 0) >= 0.2 ? '#ff4d4f' : '#52c41a' }}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="无匹配模板率"
                value={summary ? fmtPct(summary.no_match_rate) : '0.00%'}
                valueStyle={{ color: (summary?.no_match_rate ?? 0) >= 0.1 ? '#fa8c16' : '#52c41a' }}
              />
            </Col>
          </Row>
          <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>
            反馈率 = 反馈数 / 总生成数；差评率 = 差评数 / 反馈数（无反馈时 0）；
            无匹配率 = 触发 no_matching_template 闸的生成数 / 总生成数。
          </div>
        </Spin>
      </Card>

      <Card size="small" title={`无匹配模板趋势（按天）`}>
        {noMatch.length === 0 ? (
          <Text type="secondary">所选窗口内无生成记录。</Text>
        ) : (
          <Line
            data={noMatch.map((r) => ({ date: r.date, value: r.no_match_rate }))}
            xField="date"
            yField="value"
            point={{ size: 4 }}
            height={240}
            yAxis={{
              label: { formatter: (v: string) => `${(parseFloat(v) * 100).toFixed(1)}%` },
            }}
            tooltip={{
              formatter: (d: { date: string; value: number }) => ({
                name: 'no_match_rate',
                value: `${(d.value * 100).toFixed(2)}%`,
              }),
            }}
          />
        )}
      </Card>

      <Card size="small" title="差评模板 Top 10">
        <Table<TemplateIssueRow>
          dataSource={issues}
          rowKey="template_id"
          size="small"
          pagination={false}
          locale={{ emptyText: '所选窗口内无反馈记录' }}
          columns={[
            { title: '模板 ID', dataIndex: 'template_id' },
            { title: '反馈总数', dataIndex: 'total_count', width: 100 },
            { title: '差评数', dataIndex: 'bad_count', width: 100 },
            {
              title: '差评率',
              dataIndex: 'bad_rate',
              width: 120,
              render: (v: number) => (
                <Tag color={v >= 0.5 ? 'red' : v >= 0.2 ? 'orange' : 'green'}>
                  {fmtPct(v)}
                </Tag>
              ),
            },
          ]}
        />
      </Card>

      <Card size="small" title="意图-模板混淆样本（差评 + LLM 选错）">
        <Table<IntentConfusionRow>
          dataSource={confusion}
          rowKey={(r) => `${r.intent}__${r.expected_template}__${r.actual_template}`}
          size="small"
          pagination={false}
          locale={{ emptyText: '所选窗口内无混淆样本' }}
          columns={[
            { title: '用户意图', dataIndex: 'intent', ellipsis: true },
            { title: '期望模板（RAG top-1）', dataIndex: 'expected_template', width: 220 },
            { title: '实际模板（用户拿到的）', dataIndex: 'actual_template', width: 220 },
            { title: '次数', dataIndex: 'count', width: 80 },
            {
              title: '操作',
              key: 'action',
              width: 180,
              render: (_: unknown, row: IntentConfusionRow) => (
                <Button
                  size="small"
                  icon={<CopyOutlined />}
                  onClick={() => copyAsCorpusEntry(row)}
                >复制为 corpus 条目</Button>
              ),
            },
          ]}
        />
      </Card>
    </Space>
  )
}
