import type { DiscoveryFacets, DiscoveryFilters, DiscoveryItem, DiscoveryList } from '../discovery-types'
import type { AnalysisRun } from './analysis'
import type { PersonalList } from './discovery'
import { readRecord } from './browser-library'
import type { ICBriefing, ICDailyEdition } from '../briefing-types'

export interface ResearchTopic { id: string; track: string; name: string; focus: string; count: number }
export interface Exploration {
  screened_on: string; tracks: Record<string, string>; topics: ResearchTopic[]; items: DiscoveryItem[]; note: string
  counts: { total: number; ai_for_ic: number; ic_for_ai: number; both: number; general_ic: number; ai_candidates: number; unconfirmed: number; main: number; archive: number; excluded: number }
}
interface Snapshot {
  schema_version: 1; exported_at: string; items: (DiscoveryItem & { created_at?: string })[]
  facets: DiscoveryFacets; exploration: Omit<Exploration, 'items'>; reports: AnalysisRun[]
  ic_briefing?: Record<string, ICBriefing>
  daily_observations?: ICDailyEdition[]
  weekly_observations?: ICDailyEdition[]
}
let pending: Promise<Snapshot> | undefined

export async function loadSnapshot(signal?: AbortSignal): Promise<Snapshot> {
  if (!pending) {
    // One shared fetch; cancellation of one page must not cancel other readers.
    pending = fetch(`${import.meta.env.BASE_URL}data/snapshot.json`).then(async response => {
      if (!response.ok) throw new Error(`展示数据读取失败（${response.status}）`)
      const data = await response.json() as Snapshot
      if (data.schema_version !== 1 || !Array.isArray(data.items) || !Array.isArray(data.reports)) throw new Error('展示数据版本不兼容')
      return data
    }).catch(error => { pending = undefined; throw error })
  }
  const data = await pending
  if (signal?.aborted) throw new DOMException('已取消读取', 'AbortError')
  return data
}

function attachRecord(item: DiscoveryItem): DiscoveryItem { return { ...item, library: readRecord(item.id) } }
function searchText(item: DiscoveryItem): string {
  return [item.title, item.summary, item.abstract_text, item.source, item.journal, item.venue_name,
    item.doi, item.arxiv_id, ...(item.topics || []), ...(item.methods || []), ...(item.views || [])].join(' ').toLowerCase()
}
function page<T>(items: T[], limit: number, offset: number) {
  return { items: items.slice(offset, offset + limit), total: items.length, limit, offset }
}

export async function staticItems(filters: DiscoveryFilters, signal?: AbortSignal): Promise<DiscoveryList> {
  const data = await loadSnapshot(signal)
  if (filters.date_from && filters.date_to && filters.date_from > filters.date_to) throw new Error('起始日期不能晚于结束日期')
  const scope = filters.literature_scope || (filters.content_type === 'paper' ? 'main' : 'all')
  const newsScope = filters.news_scope || (filters.content_type === 'news' ? 'main' : 'all')
  const topic = data.exploration.topics.find(topic => topic.name === filters.topic)
  const dateOf = (item: DiscoveryItem) => (filters.date_basis === 'collected' ? item.collected_at : item.published_at)?.slice(0, 10) || ''
  const items = data.items.filter(item => {
    const analysis = item.ic_ai
    const date = dateOf(item)
    return (!filters.content_type || item.content_type === filters.content_type)
      && (scope === 'all' || item.content_type === 'paper' && analysis?.scope === scope)
      && (newsScope === 'all' || item.content_type === 'news' && (item.news_scope || 'main') === newsScope)
      && (!filters.publication_period || item.content_type === 'paper' && item.publication_timing?.kind === filters.publication_period)
      && (!filters.research_track || (filters.research_track === 'any_ai'
        ? analysis?.tracks.some(track => ['ai_for_ic', 'ic_for_ai'].includes(track))
        : analysis?.tracks.includes(filters.research_track)))
      && (!filters.topic || (topic ? analysis?.topic_ids.includes(topic.id) : item.topics.includes(filters.topic)))
      && (!filters.venue || (item.venue_name || item.journal) === filters.venue)
      && (!filters.publication_kind || item.venue_type === filters.publication_kind)
      && (!filters.origin || item.origin === filters.origin)
      && (!filters.q?.trim() || searchText(item).includes(filters.q.trim().toLowerCase()))
      && (!filters.date_from || !!date && date >= filters.date_from)
      && (!filters.date_to || !!date && date <= filters.date_to)
  }).sort((a, b) => dateOf(b).localeCompare(dateOf(a)) || (b.created_at || '').localeCompare(a.created_at || '') || a.id.localeCompare(b.id))
  const result = page(items, filters.limit || 20, filters.offset || 0)
  return { ...result, items: result.items.map(attachRecord) }
}

export async function staticItem(id: string, signal?: AbortSignal): Promise<DiscoveryItem> {
  const data = await loadSnapshot(signal)
  const item = data.items.find(item => item.id === id)
  if (!item) throw new Error('资料不存在于当前展示快照中')
  return attachRecord(item)
}

export async function staticLibrary(filters: Record<string, string | number>, signal?: AbortSignal): Promise<PersonalList> {
  const data = await loadSnapshot(signal)
  const saved = data.items.map(attachRecord).filter(item => item.library!.is_favorite)
  const statuses: Record<string, number> = {}
  saved.forEach(item => { const status = item.library!.reading_status; statuses[status] = (statuses[status] || 0) + 1 })
  const items = saved.filter(item => {
    const record = item.library!
    return (!filters.content_type || item.content_type === filters.content_type)
      && (!filters.reading_status || record.reading_status === filters.reading_status)
      && (!filters.topic || item.topics.includes(String(filters.topic)))
      && (!filters.personal_tag || record.personal_tags.includes(String(filters.personal_tag)))
      && (!String(filters.q || '').trim() || `${searchText(item)} ${record.notes} ${record.personal_tags.join(' ')}`.toLowerCase().includes(String(filters.q).trim().toLowerCase()))
  }).sort((a, b) => (b.library!.saved_at || '').localeCompare(a.library!.saved_at || '') || a.id.localeCompare(b.id))
  return { ...page(items, Number(filters.limit) || 20, Number(filters.offset) || 0), facets: {
    total: saved.length, status_counts: statuses,
    topics: [...new Set(saved.flatMap(item => item.topics))].sort(),
    personal_tags: [...new Set(saved.flatMap(item => item.library!.personal_tags))].sort(),
  } }
}

export async function staticExploration(signal?: AbortSignal): Promise<Exploration> {
  const data = await loadSnapshot(signal)
  return { ...data.exploration, items: data.items.filter(item => item.content_type === 'paper') }
}
