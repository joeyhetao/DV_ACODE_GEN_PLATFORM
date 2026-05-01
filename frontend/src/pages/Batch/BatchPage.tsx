import { useState, useEffect, useRef } from 'react'
import {
  Card, Upload, Button, Select, Progress, Table, Tag, Space,
  Steps, Alert, Statistic, Row, Col, message, Divider,
} from 'antd'
import { UploadOutlined, DownloadOutlined, EyeOutlined, SendOutlined } from '@ant-design/icons'
import { batchApi, BatchJob, PreflightRowResult } from '../../api/batch'
import { generateApi } from '../../api/generate'


export default function BatchPage() {
  const [codeTypes, setCodeTypes] = useState<{ id: string; display_name: string }[]>([])
  const [codeType, setCodeType] = useState<string>('')
  const [file, setFile] = useState<File | null>(null)
  const [step, setStep] = useState(0)
  const [preflightResults, setPreflightResults] = useState<PreflightRowResult[]>([])
  const [preflightLoading, setPreflight] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobStatus, setJobStatus] = useState<BatchJob | null>(null)
  const [uploading, setUploading] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollDelayRef = useRef(2000)

  useEffect(() => {
    generateApi.codeTypes().then(setCodeTypes).catch(() => {})
    return () => { if (pollRef.current) clearTimeout(pollRef.current) }
  }, [])

  const handlePreflight = async () => {
    if (!file || !codeType) return
    setPreflight(true)
    try {
      const res = await batchApi.preflight(file, codeType)
      setPreflightResults(res.results)
      setStep(1)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err?.response?.data?.detail || '预检失败')
    } finally {
      setPreflight(false)
    }
  }

  const handleUpload = async () => {
    if (!file || !codeType) return
    setUploading(true)
    try {
      const res = await batchApi.upload(file, codeType)
      setJobId(res.job_id)
      setStep(2)
      pollDelayRef.current = 2000
      schedulePoll(res.job_id)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err?.response?.data?.detail || '上传失败')
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

  const avgConfidence = preflightResults.length
    ? preflightResults.reduce((s, r) => s + r.estimated_confidence, 0) / preflightResults.length
    : 0

  const confidenceColumns = [
    { title: '行ID', dataIndex: 'row_id', width: 120 },
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
        <Space wrap>
          <Select
            placeholder="选择代码类型"
            value={codeType || undefined}
            onChange={setCodeType}
            style={{ width: 200 }}
          >
            {codeTypes.map((ct) => (
              <Select.Option key={ct.id} value={ct.id}>{ct.display_name}</Select.Option>
            ))}
          </Select>
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
            disabled={!file || !codeType}
          >
            预检分析
          </Button>
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={handleUpload}
            loading={uploading}
            disabled={!file || !codeType}
          >
            开始批量生成
          </Button>
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
