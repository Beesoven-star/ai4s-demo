import { IS_STATIC } from '../static-mode'
import { staticAnalysisRequest } from './static-analysis'

export interface AnalysisFilters {
  date_from: string; date_to: string; date_basis: 'published'|'collected'
  include_papers: boolean; include_news: boolean
  literature_scope: string; news_scope: string; research_track: string; topic: string; keyword: string
}
export interface AnalysisSource {
  ref: string; id: string; content_type: 'paper'|'news'; title: string; source: string; url: string
  doi?: string; arxiv_id?: string; published_at?: string; publication_month?: string; publication_year?: number
  collected_at?: string; venue_type?: string; venue?: string; excerpt: string; excerpt_truncated: boolean
  evidence_quality: string; tracks: string[]; topics: string[]; classification_basis: string
}
export interface AnalysisPreview {
  filters: AnalysisFilters; sources: AnalysisSource[]; fingerprint: string; total: number
  counts: Record<string,number>; excluded: Record<string,number>; max_sources: number
}
export interface AnalysisClaim {
  text: string; source_ids: string[]; evidence: {source_id: string; quote: string; evidence_id?: string|null}[]
}
export interface AnalysisReport {
  title: string; overview: AnalysisClaim
  trends: {title: string; observation: AnalysisClaim; interpretation: AnalysisClaim}[]
  connections: AnalysisClaim[]
  research_question: {question: AnalysisClaim; motivation: AnalysisClaim; approach: string[]; validation: string[]}
  limitations: string[]
}
export interface AnalysisRun {
  id: string; status: 'running'|'success'|'failed'; created_at: string; finished_at?: string
  filters: AnalysisFilters; matched_count: number; source_count: number; counts: Record<string,number>
  model: string; service_url: string; report?: AnalysisReport; sources?: AnalysisSource[]; error?: string
  retry_of?: string; elapsed_seconds?: number
  usage?: {prompt_tokens?: number; completion_tokens?: number; total_tokens?: number; reasoning_tokens?: number}
  generation_policy?: {max_tokens: number; timeout_seconds: number; reasoning_effort?: string}
  draft_report?: AnalysisReport
  error_code?: string
  citation_issues?: {path: string; source_id: string; evidence_id?: string|null; quote: string; reason: string; source_title: string}[]
  citation_repairs?: {path: string; source_id: string; reason: string}[]
  citation_policy?: string
}
export interface ModelConnection {model: string; base_url: string; key_configured: boolean; key_source?: string}
export interface AnalysisOptions {today: string; max_sources: number; topics: {id: string; track: string; name: string}[]}

export async function analysisRequest<T>(path: string, body?: unknown, method?: string): Promise<T> {
  if (IS_STATIC) return staticAnalysisRequest<T>(path, body, method)
  const response = await fetch('/api/analysis'+path, {
    method: method || (body === undefined ? 'GET' : 'POST'),
    headers: body === undefined ? undefined : {'Content-Type':'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = data.detail
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map(entry => entry.msg || '参数无效').join('；') : `请求失败（${response.status}）`)
  }
  return data as T
}
