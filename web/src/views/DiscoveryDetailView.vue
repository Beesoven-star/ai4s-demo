<script setup lang="ts">
import { IS_STATIC } from '../static-mode'
import ICRelationPanel from '../components/ICRelationPanel.vue'
import PublicationPeriodBadge from '../components/PublicationPeriodBadge.vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  dateKindLabel, getDiscoveryItem, localTimeLabel, newsGenreLabel,
  publicationLabel, readingBasisLabel, safeExternalUrl, venueLabel,
} from '../api/discovery'
import type { DiscoveryItem } from '../discovery-types'
import PersonalLibraryPanel from '../components/PersonalLibraryPanel.vue'

const props = defineProps<{ id: string }>()
const route = useRoute()
const item = ref<DiscoveryItem | null>(null)
const loading = ref(true)
const error = ref('')
let requestNumber = 0
let controller: AbortController | undefined

const listPath = computed(() => {
  const from = route.query.from
  return typeof from === 'string' && /^\/(?:(?:discover|library|explore\/ic))?(?:\?|$)/.test(from)
    ? from : item.value?.content_type === 'news' ? '/discover?content_type=news' : '/discover?content_type=paper'
})
const relevanceLabels: Record<string, string> = {
  pending: '符合收录关键词',
  core: '核心相关', candidate_core: '核心相关候选',
  transferable_method: '方法可迁移', transferable_application: '相关应用',
  related_tool: '相关工具',
}
const relevance = computed(() => relevanceLabels[item.value?.relevance || ''] || '')
const isPaper = computed(() => item.value?.content_type === 'paper')
const externalUrl = computed(() => safeExternalUrl(item.value?.url))
const newsGenre = computed(() => {
  const entry = item.value
  if (!entry || isPaper.value) return ''
  const kind = newsGenreLabel(entry.news_genre)
  if (entry.verification_mode === 'original_page_review') return kind
  return newsGenreLabel(entry.published_source_check?.genre) || kind
})
const noteBasis = {
  abstract: '作者摘要',
  abstract_excerpt: '作者摘要原文摘句',
  abstract_notes_excerpt: '作者摘要摘录',
  report: '原报道',
  report_excerpt: '公开原文摘录',
  report_summary: '已收录原文要点',
  news_listing: '官方列表或检索摘要',
  source_intro: '来源简介',
}
const readingBasis = computed(() => {
  const entry = item.value
  if (!entry) return ''
  if (isPaper.value) {
    if (entry.reading_notes?.basis === 'report') return ''
    return entry.abstract_text?.trim() ? '作者摘要' : entry.summary?.trim() ? '已收录的摘要或简介' : '论文题录'
  }
  const basis = entry.reading_notes?.basis
  if (basis && basis !== 'report') return noteBasis[basis]
  if (entry.verification_mode === 'original_page_review') return '已核对公开原文'
  if (entry.verification_mode === 'official_search_listing_manual') return '官方检索摘要或新闻列表'
  const status = entry.published_source_check?.status
  if (status) return readingBasisLabel(status, entry.content_type)
  return entry.summary?.trim() || entry.abstract_text?.trim() ? '来源简介' : '标题与来源链接'
})
const sourceNote = computed(() => {
  const note = item.value?.verification_note || ''
  if (note.startsWith('公开来源自动采集；相关性由关键词初筛')) return ''
  if (note.startsWith('原站题名与日期核对，日期依据') || note.startsWith('题名和可用简介取自原站页面。')) return '题名和发表日期来自原站页面。'
  if (note.startsWith('历史补采；首次发布日期依据原站RSS')) return '首次发表日期取自原站订阅。'
  if (note.startsWith('采集自 imec 官方文章')) return '日期和简介来自 imec 的公开公告。文中进展和计划由 imec 披露。'
  if (note.startsWith('本次人工核对官方站点公开检索摘录或新闻列表')) {
    return note.includes('原始出处为官方列表') ? '题名和日期来自官方列表，出处链接指向该列表。' : '题名和日期来自官方检索摘要或新闻列表。'
  }
  return note
})
const sourceText = computed(() => {
  const original = item.value?.abstract_text?.trim() || ''
  const summary = item.value?.summary?.trim() || ''
  if (isPaper.value && original) return { title: '原始摘要', text: original }
  const title = summary && item.value?.summary_kind === 'human' && !isPaper.value ? '报道要点' : isPaper.value ? '摘要摘录' : '来源简介'
  return { title, text: (summary || original).replace(/\s*The post [^\r\n]+ appeared first on [^\r\n]+\.?$/i, '').trim() }
})
const activeEvent = computed(() => {
  const events = item.value?.event_briefs
  return events?.find(event => event.event_id === route.query.event) || events?.[0]
})
const relatedSources = computed(() => activeEvent.value?.sources.filter(source => source.id !== props.id) || [])
const quickRead = computed(() => {
  const notes = item.value?.reading_notes
  if (notes?.points.length) return {
    title: isPaper.value ? '论文要点' : '报道要点',
    basis: notes.basis === 'abstract_excerpt' ? noteBasis[notes.basis] : `依据${noteBasis[notes.basis]}`,
    points: notes.points,
  }
  const event = activeEvent.value
  if (event) return {
    title: '热点速览',
    basis: '综合同一事件的关联资料',
    points: [
      { label: '发生了什么', text: event.what_happened },
      { label: '技术看点', text: event.why_it_matters },
      { label: '证据与后续', text: `${event.evidence_stage}。${event.watch_next}` },
    ],
  }
  const review = item.value?.published_source_check
  if (review?.summary) return {
    title: '报道要点',
    basis: readingBasisLabel(review.status),
    points: [
      { label: '报道讲了什么', text: review.summary },
      ...(review.boundary ? [{ label: '结论范围', text: review.boundary }] : []),
    ],
  }
})
const sourceLine = computed(() => {
  const entry = item.value
  if (!entry) return []
  const date = entry.published_at || entry.publication_month || entry.publication_year
  return [
    isPaper.value ? venueLabel(entry) || entry.source : entry.source,
    !isPaper.value && entry.verification_mode === 'original_page_review' ? entry.authors?.join('、') : '',
    date ? `${dateKindLabel(entry.date_kind)} ${publicationLabel(entry)}` : '',
    newsGenre.value,
  ].filter(Boolean)
})
const topics = computed(() => item.value?.ic_ai?.topics.length ? item.value.ic_ai.topics : item.value?.topics || [])
const referenceFields = computed(() => {
  const entry = item.value
  if (!entry) return []
  return [
    { label: '采集来源', value: entry.source },
    { label: '收录时间（北京时间）', value: entry.collected_at && localTimeLabel(entry.collected_at) },
    { label: '阅读依据', value: readingBasis.value },
    { label: '稿件类型', value: !isPaper.value && !newsGenre.value ? '来源类型未确认' : undefined },
    { label: '转载情况', value: !isPaper.value && entry.verification_mode !== 'original_page_review'
      && !entry.published_source_check?.genre && /^(硬件)?专业媒体报道$/.test(newsGenre.value) ? '未确认' : undefined },
    { label: '相关性', value: isPaper.value || !entry.observation_classification?.categories.length ? relevance.value : undefined },
    { label: '会议年份', value: isPaper.value ? entry.conference_year : undefined },
    { label: '会议 Track', value: isPaper.value ? entry.track : undefined },
    { label: 'DOI', value: isPaper.value ? entry.doi : undefined },
    { label: 'arXiv 标识', value: isPaper.value ? entry.arxiv_id : undefined },
  ].filter(field => field.value)
})

