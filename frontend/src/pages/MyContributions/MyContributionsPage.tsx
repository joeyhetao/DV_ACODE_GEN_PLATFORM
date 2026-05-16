import { useState, useEffect } from 'react'
import {
  Card, Table, Tag, Button, Space, Modal, Form, Input, Select,
  Drawer, Descriptions, Typography, message, Alert,
} from 'antd'
import { PlusOutlined, EyeOutlined } from '@ant-design/icons'
import { useLocation, useSearchParams } from 'react-router-dom'
import { contributionsApi, ContributionListItem, Contribution } from '../../api/contributions'
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

export default function MyContributionsPage() {
  const location = useLocation()
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
  const [submitForm] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const [codeTypes, setCodeTypes] = useState<{ id: string; display_name: string }[]>([])
  const [parseError, setParseError] = useState<{ stage: string; reason: string } | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const res = await contributionsApi.my()
      setList(res)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    generateApi.codeTypes().then(setCodeTypes).catch(() => {})
  }, [])

  // v3.0：从 IntentBuilder 跳过来时，自动打开提交 Modal 并预填 description / code_type
  useEffect(() => {
    if (prefill.prefillDescription || prefill.prefillCodeType) {
      submitForm.setFieldsValue({
        description: prefill.prefillDescription || '',
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

  const handleSubmit = async () => {
    const values = await submitForm.validateFields()
    setSubmitting(true)
    setParseError(null)
    try {
      // v3.0：只提交 4 必填——keywords / parameter_defs / subcategory / protocol 全部由后端 LLM 反推
      await contributionsApi.submit({
        template_name: values.template_name,
        code_type: values.code_type,
        description: values.description,
        demo_code: values.demo_code,
      })
      message.success('提交成功，AI 已协助参数化，等待管理员审核')
      setSubmitVisible(false)
      submitForm.resetFields()
      load()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: { type?: string; stage?: string; reason?: string; message?: string } | string } } }
      const detail = err.response?.data?.detail
      if (detail && typeof detail === 'object' && detail.type === 'contribution_parse_failed') {
        setParseError({ stage: detail.stage || 'unknown', reason: detail.reason || '' })
        // 不关 Modal，让用户在 Modal 里看到错误并修改代码示例
      } else {
        message.error(typeof detail === 'string' ? detail : '提交失败')
      }
    } finally {
      setSubmitting(false)
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

      {/* v3.0 提交贡献——4 必填字段，AI 自动反推 parameters JSON */}
      <Modal
        title="提交模板贡献（AI 协助参数化）"
        open={submitVisible}
        onOk={handleSubmit}
        onCancel={() => { setSubmitVisible(false); setParseError(null) }}
        width={760}
        confirmLoading={submitting}
        okText="提交，由 AI 协助参数化"
        destroyOnClose
      >
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
                <Text type="secondary">请简化「代码示例」或完善「场景描述」后重新提交。</Text>
              </>
            }
            style={{ marginBottom: 16 }}
          />
        )}
        <Alert
          type="info"
          showIcon
          message="只需填 4 个字段，剩下的 AI 会自动反推"
          description="后端会从你的代码示例里识别可参数化位置（信号名、状态枚举、位宽常量等），自动改写为 Jinja2 占位符并生成 parameters JSON。审核员会再过一遍。"
          style={{ marginBottom: 16 }}
        />
        <Form form={submitForm} layout="vertical">
          <Form.Item name="template_name" label="模板名称" rules={[{ required: true, message: '必填' }]}>
            <Input placeholder="如：AXI 写通道地址稳定断言" />
          </Form.Item>
          <Form.Item name="code_type" label="代码类型" rules={[{ required: true, message: '必填' }]}>
            <Select placeholder="选择代码类型">
              {codeTypes.map((ct) => (
                <Select.Option key={ct.id} value={ct.id}>{ct.display_name}</Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item
            name="description"
            label="验证场景描述"
            rules={[{ required: true, message: '必填' }]}
            extra="用自然语言描述这个模板要解决什么问题；写得越具体，RAG 匹配率越高。"
          >
            <TextArea rows={3} placeholder="如：检测 AXI valid-ready 握手期间数据信号必须保持稳定" />
          </Form.Item>
          <Form.Item
            name="demo_code"
            label="代码示例"
            rules={[{ required: true, message: '必填' }]}
            extra="直接粘贴你设计里能跑的 SystemVerilog 代码，含真实信号名 / 状态枚举值 / 数字字面量。AI 会自动识别哪些是参数。"
          >
            <TextArea
              rows={12}
              style={{ fontFamily: 'monospace', fontSize: 13 }}
              placeholder={'module my_check (input logic clk, ...);\n  property p_handshake;\n    @(posedge clk) disable iff(!rst_n)\n    awvalid && !awready |-> $stable(awaddr);\n  endproperty\n  ...\nendmodule'}
            />
          </Form.Item>
        </Form>
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
}
