import { useState, useEffect, useRef } from 'react'
import {
  Card, Upload, Button, Progress, Table, Tag, Space,
  Steps, Alert, Statistic, Row, Col, message, Divider, Typography,
} from 'antd'
import { UploadOutlined, DownloadOutlined, EyeOutlined, SendOutlined } from '@ant-design/icons'
import { batchApi, BatchJob, PreflightRowResult } from '../../api/batch'


export default function BatchPage() {
  const [file, setFile] = useState<File | null>(null)
  const [step, setStep] = useState(0)
  const [preflightResults, setPreflightResults] = useState<PreflightRowResult[]>([])
  const [preflightLoading, setPreflight] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobStatus, setJobStatus] = useState<BatchJob | null>(null)
  const [uploading, setUploading] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [templateLoading, setTemplateLoading] = useState(false)
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollDelayRef = useRef(2000)

  useEffect(() => {
    return () => { if (pollRef.current) clearTimeout(pollRef.current) }
  }, [])

  const handlePreflight = async () => {
    if (!file) return
    setPreflight(true)
    try {
      const res = await batchApi.preflight(file)
      setPreflightResults(res.results)
      setStep(1)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string | { message?: string } } } }
      const detail = err?.response?.data?.detail
      const msg = typeof detail === 'string' ? detail : detail?.message
      message.error(msg || '预检失败')
    } finally {
      setPreflight(false)
    }
  }

  const handleUpload = async () => {
    if (!file) return
    setUploading(true)
    try {
      const res = await batchApi.upload(file)
      setJobId(res.job_id)
      setStep(2)
      pollDelayRef.current = 2000
      schedulePoll(res.job_id)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string | { message?: string } } } }
      const detail = err?.response?.data?.detail
      const msg = typeof detail === 'string' ? detail : detail?.message
      message.error(msg || '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const schedulePoll = (id: string) => {
    pollRef.current = setTimeout(async () => {
      try {
        const status = await batchApi.status(id)
        setJobStatus(status)
        if (!['done', 'failed'].includes(status.status)) {
          pollDelayRef.current = Math.min(pollDelayRef.current * 1.5, 30000)
          schedulePoll(id)
        }
      } catch {
        pollDelayRef.current = Math.min(pollDelayRef.current * 2, 30000)
        schedulePoll(id)
      }
    }, pollDelayRef.current)
  }

  const handleDownload = async () => {
    if (!jobId) return
    setDownloading(true)
    try {
      await batchApi.download(jobId)
    } catch {
      message.error('下载失败，请重试')
    } finally {
      setDownloading(false)
    }
  }

  const handleDownloadTemplate = async () => {
    setTemplateLoading(true)
    try {
      await batchApi.downloadTemplate()
    } catch {
      message.error('模板下载失败')
    } finally {
      setTemplateLoading(false)
    }
  }

  const avgConfidence = preflightResults.length
    ? preflightResults.reduce((s, r) => s + r.estimated_confidence, 0) / preflightResults.length
    : 0

  const confidenceColumns = [
    { title: '行ID', dataIndex: 'row_id', width: 120 },
    { title: '代码类型', dataIndex: 'code_type', width: 120 },
    {
      title: '预估置信度', dataIndex: 'estimated_confidence', width: 130,
      render: (v: number) => <Tag color={v >= 0.85 ? 'green' : v >= 0.7 ? 'orange' : 'red'}>{(v * 100).toFixed(1)}%</Tag>,
    },
    { title: '最佳匹配', dataIndex: 'top_match', render: (v: Record<string, unknown>) => v?.name as string || '—' },
  ]

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Steps current={step} items={[
        { title: '上传文件', description: '选择 Excel 文件' },
        { title: '预检分析', description: '查看置信度预估' },
        { title: '批量生成', description: '执行并下载结果' },
      ]} />

      <Card title="文件上传">
        <Space direction="vertical" size="small" style={{ width: '100%' }}>
          <Space wrap>
            <Button
              icon={<DownloadOutlined />}
              loading={templateLoading}
              onClick={handleDownloadTemplate}
            >
              下载 Excel 模板
            </Button>
            <Upload
              beforeUpload={(f) => { setFile(f); return false }}
              maxCount={1}
              accept=".xlsx,.xls"
              onRemove={() => setFile(null)}
            >
              <Button icon={<UploadOutlined />}>选择 Excel 文件</Button>
            </Upload>
            <Button
              icon={<EyeOutlined />}
              onClick={handlePreflight}
              loading={preflightLoading}
              disabled={!file}
            >
              预检分析
            </Button>
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleUpload}
              loading={uploading}
              disabled={!file}
            >
              开始批量生成
            </Button>
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            上传 Excel 后系统自动按 sheet 识别代码类型；模板含 SVA 需求 / Coverage 需求两 sheet，凡填了 A 列编号的 sheet 都会被处理。
          </Typography.Text>
        </Space>
      </Card>

      {preflightResults.length > 0 && (
        <Card title={`预检结果（共 ${preflightResults.length} 行）`}
          extra={<Statistic title="平均置信度" value={`${(avgConfidence * 100).toFixed(1)}%`} style={{ display: 'inline-block' }} />}
        >
          <Table
            dataSource={preflightResults}
            rowKey="row_id"
            columns={confidenceColumns}
            size="small"
            pagination={{ pageSize: 10 }}
          />
        </Card>
      )}

      {jobStatus && (
        <Card title="生成进度">
          <Row gutter={24}>
            <Col span={6}>
              <Statistic title="状态" value={jobStatus.status} valueStyle={{
                color: jobStatus.status === 'done' ? '#52c41a' : jobStatus.status === 'failed' ? '#f5222d' : '#1677ff'
              }} />
            </Col>
            <Col span={6}>
              <Statistic title="总行数" value={jobStatus.total_rows} />
            </Col>
            <Col span={6}>
              <Statistic title="已完成" value={jobStatus.completed_rows} />
            </Col>
            <Col span={6}>
              {jobStatus.status === 'done' && jobStatus.result_url && (
                <Button
                  type="primary"
                  icon={<DownloadOutlined />}
                  loading={downloading}
                  onClick={handleDownload}
                >
                  下载结果
                </Button>
              )}
            </Col>
          </Row>
          <Divider />
          <Progress
            percent={Math.round(jobStatus.progress * 100)}
            status={jobStatus.status === 'failed' ? 'exception' : jobStatus.status === 'done' ? 'success' : 'active'}
          />
          {jobStatus.error_message && (
            <Alert type="error" message={jobStatus.error_message} style={{ marginTop: 12 }} />
          )}
        </Card>
      )}
    </Space>
  )
}
