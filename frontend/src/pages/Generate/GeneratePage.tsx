import { useState, useEffect } from 'react'
import {
  Card, Form, Input, Select, Button, Row, Col, Space, Tag,
  Statistic, Divider, Typography, Table, Collapse, message,
} from 'antd'
import { ThunderboltOutlined, CopyOutlined, SendOutlined, PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import Editor from '@monaco-editor/react'
import { generateApi, GenerateResponse, SignalInfo } from '../../api/generate'

const { TextArea } = Input
const { Text } = Typography

type SignalRow = SignalInfo & { _key: string }

let _signalCounter = 0
const newSignalKey = () => `sig_${++_signalCounter}`

export default function GeneratePage() {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<GenerateResponse | null>(null)
  const [codeTypes, setCodeTypes] = useState<{ id: string; display_name: string }[]>([])
  const [signals, setSignals] = useState<SignalRow[]>([])

  useEffect(() => {
    generateApi.codeTypes().then(setCodeTypes).catch(() => {})
  }, [])

  const handleGenerate = async (values: Record<string, unknown>) => {
    setLoading(true)
    try {
      const res = await generateApi.generate({
        text: values.text as string,
        code_type: values.code_type as string,
        protocol: values.protocol as string | undefined,
        clk: (values.clk as string) || 'clk',
        rst: (values.rst as string) || 'rst_n',
        rst_polarity: (values.rst_polarity as string) || '低有效',
        signals: signals.map(({ _key: _, ...s }) => s),
      })
      setResult(res)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err.response?.data?.detail || '生成失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  const copyCode = () => {
    if (result?.code) {
      navigator.clipboard.writeText(result.code)
      message.success('已复制到剪贴板')
    }
  }

  const addSignal = () => setSignals((prev) => [...prev, { name: '', width: 1, role: 'other', _key: newSignalKey() }])
  const removeSignal = (key: string) => setSignals((prev) => prev.filter((s) => s._key !== key))
  const updateSignal = (key: string, field: keyof SignalInfo, value: string | number) => {
    setSignals((prev) => prev.map((s) => s._key === key ? { ...s, [field]: value } : s))
  }

  return (
    <Row gutter={24}>
      {/* Left: input panel */}
      <Col span={10}>
        <Card title={<><ThunderboltOutlined /> 意图描述</>}>
          <Form form={form} layout="vertical" onFinish={handleGenerate}>
            <Form.Item name="text" label="功能描述" rules={[{ required: true, message: '请输入功能描述' }]}>
              <TextArea rows={5} placeholder="描述你想生成的验证代码功能，例如：当 awvalid 有效且 awready 未响应时，awaddr 必须保持稳定" />
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

            <Divider orientation="left" plain>信号列表</Divider>
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
              <Button type="primary" htmlType="submit" loading={loading} icon={<SendOutlined />} block size="large">
                生成代码
              </Button>
            </Form.Item>
          </Form>
        </Card>
      </Col>

      {/* Right: result panel */}
      <Col span={14}>
        {result ? (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Card size="small">
              <Row gutter={16}>
                <Col span={6}>
                  <Statistic title="置信度" value={`${(result.confidence * 100).toFixed(1)}%`} valueStyle={{ color: result.confidence >= 0.85 ? '#52c41a' : '#fa8c16' }} />
                </Col>
                <Col span={6}>
                  <Statistic title="命中缓存" value={result.cache_hit ? '是' : '否'} />
                </Col>
                <Col span={12}>
                  <Text type="secondary">模板: </Text>
                  <Text code>{result.template_id}</Text>
                  {result.cache_hit && <Tag color="green" style={{ marginLeft: 8 }}>缓存命中</Tag>}
                  {result.intent_cache_hit && <Tag color="blue" style={{ marginLeft: 4 }}>意图缓存</Tag>}
                </Col>
              </Row>
            </Card>

            <Card
              title="生成代码"
              extra={<Button icon={<CopyOutlined />} onClick={copyCode}>复制</Button>}
            >
              <div className="code-editor-wrap">
                <Editor
                  height="420px"
                  language="systemverilog"
                  value={result.code}
                  options={{ readOnly: true, minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false }}
                  theme="vs"
                />
              </div>
            </Card>

            {result.rag_candidates.length > 0 && (
              <Collapse size="small" items={[{
                key: '1',
                label: `RAG 候选模板 (Top ${result.rag_candidates.length})`,
                children: (
                  <Table
                    dataSource={result.rag_candidates}
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
        ) : (
          <Card style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ textAlign: 'center', color: '#bbb', padding: '80px 0' }}>
              <ThunderboltOutlined style={{ fontSize: 48 }} />
              <div style={{ marginTop: 16 }}>输入意图描述，点击「生成代码」</div>
            </div>
          </Card>
        )}
      </Col>
    </Row>
  )
}
