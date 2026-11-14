import type { AnalysisFilters, AnalysisOptions, AnalysisPreview, AnalysisSource } from './analysis'
import type { DiscoveryItem } from '../discovery-types'
import { loadSnapshot } from './static-data'

const MAX_SOURCES = 80
function validDay(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const day = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(day.getTime()) && day.toISOString().slice(0, 10) === value
}
function plain(value: string | null | undefined): string { return (value || '').replace(/\s+/g, ' ').trim() }

function toSource(item: DiscoveryItem): AnalysisSource {
  const paper = item.content_type === 'paper'
  const analysis = item.analysis_classification || item.ic_ai
  let text = plain(item.abstract_text)
  let quality = paper ? 'source_abstract' : 'source_brief'
  if (!text && ['source', 'human'].includes(item.summary_kind || '')) {
    text = plain(item.summary)
    if (item.summary_kind === 'human') quality = 'human_summary'
  }
  return {
    ref: '', id: item.id, content_type: item.content_type, title: item.title, source: item.source, url: item.url,
    doi: item.doi || undefined, arxiv_id: item.arxiv_id || undefined, published_at: item.published_at || undefined,
    publication_month: item.publication_month || undefined, publication_year: item.publication_year || undefined,
    collected_at: item.collected_at, venue_type: item.venue_type || undefined, venue: item.venue_name || item.journal || undefined,
    excerpt: text.slice(0, 4000), excerpt_truncated: text.length > 4000, evidence_quality: text ? quality : 'title_only',
    tracks: analysis?.tracks || [], topics: analysis?.topics || [],
    classification_basis: paper && analysis?.reviewed_on ? 'reviewed' : 'title_brief_rules',
  }
}

export async function previewStaticAnalysis(filters: AnalysisFilters): Promise<AnalysisPreview> {
  const data = await loadSnapshot()
  if (!validDay(filters.date_from) || !validDay(filters.date_to) || filters.date_from > filters.date_to
    || filters.date_to > data.facets.today!) throw new Error('日期范围需有效且不晚于展示数据截至日期')
  if (Date.parse(filters.date_to) - Date.parse(filters.date_from) > 3660 * 86400000) throw new Error('单次筛选范围最多十年')
  if (!filters.include_papers && !filters.include_news) throw new Error('请至少选择文献或新闻')
  const topic = data.exploration.topics.find(topic => topic.id === filters.topic)
  if (filters.topic && !topic) throw new Error('研究专题无效')
  if (topic && filters.research_track && (filters.research_track === 'any_ai' ? topic.track === 'general_ic' : topic.track !== filters.research_track)) {
    throw new Error('专题与研究主线不一致')
  }
  let incomplete = 0
  const sources = data.items.filter(item => {
    const paper = item.content_type === 'paper'
    if (!(paper ? filters.include_papers : filters.include_news)) return false
    const analysis = item.analysis_classification || item.ic_ai
    const scope = paper ? analysis?.scope : item.news_scope || 'main'
    const wanted = paper ? filters.literature_scope : filters.news_scope
    if (wanted !== 'all' && scope !== wanted || scope === 'excluded' || scope === 'pending') return false
    const body = [item.title, item.abstract_text, item.summary, item.journal, item.venue_name].join(' ').toLowerCase()
    if (!body.includes(filters.keyword.trim().toLowerCase())) return false
    const tracks = analysis?.tracks || []
    if (filters.research_track === 'any_ai' ? !tracks.some(track => ['ai_for_ic', 'ic_for_ai'].includes(track))
      : !!filters.research_track && !tracks.includes(filters.research_track)) return false
    if (filters.topic && !analysis?.topic_ids.includes(filters.topic)) return false
    const date = (filters.date_basis === 'published' ? item.published_at : item.collected_at?.slice(0, 10)) || ''
    if (!validDay(date)) { incomplete++; return false }
    return date >= filters.date_from && date <= filters.date_to
  }).map(toSource).sort((a, b) => {
    const left = a.published_at || '', right = b.published_at || ''
    return left !== right ? left < right ? 1 : -1 : a.id < b.id ? 1 : a.id > b.id ? -1 : 0
  })
  const counts: Record<string, number> = {}
  sources.forEach((source, index) => { source.ref = `S${String(index + 1).padStart(3, '0')}`; counts[source.content_type] = (counts[source.content_type] || 0) + 1 })
  // No server generation token is issued by the static preview.
  return { filters: { ...filters }, sources, fingerprint: '', total: sources.length, counts,
    excluded: incomplete ? { incomplete_publication_date: incomplete } : {}, max_sources: MAX_SOURCES }
}

export async function staticAnalysisRequest<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const verb = method || (body === undefined ? 'GET' : 'POST')
  const data = await loadSnapshot()
  if (path === '/options' && verb === 'GET') {
    return { today: data.facets.today, max_sources: MAX_SOURCES, topics: data.exploration.topics } as AnalysisOptions as T
  }
  if (path === '/preview' && verb === 'POST') return previewStaticAnalysis(body as AnalysisFilters) as Promise<T>
  if (path === '/runs' && verb === 'GET') return data.reports as T
  const match = path.match(/^\/runs\/([^/]+)$/)
  if (match && verb === 'GET') {
    const run = data.reports.find(run => run.id === decodeURIComponent(match[1]))
    if (!run) throw new Error('当前发布版本中没有这份分析报告')
    return run as T
  }
  throw new Error('静态展示支持筛选材料和查看历史报告；生成新报告请使用本地完整版。')
}
