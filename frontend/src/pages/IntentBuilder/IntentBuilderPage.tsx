/**
 * v3.0 IntentBuilder 多轮对话 UI（替换 v2 表单式）。
 *
 * 布局：
 *  - 左侧（主区）：ChatMessageList（user/assistant 气泡） + TextArea + 发送按钮
 *  - 右侧（辅区）：RAG 候选 Card 列表
 *  - 顶部：当前 accumulated_intent 显示框
 *  - 底部：「用这条意图回去生成」+「贡献新模板」两个出口按钮
 *
 * URL 参数：?prefill=<原始意图>&template_id=<已识别模板>&code_type=<assertion|coverage>&missing=<csv 缺失参数>
 * 来自 Generate 页 under_specified 跳转的 redirect_to。
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Card, Input, Button, Space, Typography, Alert, Tag, Spin, Empty, message,
} from 'antd'
import { SendOutlined, RollbackOutlined, PlusOutlined } from '@ant-design/icons'
import {
  intentBuilderApi,
  IntentBuilderChatResponse,
  RAGCandidateBrief,
} from '../../api/intentBuilder'

const { TextArea } = Input
const { Title, Paragraph, Text } = Typography

interface DisplayMessage {
  role: 'user' | 'assistant'
  content: string
}

export default function IntentBuilderPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // URL prefill 字段
  const prefill = searchParams.get('prefill') || ''
  const initialCodeType = searchParams.get('code_type') || 'assertion'
  const initialTemplateId = searchParams.get('template_id') || ''
  const missingCsv = searchParams.get('missing') || ''

  const [sessionId, setSessionId] = useState<string>('')
  const [codeType] = useState<string>(initialCodeType)
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  const [accumulatedIntent, setAccumulatedIntent] = useState('')
  const [ragCandidates, setRagCandidates] = useState<RAGCandidateBrief[]>([])
  const [suggestContribute, setSuggestContribute] = useState(false)
  const [inputText, setInputText] = useState('')
  const [loading, setLoading] = useState(false)
  const [firstTurnSent, setFirstTurnSent] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)

  // 进页面后，如果有 prefill 自动塞到输入框
  useEffect(() => {
    if (prefill && !firstTurnSent) {
      const firstMsg = missingCsv
        ? `${prefill}\n\n（系统提示：以下必填参数我还没明确：${missingCsv}）`
        : prefill
      setInputText(firstMsg)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = async () => {
    const text = inputText.trim()
    if (!text) {
      message.warning('请输入内容')
      return
    }
    setLoading(true)
    setMessages(prev => [...prev, { role: 'user', content: text }])
    setInputText('')
    setFirstTurnSent(true)
    try {
      const resp: IntentBuilderChatResponse = await intentBuilderApi.chat({
        session_id: sessionId,
        user_message: text,
        code_type: codeType,
      })
      setSessionId(resp.session_id)
      setMessages(prev => [...prev, { role: 'assistant', content: resp.assistant_message }])
      setAccumulatedIntent(resp.accumulated_intent)
      setRagCandidates(resp.rag_candidates)
      setSuggestContribute(resp.suggest_contribute)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err.response?.data?.detail || '对话引擎异常，请稍后重试')
      setMessages(prev => prev.slice(0, -1))
      setInputText(text)
    } finally {
      setLoading(false)
    }
  }

  const backToGenerate = () => {
    if (!accumulatedIntent) {
      message.warning('还没有可用的标准化意图，请继续对话')
      return
    }
    // P2-17：用 URL query 而非 location.state——刷新页面后 prefill 仍能从 URL 恢复
    const qs = new URLSearchParams({
      prefill: accumulatedIntent,
      code_type: codeType,
      source: 'intent_builder',
    })
    navigate(`/generate?${qs.toString()}`)
  }

  const goToContribute = () => {
    // P2-17：贡献入口也走 URL query，刷新可恢复
    const qs = new URLSearchParams({
      description: accumulatedIntent || prefill,
      code_type: codeType,
    })
    navigate(`/contribute/new?${qs.toString()}`)
  }

  return (
    <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 120px)', padding: 16 }}>
      <div style={{ flex: 2, display: 'flex', flexDirection: 'column' }}>
        <Card
          size="small"
          title={
            <Space>
              <Title level={5} style={{ margin: 0 }}>意图构建器</Title>
              <Tag color="blue">{codeType}</Tag>
              {initialTemplateId && <Tag color="purple">已识别：{initialTemplateId}</Tag>}
              {missingCsv && <Tag color="orange">需补充：{missingCsv}</Tag>}
            </Space>
          }
          style={{ flex: 1, display: 'flex', flexDirection: 'column' }}
          styles={{ body: { flex: 1, overflow: 'auto', padding: 12 } }}
        >
          {accumulatedIntent && (
            <Alert
              type="success"
              showIcon
              message="当前累计意图（点击「用这条意图回去生成」可带回 Generate 页）"
              description={<Text code>{accumulatedIntent}</Text>}
              style={{ marginBottom: 12 }}
            />
          )}
          {messages.length === 0 ? (
            <Empty description="还没开始对话——在下面输入你的验证需求，或编辑左上方预填的内容后点击发送" />
          ) : (
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              {messages.map((m, i) => (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start',
                  }}
                >
                  <div
                    style={{
                      maxWidth: '80%',
                      padding: '10px 14px',
                      borderRadius: 8,
                      background: m.role === 'user' ? '#e6f7ff' : '#f0f0f0',
                      whiteSpace: 'pre-wrap',
                    }}
                  >
                    <Text strong style={{ fontSize: 11, color: '#888', display: 'block', marginBottom: 4 }}>
                      {m.role === 'user' ? '你' : 'AI 助手'}
                    </Text>
                    {m.content}
                  </div>
                </div>
              ))}
              <div ref={chatEndRef} />
              {loading && <Spin size="small" />}
            </Space>
          )}
        </Card>

        <Card size="small" style={{ marginTop: 8 }} styles={{ body: { padding: 12 } }}>
          <Space.Compact style={{ width: '100%' }}>
            <TextArea
              rows={3}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="描述你想验证的场景，按 Ctrl+Enter 发送"
              onPressEnter={(e) => {
                if (e.ctrlKey || e.metaKey) {
                  e.preventDefault()
                  sendMessage()
                }
              }}
              disabled={loading}
            />
            <Button type="primary" icon={<SendOutlined />} onClick={sendMessage} loading={loading}>
              发送
            </Button>
          </Space.Compact>
          <Space style={{ marginTop: 8 }} wrap>
            <Button icon={<RollbackOutlined />} onClick={backToGenerate} disabled={!accumulatedIntent}>
              用这条意图回去生成
            </Button>
            {suggestContribute && (
              <Button danger icon={<PlusOutlined />} onClick={goToContribute}>
                贡献新模板
              </Button>
            )}
          </Space>
        </Card>
      </div>

      <div style={{ flex: 1, overflow: 'auto' }}>
        <Card size="small" title="当前可对齐的库内模板" styles={{ body: { padding: 8 } }}>
          {ragCandidates.length === 0 ? (
            <Paragraph type="secondary" style={{ fontSize: 12, padding: 8 }}>
              发送第一条消息后，系统会在这里展示库里最相近的 3 个模板。
            </Paragraph>
          ) : (
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              {ragCandidates.map((c, i) => (
                <Card
                  key={c.template_id}
                  type="inner"
                  size="small"
                  title={
                    <Space>
                      <Text strong>#{i + 1} {c.name}</Text>
                      <Tag color={c.score >= 0.7 ? 'green' : c.score >= 0.5 ? 'gold' : 'red'}>
                        {(c.score * 100).toFixed(0)}%
                      </Tag>
                    </Space>
                  }
                >
                  <Paragraph style={{ fontSize: 12, margin: 0 }}>{c.description}</Paragraph>
                  <Text code style={{ fontSize: 11 }}>{c.template_id}</Text>
                </Card>
              ))}
              {suggestContribute && (
                <Alert
                  type="warning"
                  message="候选都不太匹配"
                  description="多轮对话后库里仍没有合适的模板。考虑「贡献新模板」按钮把这个场景加进库里。"
                />
              )}
            </Space>
          )}
        </Card>
      </div>
    </div>
  )
}
