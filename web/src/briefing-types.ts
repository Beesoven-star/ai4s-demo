export interface BriefingClaim { text: string; source_ids: string[] }
export interface BriefingSource {
  id: string; content_type: 'paper' | 'news'; title: string; source: string; url: string
  published_at: string | null; publication_month: string | null; venue_type: string | null
  news_genre: string | null; excerpt: string; evidence_kind: string; organization: string
  attention_eligible: boolean; attention_note: string
  author?: string
  reading_takeaway?: string
}
export interface BriefingEvent {
  id: string; title: string; technology_ids: string[]; source_ids: string[]; window_source_ids: string[]
  tracked_topic_ids?: string[]
  kind: string; grouping_note: string; occurred_at: string | null; date_basis: string
  attention_rank: number | null
  attention: { source_ids: string[]; source_count: number; latest_reported_at: string | null }
}
export interface WeeklyHighlight {
  event_id: string
  reading_question?: string
  what_happened: string
  why_it_matters: string
  evidence_stage: string
  watch_next: string
}
export interface Technology {
  id: string; name: string; track: string; topic_ids: string[]; tagline: string
  overview: BriefingClaim; assessment: BriefingClaim; limitations: BriefingClaim; watch_next: BriefingClaim
  scores: (BriefingClaim & { label: string; value: number })[]; paper_ids: string[]
  maturity: string; evidence_status: string; review_status: 'provisional' | 'reviewed'
  importance_score: number; importance_rank: number; attention_rank: number | null
  attention: { source_count: number; organizations: string[]; event_count: number; covered_days: number
    news_count: number; other_source_count: number; source_ids: string[]; event_ids: string[] }
}
export interface EvaluationPoint {
  text: string
  references: { source_id: string; excerpt_index: number; quote: string }[]
}

export interface TopicEvaluation {
  topic_id: string; stage: string; evidence_through: string; evaluated_at: string; total: number | null
  finding: EvaluationPoint; limits: EvaluationPoint
  dimensions: (EvaluationPoint & { id: string; label: string; score: number | null })[]
  sources: Record<string, { id: string; title: string; source: string; url: string; date: string; basis: string; genre: string }>
}

export interface ImportanceEntry {
  id: string; name: string; score: number; rank: number; caption: string; automatic: boolean
}

export interface ICBriefing {
  schema_version: number; edition: string; prepared_on: string; data_through: string; title: string
  coverage: { library_papers: number; library_news: number; selected_news: number; selected_papers: number }
  backfill?: { date_from: string; date_to: string; reviewed_in_window: number; counted_in_window: number }
  window: { days: number; date_from: string; date_to: string }
  attention_label: string; attention_method: string; importance_method: string; limitations: string[]
  technologies: Technology[]; events: BriefingEvent[]; sources: Record<string, BriefingSource>
  weekly_story?: { question: string; overview: string; research_question: string }
  weekly_highlights?: WeeklyHighlight[]
  attention_order: string[]; importance_order: string[]
  event_attention_order: string[]; event_attention_method: string
  evaluations?: Record<string, TopicEvaluation>; importance_entries?: ImportanceEntry[]
  topic_catalog?: ICTopicCatalog
}

export interface ICClassificationLabel { id: string; name: string }
export interface ICTopicLabel extends ICClassificationLabel { status: 'candidate' | 'active' | 'paused' | 'merged' }
export interface ICTopicCatalog {
  version: string
  categories: ICClassificationLabel[]
  topics: (ICTopicLabel & { category_ids: string[]; reason?: string; source_ids?: string[]; merged_into?: string })[]
}
export interface ICObservationClassification {
  catalog_version: string
  categories: ICClassificationLabel[]
  topics: ICTopicLabel[]
  basis: 'editorial' | 'rule' | 'pending'
}
export interface ICDailyEdition {
  id?: string
  date_from?: string
  coverage_through?: string
  published_at?: string
  date: string
  title: string
  intro: string
  prepared_on: string
  catalog_version: string
  automation?: {
    prompt_version: string; generated_at: string; collection_partial: boolean; material_change?: string
    topic_suggestions: { name: string; sources: { title: string; source: string; url: string; published_at: string }[] }[]
  }
  entries: {
    title: string
    summary: string
    boundary?: string
    source: ObservationCitation
    sources?: ObservationCitation[]
    classification: ICObservationClassification
  }[]
}

export interface ObservationCitation {
  id: string; source: string; url: string; content_type: 'paper' | 'news'; news_genre?: string | null
  title?: string; published_at?: string
  evidence_status?: 'original' | 'original_summary' | 'metadata' | 'abstract' | 'abstract_excerpt' | 'stored_abstract' | 'bibliography' | 'listing' | 'excerpt' | 'headline'
  evidence_note?: string
}
