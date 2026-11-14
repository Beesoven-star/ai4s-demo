export type DiscoveryContentType = 'paper' | 'news'
export type DiscoveryOrigin = 'seed' | 'collected'
export type DiscoveryDateBasis = 'published' | 'collected'
export type ReadingStatus = 'unread' | 'reading' | 'read' | 'follow_up'
export interface ICAnalysis {
  scope?: string; scope_label?: string; reviewed_on?: string
  tracks: string[]; topic_ids: string[]; topics: string[]
  basis: string; status: string; note: string
  evidence: { topic_id: string; track: string; field: string; ai_signal: string; task_signal: string }[]
}
export interface PersonalRecord {
  is_favorite: boolean
  notes: string
  reading_status: ReadingStatus
  personal_tags: string[]
  saved_at: string | null
  updated_at: string | null
}

export interface DiscoveryItem {
  publication_timing?: {kind: string; label: string; as_of: string; recent_start: string; note: string}
  abstract_provenance?: {source: string; url: string}[]
  ic_ai?: ICAnalysis
  library?: PersonalRecord
  id: string
  content_type: DiscoveryContentType
  origin: DiscoveryOrigin
  sample_role?: string
  title: string
  source: string
  journal?: string | null
  venue_type?: 'journal' | 'conference' | 'preprint' | null
  venue_name?: string | null
  conference_year?: number | null
  track?: string | null
  url: string
  doi?: string | null
  arxiv_id?: string | null
  published_at: string | null
  publication_year?: number | null
  publication_month?: string | null
  news_genre?: string
  news_scope?: string
  news_scope_reason?: string
  publication_status?: string
  date_kind?: string
  collected_at: string
  summary: string
  summary_kind?: string
  abstract_text?: string | null
  topics: string[]
  methods: string[]
  views: string[]
  relevance?: string
  verification_note?: string
  verification_mode?: string
}

export interface DiscoveryList {
  items: DiscoveryItem[]
  total: number
  limit: number
  offset: number
}

export interface DiscoveryFilters {
  news_scope?: string
  literature_scope?: string
  publication_period?: string
  research_track?: string
  publication_kind?: 'journal' | 'conference' | 'preprint'
  q?: string
  content_type?: DiscoveryContentType
  topic?: string
  venue?: string
  date_from?: string
  date_to?: string
  date_basis?: DiscoveryDateBasis
  origin?: DiscoveryOrigin
  limit?: number
  offset?: number
}

export interface DiscoveryFacets {
  news_candidates?: number
  archived_news?: number
  main_papers?: number
  archive_papers?: number
  pending_papers?: number
  excluded_papers?: number
  literature_scopes?: Record<string,number>
  publication_audit?: {as_of: string; recent_start: string; counts: Record<string,number>; collection_days: Record<string,number>}
  domain?: string
  research_tracks?: Record<string,string>
  total: number
  papers: number
  news: number
  today?: string
  new_today?: number
  papers_today?: number
  news_today?: number
  seed: number
  collected: number
  topics: string[]
  venues: string[]
}

export interface DiscoveryRun {
  source_id: string
  source_name: string
  started_at: string
  finished_at: string
  status: 'success' | 'no_results' | 'failed'
  found: number
  inserted: number
  updated: number
  error?: string | null
  coverage_warning?: string | null
  selection?: {
    parsed: number
    date_matched: number
    matched: number
    rejected_date: number
    rejected_relevance: number
  }
  window_start?: string | null
  window_end?: string | null
}
