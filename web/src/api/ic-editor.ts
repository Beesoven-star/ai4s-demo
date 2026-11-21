import type { TopicEvaluation } from '../briefing-types'
import { IS_STATIC } from '../static-mode'
import { loadSnapshot } from './static-data'
import { snapshotArchive, type ObservationArchive } from './observation-archive'

export interface AutomaticRun {
  id: string; date: string; status: 'queued' | 'running' | 'published' | 'empty' | 'unchanged' | 'failed'
  error?: string | null; publications?: string[]; prompt_version: string; attempts: number
  usage?: { total_tokens?: number }; elapsed_seconds?: number
}

export interface TechnologyTopic {
  id: string; name: string; overview: string; question: string; follow_up: string
  seeded: boolean; established: boolean; category_id: string
  status: 'active' | 'history' | 'merged'; merged_into?: string; scope_reason?: string; latest_progress: string | null; reviewed_through: string | null
}

export interface TechnologyTopicIndexEntry extends TechnologyTopic {
  event_count: number
  evaluation_status?: 'ranked' | 'partial'
  latest_event: { title: string; summary: string; date: string; sources: string[] } | null
}

interface TopicSource {
  id: string; title: string; source: string; url: string
  published_at: string; content_type: 'news' | 'paper'; news_genre?: string
  reading_basis?: string
}

export interface TechnologyTopicDetail extends TechnologyTopic {
  evaluation?: TopicEvaluation
  events: { id: string; title: string; summary: string; boundary?: string; date: string; sources: TopicSource[] }[]
}

interface TopicRun {
  id: string; date: string; status: 'queued' | 'running' | 'complete' | 'unchanged' | 'empty' | 'failed'
  changes?: Pick<TechnologyTopic, 'id' | 'name' | 'status'>[]; error?: string
}

interface TechnologyTopics {
  topics: TechnologyTopicIndexEntry[]; runs: TopicRun[]; cool_days: number; as_of?: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/ic-editor${path}`, { cache: 'no-store', ...init })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : `请求失败（${response.status}）`)
  return result
}

interface EvaluationSettings {
  focus: string; max_length: number; rank_rule: string; rubric: { label: string; criteria: string }[]
}

export function getEvaluationSettings() {
  return request<EvaluationSettings>('/evaluation-settings')
}

export function saveEvaluationSettings(focus: string) {
  return request<EvaluationSettings>('/evaluation-settings', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ focus }),
  })
}

export async function getTechnologyTopics(signal?: AbortSignal): Promise<TechnologyTopics> {
  if (IS_STATIC) {
    const snapshot = await loadSnapshot(signal)
    const index = snapshot.ic_topics
    return { topics: index?.topics || [], cool_days: index?.cool_days || 30, runs: [], as_of: snapshot.facets.today }
  }
  return request<TechnologyTopics>('/topics', { signal })
}

export async function getTechnologyTopic(id: string, signal?: AbortSignal): Promise<TechnologyTopicDetail> {
  if (IS_STATIC) {
    const details = (await loadSnapshot(signal)).ic_topics?.details
    if (!details || !Object.prototype.hasOwnProperty.call(details, id)) throw new Error('此专题未收录于本期展示')
    return details[id]!
  }
  return request<TechnologyTopicDetail>(`/topics/${encodeURIComponent(id)}`, { signal })
}

export function getObservationAutomation() {
  return request<{ prompt: string; version: string; runs: AutomaticRun[] }>('/automation')
}

export function saveObservationPrompt(prompt: string) {
  return request<{ prompt: string; version: string }>('/automation/prompt', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt }),
  })
}

export type ReadingPromptKind = 'paper' | 'news'
interface ReadingPrompt {
  prompt: string
  default_prompt: string
  request_footer: string
}

export function getReadingPrompts() {
  return request<{ prompts: Record<ReadingPromptKind, ReadingPrompt>; system_prompt: string; max_length: number }>('/reading-prompts')
}

export function saveReadingPrompt(kind: ReadingPromptKind, prompt: string | null) {
  return request<ReadingPrompt>(`/reading-prompts/${kind}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt }),
  })
}

export function replayObservation(day: string) {
  return request<{ id: string }>('/automation/replay', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ day }),
  })
}

export async function getPublishedWeekly(day?: string, version?: string, signal?: AbortSignal): Promise<ObservationArchive> {
  if (IS_STATIC) {
    const snapshot = await loadSnapshot(signal)
    const original = snapshot.ic_briefing?.['7']
    return snapshotArchive(snapshot.weekly_observations || [], { day, version, original: original && {
      id: 'original', date: original.window.date_to, date_from: original.window.date_from,
      title: original.weekly_story?.question || '本周技术观察',
    } })
  }
  const query = new URLSearchParams()
  if (day) query.set('day', day)
  if (version) query.set('version', version)
  return request<ObservationArchive>(`/weekly?${query}`, { signal })
}
