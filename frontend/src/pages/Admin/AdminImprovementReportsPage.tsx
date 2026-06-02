import { useEffect, useState } from 'react'
import { Card, Table, Tag, Button, Space, Select, Checkbox, Typography, message } from 'antd'
import { EyeOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  improvementReportsApi,
  ImprovementReportAdminListItem,
  ReportCategory,
  ReportStatus,
  STATUS_COLORS,
  STATUS_LABELS,
  CATEGORY_LABELS,
  REPORT_CATEGORY_OPTIONS,
} from '../../api/improvementReports'

const { Text } = Typography

export default function AdminImprovementReportsPage() {
  const navigate = useNavigate()
  const [list, setList] = useState<ImprovementReportAdminListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState<ReportStatus | undefined>(undefined)
  const [categoriesFilter, setCategoriesFilter] = useState<ReportCategory[]>([])
  // 服务端分页：page 1-based；page_size 与 Table.pagination 同步。
  // 后端未返 total，前端按返回行数推断是否还有下一页：
  // 拿到 < page_size 行 = 末页，停在当前 page；否则允许翻下一页。
  // 这是临时方案；正式分页需要后端补 total 字段。
  const [page, setPage] = useState<number>(1)
  const [pageSize, setPageSize] = useState<number>(20)
  const [hasMore, setHasMore] = useState<boolean>(false)

  const load = async () => {
    setLoading(true)
    try {
      const rows = await improvementReportsApi.adminList({
        status: statusFilter,
        categories: categoriesFilter.length ? categoriesFilter : undefined,
        page,
        page_size: pageSize,
      })
      setList(rows)
      setHasMore(rows.length === pageSize)
    } catch {
      message.error('加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, categoriesFilter.join(','), page, pageSize])

  // filter 变化时把 page 拉回 1，避免停留在不存在的尾页
  useEffect(() => {
    setPage(1)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, categoriesFilter.join(',')])

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 280, render: (v: string) => <Text code>{v}</Text> },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: ReportStatus) => <Tag color={STATUS_COLORS[v]}>{STATUS_LABELS[v]}</Tag>,
    },
    {
      title: '提交人',
      dataIndex: 'reporter_username',
      width: 140,
      render: (v: string | null) => v || '-',
    },
    {
      title: 'RAG 模板',
      dataIndex: 'rag_template_name',
      render: (v: string | null, r: ImprovementReportAdminListItem) =>
        v ? (
          <span>
            {v} <Text type="secondary" code>{r.rag_template_id}</Text>
          </span>
        ) : (
          <Text type="secondary">（模板已删除）</Text>
        ),
    },
    {
      title: '分类',
      dataIndex: 'categories',
      render: (v: string[] | null) => {
        if (!v || v.length === 0) return <Text type="secondary">-</Text>
        return (
          <Space wrap size={4}>
            {v.map((slug) => (
              <Tag key={slug}>{CATEGORY_LABELS[slug as ReportCategory] || slug}</Tag>
            ))}
          </Space>
        )
      },
    },
    {
      title: '提交时间',
      dataIndex: 'created_at',
      width: 180,
      render: (v: string) => new Date(v).toLocaleString(),
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: unknown, r: ImprovementReportAdminListItem) => (
        <Button
          type="link"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => navigate(`/admin/improvement-reports/${r.id}`)}
        >
          查看
        </Button>
      ),
    },
  ]

  return (
    <Card title="对比报告" loading={loading}>
      <Space style={{ marginBottom: 16 }} wrap>
        <span>状态：</span>
        <Select
          allowClear
          placeholder="全部"
          style={{ width: 140 }}
          value={statusFilter}
          onChange={(v) => setStatusFilter(v)}
          options={[
            { value: 'pending', label: STATUS_LABELS.pending },
            { value: 'in_review', label: STATUS_LABELS.in_review },
            { value: 'resolved', label: STATUS_LABELS.resolved },
          ]}
        />
        <span style={{ marginLeft: 16 }}>分类：</span>
        <Checkbox.Group
          options={REPORT_CATEGORY_OPTIONS.map((o) => ({ label: o.label, value: o.value }))}
          value={categoriesFilter}
          onChange={(v) => setCategoriesFilter(v as ReportCategory[])}
        />
      </Space>
      <Table
        dataSource={list}
        columns={columns}
        rowKey="id"
        size="small"
        // 后端不返 total；用当前页 + hasMore 估算，至少给一个 next-page 入口
        pagination={{
          current: page,
          pageSize,
          // total 仅用于 Pagination 内部计算总页数：当前页全满时给 page+1 页
          // 的占位（鼓励用户点 next），否则停在当前页
          total: (page - 1) * pageSize + list.length + (hasMore ? 1 : 0),
          showSizeChanger: true,
          pageSizeOptions: [20, 50, 100],
          onChange: (p, ps) => {
            setPage(p)
            if (ps !== pageSize) setPageSize(ps)
          },
        }}
      />
    </Card>
  )
}
