import type {
  DiscoveryFacets,
  DiscoveryFilters,
  DiscoveryItem,
  DiscoveryList,
  DiscoveryRun,
} from '../discovery-types'
import { IS_STATIC } from '../static-mode'
import { staticItems, staticItem, staticLibrary, loadSnapshot } from './static-data'
import { writeRecord } from './browser-library'

const BASE = '/api/discovery'
export const READING_LABELS = { unread: '待阅读', reading: '阅读中', read: '已读', follow_up: '重点跟进' }

export async function updatePersonalRecord(id: string, changes: Partial<import('../discovery-types').PersonalRecord>): Promise<import('../discovery-types').PersonalRecord> {
  if (IS_STATIC) {
    await staticItem(id)
    return writeRecord(id, changes)
  }
  const response = await fetch(`${BASE}/items/${encodeURIComponent(id)}/library`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : `保存失败（${response.status}）`)
  }
  return response.json()
}

export interface PersonalList extends DiscoveryList {
  facets: { topics: string[]; personal_tags: string[]; status_counts: Record<string, number>; total: number }
}
export function listPersonalLibrary(filters: Record<string, string | number>, signal?: AbortSignal): Promise<PersonalList> {
  if (IS_STATIC) return staticLibrary(filters, signal)
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) if (value !== '') params.set(key, String(value))
  return request<PersonalList>(`/library?${params}`, signal)
}

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { signal })
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const body: { detail?: unknown } = await response.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) {
        message = body.detail
          .map((entry: unknown) => {
            if (entry && typeof entry === 'object' && 'msg' in entry) return String(entry.msg)
            return '查询参数不正确'
          })
          .join('；')
      }
    } catch {
      // The HTTP status still gives a useful error if the response is not JSON.
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export function listDiscoveryItems(filters: DiscoveryFilters, signal?: AbortSignal): Promise<DiscoveryList> {
  if (IS_STATIC) return staticItems(filters, signal)
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '') query.set(key, String(value))
  }
  return request<DiscoveryList>(`/items?${query}`, signal)
}

export function getDiscoveryItem(id: string, signal?: AbortSignal): Promise<DiscoveryItem> {
  if (IS_STATIC) return staticItem(id, signal)
  return request<DiscoveryItem>(`/items/${encodeURIComponent(id)}`, signal)
}

export function getDiscoveryFacets(signal?: AbortSignal): Promise<DiscoveryFacets> {
  if (IS_STATIC) return loadSnapshot(signal).then(data => data.facets)
  return request<DiscoveryFacets>('/facets', signal)
}

export function listDiscoveryRuns(signal?: AbortSignal): Promise<DiscoveryRun[]> {
  if (IS_STATIC) return Promise.resolve([])
  return request<DiscoveryRun[]>('/runs?limit=10', signal)
}

export function safeExternalUrl(value: string | null | undefined): string | undefined {
  try {
    const parsed = new URL(value || '')
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : undefined
  } catch {
    return undefined
  }
}

export function newsGenreLabel(value?: string | null): string {
  if (value === '来源性质待确认') return '来源类型未确认'
  return (value || '').replace(/\s*[（(]\s*待核验\s*[）)]\s*$/, '').trim()
}

export function readingBasisLabel(value?: string, contentType?: 'paper' | 'news'): string {
  const labels: Record<string, string> = {
    original: '公开原文摘录', original_summary: '原文核对简述', metadata: contentType === 'paper' ? '论文题录' : '页面公开信息',
    abstract: '作者摘要', abstract_excerpt: '作者摘要摘录', excerpt: '来源简介', bibliography: '论文题录',
    listing: '官方检索摘要或新闻列表', headline: '标题与来源链接',
    stored_abstract: '已收录摘要或简介', stored_summary: '当时收录的简介', material: '已收录的资料摘录',
  }
  return value ? labels[value] || '' : ''
}

export function publicationLabel(item: DiscoveryItem): string {
  if (item.published_at) return item.published_at.slice(0, 10)
  if (item.publication_month) return `${item.publication_month}（仅月份）`
  if (item.publication_year) return `${item.publication_year}（仅年份）`
  return '发布日期未提供'
}

export function venueLabel(item: DiscoveryItem): string {
  return item.venue_name?.trim() || item.journal?.trim() || ''
}

export function venueKindLabel(item: DiscoveryItem): string {
  if (item.venue_type === 'conference') return '会议'
  if (item.venue_type === 'journal') return '期刊'
  if (item.venue_type === 'preprint') return '预印本'
  return '期刊/会议'
}

export function dateKindLabel(value?: string): string {
  if (value?.startsWith('crossref_') && value.endsWith('_month')) return '期刊发表月份'
  const labels: Record<string, string> = {
    'crossref_published-online': '在线发表',
    'crossref_published-print': '印刷出版',
    crossref_published: '来源发表',
    crossref_issued: '来源发行',
    publisher_online: '在线发表',
    publisher_online_accepted: '接受稿在线发表',
    publisher_published: '出版社发表',
    journal_publication: '期刊发表',
    arxiv_first_submission: '预印本首次提交',
    blog_posted_on: '文章发布',
    year_only: '仅有发表年份',
    first_publication: '来源首次发表',
    news_published: '新闻发布日期',
  }
  return labels[value || ''] || '来源发布日期'
}

export function localTimeLabel(value: string | null | undefined): string {
  if (!value) return '未提供'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date)
}

export function summaryKindLabel(value?: string): string {
  if (value === 'human') return '人工简述'
  if (value === 'source') return '摘要预览'
  return '条目摘要'
}
