import { useState, useEffect } from 'react'
import { Card, Select, Form, Input, Button, Space, Typography, Alert, Row, Col, Divider, message } from 'antd'
import { CopyOutlined, SendOutlined } from '@ant-design/icons'
import { intentBuilderApi, Scenario } from '../../api/intentBuilder'
import { generateApi } from '../../api/generate'
import { useNavigate } from 'react-router-dom'

const { Text, Title } = Typography

export default function IntentBuilderPage() {
  const navigate = useNavigate()
  const [codeType, setCodeType] = useState('assertion')
  const [codeTypes, setCodeTypes] = useState<{ id: string; display_name: string }[]>([])
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [selectedScenario, setSelectedScenario] = useState<Scenario | null>(null)
  const [paramForm] = Form.useForm()
  const [builtIntent, setBuiltIntent] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    generateApi.codeTypes().then(setCodeTypes).catch(() => {})
  }, [])

  useEffect(() => {
    if (codeType) {
      intentBuilderApi.scenarios(codeType).then((r) => {
        setScenarios(r.scenarios)
        setSelectedScenario(null)
        setBuiltIntent('')
        paramForm.resetFields()
      }).catch(() => {})
    }
  }, [codeType, paramForm])

  const handleBuild = async (values: Record<string, string>) => {
    if (!selectedScenario) return
    setLoading(true)
    try {
      const res = await intentBuilderApi.build(codeType, selectedScenario.id, values)
      setBuiltIntent(res.intent_text)
    } catch {
      message.error('构建失败')
    } finally {
      setLoading(false)
    }
  }

  const copyIntent = () => {
    navigator.clipboard.writeText(builtIntent)
    message.success('已复制')
  }

  const goGenerate = () => {
    navigate('/generate', { state: { prefillText: builtIntent, prefillCodeType: codeType } })
  }

  return (
    <Row gutter={24}>
      <Col span={10}>
        <Card title="场景选择">
          <Space direction="vertical" style={{ width: '100%' }}>
            <Select value={codeType} onChange={setCodeType} style={{ width: '100%' }}>
              {codeTypes.map((ct) => (
                <Select.Option key={ct.id} value={ct.id}>{ct.display_name}</Select.Option>
              ))}
            </Select>

            <Select
              placeholder="选择验证场景"
              style={{ width: '100%' }}
              value={selectedScenario?.id}
              onChange={(id) => {
                const s = scenarios.find((sc) => sc.id === id)
                setSelectedScenario(s || null)
                paramForm.resetFields()
                setBuiltIntent('')
              }}
            >
              {scenarios.map((s) => (
                <Select.Option key={s.id} value={s.id}>
                  <div>
                    <div>{s.name}</div>
                    <Text type="secondary" style={{ fontSize: 12 }}>{s.description}</Text>
                  </div>
                </Select.Option>
              ))}
            </Select>

            {selectedScenario && (
              <>
                <Divider orientation="left" plain>填写参数</Divider>
                <Form form={paramForm} layout="vertical" onFinish={handleBuild}>
                  {selectedScenario.params.map((p) => (
                    <Form.Item
                      key={p.name}
                      name={p.name}
                      label={p.description || p.name}
                      rules={p.required ? [{ required: true, message: `请填写 ${p.name}` }] : []}
                    >
                      <Input placeholder={p.name} />
                    </Form.Item>
                  ))}
                  <Form.Item>
                    <Button type="primary" htmlType="submit" loading={loading} icon={<SendOutlined />} block>
                      构建意图
                    </Button>
                  </Form.Item>
                </Form>
              </>
            )}
          </Space>
        </Card>
      </Col>

      <Col span={14}>
        {builtIntent ? (
          <Card
            title="生成的意图描述"
            extra={
              <Space>
                <Button icon={<CopyOutlined />} onClick={copyIntent}>复制</Button>
                <Button type="primary" onClick={goGenerate}>去生成代码 →</Button>
              </Space>
            }
          >
            <Alert
              type="success"
              description={
                <Text style={{ fontSize: 15, lineHeight: '1.8' }}>{builtIntent}</Text>
              }
              style={{ marginBottom: 16 }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              场景: {selectedScenario?.name} · 代码类型: {codeType}
            </Text>
          </Card>
        ) : (
          <Card style={{ height: '100%' }}>
            <div style={{ textAlign: 'center', color: '#bbb', padding: '80px 0' }}>
              <div style={{ fontSize: 48 }}>💡</div>
              <div style={{ marginTop: 16 }}>选择场景并填写参数，系统将自动构建标准意图描述</div>
            </div>
          </Card>
        )}
      </Col>
    </Row>
  )
}