async function load() {
  const currentRequest = ++requestNumber
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  error.value = ''
  item.value = null
  try {
    const result = await getDiscoveryItem(props.id, controller.signal)
    if (currentRequest === requestNumber) item.value = result
  } catch (cause) {
    if (currentRequest === requestNumber) error.value = cause instanceof Error ? cause.message : '条目加载失败'
  } finally {
    if (currentRequest === requestNumber) loading.value = false
  }
}

watch(() => props.id, () => { void load() }, { immediate: true })
onBeforeUnmount(() => { ++requestNumber; controller?.abort() })
</script>

<template>
  <div>
    <router-link :to="listPath" class="inline-block text-sm text-stone-500 hover:text-accent dark:text-stone-400">{{ listPath.startsWith('/explore/ic') ? '返回技术评价' : listPath==='/' || listPath.startsWith('/?') ? '返回热点与技术观察' : listPath.startsWith('/library') ? '← 返回我的收藏' : '← 返回每日发现' }}</router-link>
    <p v-if="loading" role="status" class="py-20 text-center text-sm text-stone-400">正在读取条目…</p>
    <div v-else-if="error" role="alert" class="mt-8 border border-red-200 bg-red-50 p-6 dark:border-red-900 dark:bg-red-950/30"><h2 class="font-serif text-xl text-red-800 dark:text-red-300">暂时无法打开这条资料</h2><p class="mt-3 text-sm text-red-600 dark:text-red-400">{{ error }}</p><button type="button" class="mt-4 text-sm text-accent underline underline-offset-4" @click="load">重新读取</button></div>
    <article v-else-if="item" aria-labelledby="discovery-title" class="mt-5">
      <header class="border-b border-stone-200 pb-5 dark:border-stone-800">
        <p class="text-xs font-medium text-stone-600 dark:text-stone-400">{{ isPaper ? '研究文献' : '新闻与动态' }}</p>
        <h2 id="discovery-title" class="mt-2 break-words font-serif text-2xl font-bold leading-snug text-stone-900 sm:text-3xl dark:text-stone-50">{{ item.title }}</h2>
        <p v-if="sourceLine.length" class="mt-3 break-words text-sm leading-6 text-stone-600 dark:text-stone-400">{{ sourceLine.join(' · ') }}</p>
        <PersonalLibraryPanel :key="item.id" :item="item" :initially-open="route.query.edit==='notes'">
          <a v-if="externalUrl" :href="externalUrl" target="_blank" rel="noopener noreferrer" class="font-medium text-accent underline-offset-4 hover:underline">查看原文 ↗</a>
        </PersonalLibraryPanel>
      </header>

      <section v-if="quickRead" class="mt-5" aria-labelledby="reading-notes-title">
        <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h3 id="reading-notes-title" class="font-serif text-xl font-bold">{{ quickRead.title }}</h3>
          <p class="text-xs text-stone-600 dark:text-stone-400">{{ quickRead.basis }}</p>
        </div>
        <div class="mt-3 divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white px-4 sm:px-5 dark:divide-stone-800 dark:border-stone-800 dark:bg-stone-900">
          <section v-for="point in quickRead.points" :key="point.label" class="grid gap-1.5 py-3.5 sm:grid-cols-[7rem_minmax(0,1fr)] sm:gap-3">
            <h4 class="text-sm font-semibold leading-7">{{ point.label }}</h4>
            <p class="break-words text-sm leading-7" :class="isPaper && (point.label === '主要发现' || point.label === '作者报告的结果') ? 'font-medium text-stone-900 dark:text-stone-50' : 'text-stone-700 dark:text-stone-300'">{{ point.text }}</p>
          </section>
        </div>
      </section>

      <details v-if="quickRead && sourceText.text" class="mt-5 border-b border-stone-200 pb-3 dark:border-stone-800">
        <summary class="cursor-pointer text-sm font-medium">{{ sourceText.title }}</summary>
        <p class="mt-3 whitespace-pre-wrap break-words text-sm leading-7 text-stone-700 dark:text-stone-300">{{ sourceText.text }}</p>
      </details>
      <section v-else-if="!quickRead" class="mt-5">
        <h3 class="font-serif text-xl font-bold">{{ sourceText.text ? sourceText.title : isPaper ? '摘要' : '报道简介' }}</h3>
        <p class="mt-3 whitespace-pre-wrap break-words text-sm leading-7 text-stone-700 dark:text-stone-300">{{ sourceText.text || (externalUrl ? (isPaper ? '当前仅收录题录，正文见原文。' : '当前仅收录标题和来源链接。') : '来源暂未提供简介或摘要。') }}</p>
        <p v-if="item.verification_mode==='official_search_listing_manual'" class="mt-2 text-xs text-stone-600 dark:text-stone-400">阅读依据为官方检索摘要或新闻列表。</p>
      </section>
      <details v-if="relatedSources.length" class="mt-4 border-b border-stone-200 pb-3 dark:border-stone-800">
        <summary class="cursor-pointer text-sm font-medium">同一事件的其他来源（{{ relatedSources.length }}）</summary>
        <ul class="mt-2 space-y-2 text-sm">
          <li v-for="source in relatedSources" :key="source.id">
            <RouterLink :to="{ name: 'discover-detail', params: { id: source.id }, query: { from: listPath, event: activeEvent?.event_id } }" class="text-accent hover:underline">{{ source.name }}</RouterLink>
          </li>
        </ul>
      </details>

      <p v-if="item.observation_classification" class="mt-4 break-words text-xs leading-6 text-stone-600 dark:text-stone-400">
        当前观察分类
        <span v-if="item.observation_classification.basis==='pending'"> · 未归入具体方向</span>
        <span v-for="category in item.observation_classification.categories" :key="category.id"> · {{ category.name }}</span>
        <span v-for="topic in item.observation_classification.topics" :key="topic.id"> ·
          <RouterLink v-if="!IS_STATIC" :to="{ name: 'ic-technology-topic', params: { topicId: topic.id } }" class="text-accent hover:underline">{{ topic.name }}</RouterLink>
          <span v-else>{{ topic.name }}</span><span v-if="topic.status==='paused'">（历史专题）</span>
        </span>
      </p>
      <section v-if="isPaper && item.ic_ai" class="mt-5 border-t border-stone-200 pt-4 dark:border-stone-800" aria-label="研究关联">
        <h3 class="font-serif text-lg font-semibold">研究关联</h3>
        <ICRelationPanel :analysis="item.ic_ai" />
      </section>
      <p v-else-if="topics.length" class="mt-5 break-words text-sm text-stone-600 dark:text-stone-400">相关专题 · {{ topics.join('、') }}</p>

      <details class="mt-5 border-y border-stone-200 py-3 dark:border-stone-800">
        <summary class="cursor-pointer text-sm font-medium">来源与阅读依据</summary>
        <p v-if="sourceNote" class="mt-3 whitespace-pre-wrap break-words text-sm leading-7 text-stone-600 dark:text-stone-400">{{ sourceNote }}</p>
        <div v-if="isPaper && item.publication_timing" class="mt-3"><PublicationPeriodBadge :item="item" /></div>
        <dl class="mt-3 grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <div v-for="field in referenceFields" :key="field.label"><dt class="text-xs text-stone-600 dark:text-stone-400">{{ field.label }}</dt><dd class="mt-1 break-words">{{ field.value }}</dd></div>
          <div v-if="isPaper && Array.isArray(item.authors) && item.authors.length" class="sm:col-span-2"><dt class="text-xs text-stone-600 dark:text-stone-400">作者</dt><dd class="mt-1 break-words">{{ item.authors.join('、') }}</dd></div>
        </dl>
        <ul v-if="item.abstract_provenance?.length" class="mt-3 space-y-1 text-sm text-stone-600 dark:text-stone-400">
          <li v-for="(entry,index) in item.abstract_provenance" :key="index">摘要补充来源 · <a v-if="safeExternalUrl(entry.url)" :href="safeExternalUrl(entry.url)" target="_blank" rel="noopener noreferrer" class="text-accent hover:underline">{{ entry.source }}</a><span v-else>{{ entry.source }}</span></li>
        </ul>
      </details>
    </article>
  </div>
</template>
