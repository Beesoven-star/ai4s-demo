<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { LocationQuery, LocationQueryRaw } from 'vue-router'
import SummaryPreview from '../components/SummaryPreview.vue'
import FavoriteButton from '../components/FavoriteButton.vue'
import CollectionPanel from '../components/CollectionPanel.vue'
import PublicationPeriodBadge from '../components/PublicationPeriodBadge.vue'
import { IS_STATIC } from '../static-mode'
import {
  dateKindLabel, getDiscoveryFacets, listDiscoveryItems, listDiscoveryRuns,
  localTimeLabel, newsGenreLabel, publicationLabel, safeExternalUrl, summaryKindLabel, venueLabel,
} from '../api/discovery'
import { workspace } from '../workspace'
import type {
  DiscoveryContentType, DiscoveryDateBasis, DiscoveryFacets,
  DiscoveryFilters, DiscoveryItem, DiscoveryOrigin, DiscoveryRun,
} from '../discovery-types'

const route = useRoute()
const router = useRouter()
const PAGE_SIZE = 20
const contentType = computed<DiscoveryContentType>(() => queryString(route.query, 'content_type') === 'news' ? 'news' : 'paper')
const isPaper = computed(() => contentType.value === 'paper')
const categories: DiscoveryContentType[] = ['paper', 'news']
const categoryTabs = computed(() => workspace.domain === 'ic' ? [...categories].reverse() : categories)
const categoryLabel = computed(() => isPaper.value ? '文献' : '新闻')
const countUnit = computed(() => isPaper.value ? '篇' : '条')
const paperOnlyFilters = ['topic','venue','publication_kind','research_track','literature_scope','publication_period']
const literatureScopes = [
  { id: 'main', label: '主文献库' },
  { id: 'all', label: '全部文献候选' },
  { id: 'archive', label: '扩展归档' },
]
const form = reactive({
  q: '', content_type: '', topic: '', venue: '', date_from: '', date_to: '',
  date_basis: 'published', origin: '', publication_kind: '', research_track: '',
  literature_scope: 'main', publication_period: '', news_scope:'main',
})
const items = ref<DiscoveryItem[]>([])
const total = ref(0)
const offset = ref(0)
const facets = ref<DiscoveryFacets | null>(null)
const runs = ref<DiscoveryRun[]>([])
const loading = ref(true)
const error = ref('')
const formError = ref('')
const metadataWarning = ref('')
const runLoadError = ref(false)
const collectionOpen = ref(false)
const statisticsOpen = ref(false)
const advancedOpen = ref(false)
let requestNumber = 0
let controller: AbortController | undefined

function queryString(query: LocationQuery, key: string): string {
  const value = query[key]
  return typeof value === 'string' ? value : ''
}

function readQuery(query: LocationQuery) {
  form.q = queryString(query, 'q')
  const selectedType = queryString(query, 'content_type') === 'news' ? 'news' : 'paper'
  form.content_type = selectedType
  form.topic = selectedType === 'paper' ? queryString(query, 'topic') : ''
  form.venue = selectedType === 'paper' ? queryString(query, 'venue') : ''
  const publicationKind = queryString(query, 'publication_kind')
  form.publication_kind = selectedType === 'paper' && ['journal', 'conference', 'preprint'].includes(publicationKind) ? publicationKind : ''
  const researchTrack = queryString(query,'research_track')
  form.research_track = selectedType === 'paper' && ['any_ai','ai_for_ic','ic_for_ai','general_ic'].includes(researchTrack) ? researchTrack : ''
  const scope = queryString(query,'literature_scope')
  form.literature_scope = ['main','all','archive'].includes(scope) ? scope : 'main'
  const period = queryString(query,'publication_period')
  form.publication_period = ['recent_published','recent_preprint','historical','month_only','unknown'].includes(period) ? period : ''
  form.news_scope=['main','all','archive'].includes(queryString(query,'news_scope')) ? queryString(query,'news_scope') : 'main'
  form.date_from = queryString(query, 'date_from')
  form.date_to = queryString(query, 'date_to')
  form.date_basis = queryString(query, 'date_basis') === 'collected' ? 'collected' : 'published'
  const origin = queryString(query, 'origin')
  form.origin = ['seed', 'collected'].includes(origin) ? origin : ''
  const requestedOffset = Number(queryString(query, 'offset'))
  offset.value = Number.isSafeInteger(requestedOffset) && requestedOffset >= 0
    ? Math.floor(requestedOffset / PAGE_SIZE) * PAGE_SIZE : 0
}

const topics = computed(() => [...new Set([...(facets.value?.topics || []), ...(form.topic ? [form.topic] : [])])])
const venues = computed(() => [...new Set([...(facets.value?.venues || []), ...(form.venue ? [form.venue] : [])])])
const advancedFilters = computed(() => [
  ['topic','专题',queryString(route.query,'topic')],
  ['venue','期刊 / 会议',queryString(route.query,'venue')],
  ['date_from','开始日期',queryString(route.query,'date_from')],
  ['date_to','结束日期',queryString(route.query,'date_to')],
  ['date_basis','日期依据',queryString(route.query,'date_basis')==='collected' ? '收录日期' : ''],
  ['origin','来源类别',({seed:'已核验样本',collected:'公开来源采集'} as Record<string,string>)[queryString(route.query,'origin')] || ''],
  ['publication_kind','出版形式',({journal:'正式期刊题录',conference:'会议论文',preprint:'作者预印本'} as Record<string,string>)[queryString(route.query,'publication_kind')] || ''],
  ['research_track','研究主线',({any_ai:'两类AI交叉研究',ai_for_ic:'AI用于芯片设计',ic_for_ai:'芯片用于AI计算',general_ic:'通用集成电路研究'} as Record<string,string>)[queryString(route.query,'research_track')] || ''],
  ['publication_period','发表时间',({recent_published:'近期正式发表',recent_preprint:'近期预印本',historical:'历史资料',month_only:'仅提供月份',unknown:'发表日期未知'} as Record<string,string>)[queryString(route.query,'publication_period')] || ''],
  ['news_scope','新闻范围',({all:'全部候选',archive:'拓展归档'} as Record<string,string>)[queryString(route.query,'news_scope')] || ''],
].filter(([, ,value]) => value).map(([key,label,value]) => ({key,label,value})))
const hasFilters = computed(() => Boolean(queryString(route.query, 'q') || advancedFilters.value.length))
const currentPage = computed(() => Math.floor(offset.value / PAGE_SIZE) + 1)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const resultDateBasis = computed(() => queryString(route.query, 'date_basis') === 'collected' ? '收录日期' : isPaper.value ? '发表日期' : '新闻发布日期')
const rangeLabel = computed(() => total.value && items.value.length
  ? `${offset.value + 1}–${Math.min(offset.value + items.value.length, total.value)}` : '0')

async function load() {
  const currentRequest = ++requestNumber
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  error.value = ''
  formError.value = ''
  metadataWarning.value = ''
  runLoadError.value = false
  const filters: DiscoveryFilters = {
    q: queryString(route.query, 'q'),
    content_type: contentType.value,
    topic: isPaper.value ? queryString(route.query, 'topic') : undefined,
    venue: isPaper.value ? queryString(route.query, 'venue') : undefined,
    publication_kind: isPaper.value ? form.publication_kind as DiscoveryFilters['publication_kind'] : undefined,
    research_track: isPaper.value ? form.research_track || undefined : undefined,
    literature_scope: isPaper.value ? form.literature_scope : undefined,
    publication_period: isPaper.value ? form.publication_period || undefined : undefined,
    news_scope: isPaper.value ? undefined : form.news_scope,
    date_from: queryString(route.query, 'date_from'),
    date_to: queryString(route.query, 'date_to'),
    date_basis: (queryString(route.query, 'date_basis') === 'collected' ? 'collected' : 'published') as DiscoveryDateBasis,
    origin: ['seed', 'collected'].includes(queryString(route.query, 'origin'))
      ? queryString(route.query, 'origin') as DiscoveryOrigin : undefined,
    limit: PAGE_SIZE, offset: offset.value,
  }
  const results = await Promise.allSettled([
    listDiscoveryItems(filters, controller.signal),
    getDiscoveryFacets(controller.signal),
    listDiscoveryRuns(controller.signal),
  ])
  if (currentRequest !== requestNumber) return
  const [listResult, facetResult, runResult] = results
  if (listResult.status === 'fulfilled') {
    items.value = listResult.value.items
    total.value = listResult.value.total
  } else {
    error.value = listResult.reason instanceof Error ? listResult.reason.message : '资料加载失败'
    items.value = []
    total.value = 0
  }
  if (facetResult.status === 'fulfilled') facets.value = facetResult.value
  if (runResult.status === 'fulfilled') runs.value = runResult.value
  else runLoadError.value = true
  if (facetResult.status === 'rejected' || runResult.status === 'rejected') {
    metadataWarning.value = '部分统计或采集记录暂时无法读取，可重新查询。'
  }
  loading.value = false
}

async function navigate(query: LocationQueryRaw) {
  const target = { path: '/discover', query }
  if (router.resolve(target).fullPath === route.fullPath) await load()
  else await router.push(target)
}

async function submit() {
  if (form.date_from && form.date_to && form.date_from > form.date_to) {
    formError.value = '开始日期不能晚于结束日期。'
    return
  }
  const query: LocationQueryRaw = {}
  for (const [key, value] of Object.entries(form)) {
    if (isPaper.value && key==='news_scope') continue
    if (!isPaper.value && paperOnlyFilters.includes(key)) continue
    if (value.trim() && !(key === 'date_basis' && value === 'published')) query[key] = value.trim()
  }
  await navigate(query)
  advancedOpen.value = false
}

async function reset() {
  const query = { content_type: contentType.value }
  readQuery(query)
  advancedOpen.value = false
  await navigate(query)
}

function literatureScopeLink(scope: string) {
  const query: LocationQueryRaw = { ...route.query, content_type: 'paper', literature_scope: scope === 'main' ? undefined : scope }
  delete query.offset
  delete query.research_track
  delete query.topic
  return { name: 'discover', query }
}

async function choosePeriod(period: string) {
  statisticsOpen.value = false
  await navigate({content_type:'paper',literature_scope:'all',publication_period:period})
}

async function removeAdvancedFilter(key: string) {
  const query: LocationQueryRaw = { ...route.query }
  delete query[key]
  delete query.offset
  await navigate(query)
}

async function changeContentType(next: DiscoveryContentType) {
  if (next === contentType.value) return
  advancedOpen.value = false
  const query: LocationQueryRaw = { ...route.query, content_type: next }
  delete query.offset
  if (next === 'news') for (const key of paperOnlyFilters) delete query[key]
  if (next === 'paper') delete query.news_scope
  await navigate(query)
}

async function changePage(nextOffset: number) {
  const query: LocationQueryRaw = { ...route.query }
  if (nextOffset > 0) query.offset = String(nextOffset)
  else delete query.offset
  await navigate(query)
}

function detailLink(item: DiscoveryItem) {
  return { path: `/discover/item/${encodeURIComponent(item.id)}`, query: { from: route.fullPath } }
}

function runStatusLabel(status: DiscoveryRun['status']) {
  return { success: '采集成功', no_results: '本次检索无匹配', failed: '采集失败' }[status]
}

watch(() => route.fullPath, () => {
  const cleanedQuery: LocationQueryRaw = { ...route.query }
  let removedFilter = false
  if (['pending','excluded'].includes(queryString(route.query,'literature_scope'))) {
    delete cleanedQuery.literature_scope
    removedFilter = true
  }
  if (queryString(route.query,'research_track')==='unconfirmed') {
    delete cleanedQuery.research_track
    removedFilter = true
  }
  if (queryString(route.query,'publication_period')==='future') {
    delete cleanedQuery.publication_period
    removedFilter = true
  }
  if (removedFilter) {
    delete cleanedQuery.offset
    void router.replace({ path:'/discover', query:cleanedQuery })
    return
  }
  if (contentType.value === 'news' && paperOnlyFilters.some(key => key in route.query)) {
    const query: LocationQueryRaw = { ...route.query }
    for (const key of paperOnlyFilters) delete query[key]
    delete query.offset
    void router.replace({ path: '/discover', query })
    return
  }
  readQuery(route.query)
  if (route.query.collection === '1') collectionOpen.value = true
  void load()
}, { immediate: true })

onBeforeUnmount(() => {
  ++requestNumber
  controller?.abort()
})
</script>

<template>
  <div>
    <header class="mb-4 flex flex-wrap items-end justify-between gap-3">
      <h2 class="font-serif text-3xl font-bold text-stone-900 sm:text-4xl dark:text-stone-50">每日发现</h2>
      <div class="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-stone-600 dark:text-stone-400">
        <button type="button" :aria-expanded="statisticsOpen" aria-controls="discovery-statistics" class="underline underline-offset-4 hover:text-accent" @click="statisticsOpen=!statisticsOpen">{{ statisticsOpen ? '收起统计' : '资料统计' }}</button>
        <button v-if="!IS_STATIC" type="button" :aria-expanded="collectionOpen" aria-controls="discovery-collection" class="underline underline-offset-4 hover:text-accent" @click="collectionOpen=!collectionOpen">{{ collectionOpen ? '收起采集' : '采集管理' }}</button>
      </div>
    </header>

    <section v-if="statisticsOpen && facets" id="discovery-statistics" aria-label="资料统计" class="mb-4 border border-stone-200 p-4 text-xs leading-6 text-stone-500 dark:border-stone-700">
      <div class="flex flex-wrap gap-x-6 gap-y-1">
        <p>库内 {{ facets.total }} 条<span v-if="IS_STATIC"> · 数据截至 {{ facets.today }}</span><span v-else-if="facets.new_today !== undefined"> · 今日收录 {{ facets.new_today }} 条</span></p>
        <p>原始文献候选 {{ facets.papers }} 条<span v-if="!IS_STATIC"> · 今日收录 {{ facets.papers_today || 0 }} 篇</span></p>
        <p>新闻 {{ facets.news }} 条<span v-if="facets.archived_news"> · 原始候选 {{ facets.news_candidates }} 条 · 拓展归档 {{ facets.archived_news }} 条</span></p>
      </div>
      <template v-if="isPaper && facets.publication_audit">
        <p class="mt-3">原始文献候选的发表时间 · 近30天 {{ facets.publication_audit.recent_start }} 至 {{ facets.publication_audit.as_of }}</p>
        <div class="mt-2 flex flex-wrap gap-2">
          <button v-for="entry in [{key:'recent_published',label:'近期正式发表'},{key:'recent_preprint',label:'近期预印本'},{key:'historical',label:'历史资料'},{key:'month_only',label:'仅提供发表月份'}]" :key="entry.key" type="button" class="border border-stone-200 px-3 py-1.5 hover:border-accent hover:text-accent dark:border-stone-700" @click="choosePeriod(entry.key)">{{ entry.label }} {{ facets.publication_audit.counts[entry.key] || 0 }} 篇</button>
        </div>
        <p class="mt-3">入库批次：<span v-for="(count,day) in facets.publication_audit.collection_days" :key="day" class="mr-3">{{ day }} · {{ count }} 条</span></p>
      </template>
    </section>

    <nav aria-label="文献与新闻分类" class="mb-3 flex gap-1 border-b border-stone-200 dark:border-stone-700">
      <button v-for="category in categoryTabs" :key="category" type="button" :aria-pressed="contentType===category" class="border-b-2 px-4 py-2 text-sm" :class="contentType===category ? 'border-accent font-semibold text-accent' : 'border-transparent text-stone-600 hover:text-accent dark:text-stone-400'" @click="changeContentType(category)">{{ category==='news' ? '新闻' : '文献' }}</button>
    </nav>

    <nav v-if="isPaper && workspace.domain==='ic'" aria-label="文献范围" class="mb-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
      <RouterLink v-for="scope in literatureScopes" :key="scope.id" :to="literatureScopeLink(scope.id)"
        :aria-current="form.literature_scope === scope.id ? 'page' : undefined"
        class="py-1 underline-offset-4 hover:text-accent hover:underline"
        :class="form.literature_scope === scope.id ? 'font-semibold text-accent underline' : 'text-stone-700 dark:text-stone-300'">
        {{ scope.label }}<span v-if="facets?.latest_paper_dates?.[scope.id]" class="ml-1 text-xs font-normal text-stone-500 dark:text-stone-400">最新发表 {{ facets.latest_paper_dates[scope.id] }}</span>
      </RouterLink>
    </nav>

    <div v-if="!IS_STATIC" id="discovery-collection" v-show="collectionOpen">
      <CollectionPanel @completed="load" />
    </div>

    <section aria-label="资料检索" class="mb-4">
      <h3 class="sr-only">{{ categoryLabel }}检索</h3>
      <form @submit.prevent="submit">
        <div class="flex flex-wrap items-end gap-2">
          <div class="min-w-0 flex-1 basis-full sm:basis-48">
            <label for="discovery-keyword" class="sr-only">关键词</label>
            <input id="discovery-keyword" v-model="form.q" type="search" placeholder="搜索标题、摘要或标签" class="discovery-input" />
          </div>
          <button type="submit" :disabled="loading" class="min-h-[42px] bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-soft disabled:cursor-wait disabled:opacity-60">{{ loading ? '查询中…' : `查询${categoryLabel}` }}</button>
          <button type="button" :aria-expanded="advancedOpen" aria-controls="discovery-advanced" class="pagination-button min-h-[42px] px-3 py-2" @click="advancedOpen=!advancedOpen">{{ advancedOpen ? '收起筛选' : '筛选' }}<span v-if="advancedFilters.length">（{{ advancedFilters.length }}）</span></button>
        </div>

        <div v-if="advancedFilters.length" class="mt-3 flex flex-wrap gap-2">
          <button v-for="filter in advancedFilters" :key="filter.key" type="button" :aria-label="`移除${filter.label}：${filter.value}`" class="max-w-full truncate rounded border border-stone-200 px-2 py-1 text-xs text-stone-600 hover:border-accent hover:text-accent dark:border-stone-700 dark:text-stone-400" @click="removeAdvancedFilter(filter.key)">{{ filter.value }} ×</button>
        </div>

        <div id="discovery-advanced" v-show="advancedOpen" class="mt-3 grid gap-3 rounded-lg border border-stone-200 bg-white p-4 sm:grid-cols-3 dark:border-stone-800 dark:bg-stone-900">
          <div v-if="isPaper">
            <label for="discovery-publication-period" class="filter-label">发表时间分类</label>
            <select id="discovery-publication-period" v-model="form.publication_period" class="discovery-input">
              <option value="">全部发表时间</option><option value="recent_published">近期正式发表（近30天）</option><option value="recent_preprint">近期预印本（近30天首次提交）</option><option value="historical">历史资料（30天之前）</option><option value="month_only">仅提供发表月份</option><option v-if="facets?.publication_audit?.counts.unknown" value="unknown">来源未提供发表日期</option>
            </select>
          </div>
          <div v-if="isPaper && facets?.domain==='ic'">
            <label for="discovery-research-track" class="filter-label">研究主线</label>
            <select id="discovery-research-track" v-model="form.research_track" class="discovery-input">
              <option value="">全部集成电路资料</option><option value="any_ai">两类AI交叉研究</option><option value="ai_for_ic">AI用于芯片设计</option><option value="ic_for_ai">芯片用于AI计算</option><option value="general_ic">通用集成电路研究</option>
            </select>
          </div>
          <div v-if="!isPaper && facets?.domain==='ic'">
            <label for="discovery-news-scope" class="filter-label">新闻范围</label>
            <select id="discovery-news-scope" v-model="form.news_scope" class="discovery-input">
              <option value="main">集成电路新闻与动态（{{ facets.news }} 条）</option><option value="archive">拓展归档（{{ facets.archived_news }} 条）</option><option value="all">全部原始新闻候选（{{ facets.news_candidates }} 条）</option>
            </select>
          </div>
          <div>
            <label for="discovery-date-basis" class="filter-label">日期依据</label>
            <select id="discovery-date-basis" v-model="form.date_basis" class="discovery-input"><option value="published">{{ isPaper ? '发表日期' : '新闻发布日期' }}</option><option value="collected">收录日期</option></select>
          </div>
          <div><label for="discovery-from" class="filter-label">开始日期</label><input id="discovery-from" v-model="form.date_from" type="date" class="discovery-input" /></div>
          <div><label for="discovery-to" class="filter-label">结束日期</label><input id="discovery-to" v-model="form.date_to" type="date" class="discovery-input" /></div>
          <div v-if="isPaper">
            <label for="discovery-topic" class="filter-label">研究专题</label>
            <select id="discovery-topic" v-model="form.topic" class="discovery-input"><option value="">全部专题</option><option v-for="topic in topics" :key="topic" :value="topic">{{ topic }}</option></select>
          </div>
          <div v-if="isPaper">
            <label for="discovery-venue" class="filter-label">期刊 / 会议</label>
            <select id="discovery-venue" v-model="form.venue" class="discovery-input"><option value="">全部期刊与会议</option><option v-for="venue in venues" :key="venue" :value="venue">{{ venue }}</option></select>
          </div>
          <div>
            <label for="discovery-origin" class="filter-label">资料来源类别</label>
            <select id="discovery-origin" v-model="form.origin" class="discovery-input"><option value="">全部资料</option><option value="seed">已核验样本</option><option value="collected">公开来源采集</option></select>
          </div>
          <div v-if="isPaper">
            <label for="discovery-publication-kind" class="filter-label">论文出版形式</label>
            <select id="discovery-publication-kind" v-model="form.publication_kind" class="discovery-input"><option value="">全部出版形式</option><option value="journal">正式期刊题录</option><option value="conference">会议论文</option><option value="preprint">作者预印本</option></select>
          </div>
          <div class="flex gap-3 sm:col-span-3">
            <button type="submit" :disabled="loading" class="bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-soft disabled:opacity-60">应用筛选</button>
            <button type="button" :disabled="loading" class="pagination-button px-3 py-2" @click="reset">重置条件</button>
          </div>
        </div>
        <p v-if="formError" role="alert" class="mt-3 text-sm text-red-600 dark:text-red-400">{{ formError }}</p>
      </form>
    </section>

    <p v-if="metadataWarning" role="status" class="mb-4 text-xs text-amber-700 dark:text-amber-400">{{ metadataWarning }}</p>
    <div class="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-stone-200 pb-3 dark:border-stone-800">
      <p class="text-sm text-stone-600 dark:text-stone-300">{{ hasFilters ? `${categoryLabel}筛选结果` : `全部${categoryLabel}` }}<span v-if="!loading && !error" class="ml-2 tabular-nums text-stone-400">{{ total }} {{ countUnit }}</span></p>
      <p class="text-xs text-stone-400">日期依据：{{ resultDateBasis }}</p>
    </div>

    <div v-if="loading" role="status" class="border border-dashed border-stone-200 px-6 py-16 text-center text-sm text-stone-400 dark:border-stone-800">正在读取本地资料…</div>
    <div v-else-if="error" role="alert" class="border border-red-200 bg-red-50 px-6 py-10 dark:border-red-900 dark:bg-red-950/30"><p class="font-medium text-red-700 dark:text-red-300">暂时无法读取资料</p><p class="mt-2 text-sm text-red-600 dark:text-red-400">{{ error }}</p><button class="mt-4 text-sm text-accent underline underline-offset-4" type="button" @click="load">重新读取</button></div>
    <div v-else-if="!items.length" class="border border-dashed border-stone-300 px-6 py-14 text-center dark:border-stone-700">
      <h3 class="font-serif text-xl text-stone-700 dark:text-stone-200">{{ total > 0 ? '当前页码超出结果范围' : `没有符合条件的${categoryLabel}` }}</h3>
      <p class="mx-auto mt-3 max-w-md text-sm leading-7 text-stone-400">{{ total > 0 ? `当前条件下共有 ${total} 条资料，请返回第一页继续浏览。` : hasFilters ? '可以放宽日期、关键词或类型条件。没有匹配结果不代表今天没有相关研究，采集情况请查看下方记录。' : '资料库尚未收录内容。采集和样本导入完成后，资料会显示在这里。' }}</p>
      <button v-if="total > 0" type="button" class="mt-5 text-sm text-accent underline underline-offset-4" @click="changePage(0)">返回第一页</button>
      <button v-else-if="hasFilters || offset" type="button" class="mt-5 text-sm text-accent underline underline-offset-4" @click="reset">查看全部{{ categoryLabel }}</button>
    </div>
    <div v-else class="divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white px-4 sm:px-6 dark:divide-stone-800 dark:border-stone-800 dark:bg-stone-900">
      <article v-for="item in items" :key="item.id" class="py-4 sm:py-5">
        <h3 class="break-words font-serif text-lg font-semibold leading-7 text-stone-900 dark:text-stone-100"><router-link :to="detailLink(item)" class="block hover:text-accent hover:underline">{{ item.title }}</router-link></h3>
        <div class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-stone-600 dark:text-stone-400">
          <span>{{ venueLabel(item) || item.source || '来源未提供' }}</span>
          <span v-if="newsGenreLabel(item.news_genre)">{{ newsGenreLabel(item.news_genre) }}</span>
          <PublicationPeriodBadge v-if="item.content_type==='paper'" :item="item" />
          <span class="tabular-nums sm:ml-auto">{{ dateKindLabel(item.date_kind) }} · {{ publicationLabel(item) }}</span>
        </div>
        <p v-if="item.verification_mode==='official_search_listing_manual'" class="mt-2 text-xs leading-6 text-stone-600 dark:text-stone-400">阅读依据为官方检索摘要或新闻列表。</p>
        <SummaryPreview v-if="item.abstract_text || item.summary" :id="`summary-${item.id}`" :text="item.abstract_text || item.summary" :label="item.content_type === 'news' ? item.summary_kind==='human' ? '报道简介' : '来源简介' : item.abstract_text ? '摘要预览' : summaryKindLabel(item.summary_kind)" />
        <p v-if="item.ic_ai?.topics.length || item.topics.length" class="mt-2 text-xs leading-5 text-stone-600 dark:text-stone-400">{{ (item.ic_ai?.topics.length ? item.ic_ai.topics : item.topics).join(' · ') }}</p>
        <div class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
          <FavoriteButton :item="item" class="!mt-0" />
          <a v-if="safeExternalUrl(item.url)" :href="safeExternalUrl(item.url)" target="_blank" rel="noopener noreferrer" class="text-stone-600 hover:text-accent hover:underline dark:text-stone-400">原始出处 ↗</a>
        </div>
      </article>
    </div>

    <nav v-if="!loading && !error && total > PAGE_SIZE" aria-label="结果分页" class="mt-6 flex flex-wrap items-center justify-between gap-4">
      <p class="text-xs tabular-nums text-stone-400">第 {{ currentPage }} / {{ totalPages }} 页 · 显示 {{ rangeLabel }} 条，共 {{ total }} 条</p>
      <div class="flex gap-2"><button type="button" :disabled="offset === 0" class="pagination-button" @click="changePage(Math.max(0, offset - PAGE_SIZE))">上一页</button><button type="button" :disabled="offset + PAGE_SIZE >= total" class="pagination-button" @click="changePage(offset + PAGE_SIZE)">下一页</button></div>
    </nav>

    <details v-if="!IS_STATIC" class="mt-10 border-t border-stone-200 pt-5 dark:border-stone-800">
      <summary class="cursor-pointer text-sm text-stone-600 dark:text-stone-300">采集记录<span class="ml-2 text-xs text-stone-400">最近 {{ runs.length }} 次</span></summary>
      <p class="mt-3 text-xs leading-6 text-stone-400">记录每个来源的实际执行情况。本次检索无匹配不表示整个期刊或会议没有相关研究；采集范围与数量限制请查看覆盖提示。已核验样本不代表今天自动采集的新增。</p>
      <p class="mt-1 text-xs leading-6 text-stone-400">读取量为本轮实际解析条目，受分页与订阅范围限制；日期初筛保留日期未知的候选。不同来源的候选可能重复，不能直接相加为独立论文数。</p>
      <p v-if="loading" class="mt-4 text-sm text-stone-400">正在读取采集记录…</p>
      <p v-else-if="runLoadError" role="status" class="mt-4 text-sm text-amber-700 dark:text-amber-400">采集记录暂时读取失败，尚不能判断来源是否成功执行，请重新查询。</p>
      <p v-else-if="!runs.length" class="mt-4 text-sm text-stone-400">暂无采集记录，尚不能据此判断今日是否有新增。</p>
      <ul v-else class="mt-4 divide-y divide-stone-100 dark:divide-stone-800">
        <li v-for="(run, index) in runs" :key="`${run.source_id}-${run.started_at}-${index}`" class="py-4">
          <div class="flex flex-wrap items-center justify-between gap-2"><span class="text-sm text-stone-700 dark:text-stone-200">{{ run.source_name }}</span><span class="text-xs" :class="run.status === 'failed' ? 'text-red-600 dark:text-red-400' : run.status === 'no_results' ? 'text-stone-500' : 'text-emerald-700 dark:text-emerald-400'">{{ runStatusLabel(run.status) }}</span></div>
          <p class="mt-2 text-xs leading-6 text-stone-400">{{ localTimeLabel(run.finished_at || run.started_at) }}<template v-if="run.selection"> · 读取 {{ run.selection.parsed }} · 日期初筛 {{ run.selection.date_matched }}</template> · 相关候选 {{ run.found }} · 新增 {{ run.inserted }} · 更新 {{ run.updated }}<span v-if="run.window_start || run.window_end"> · 检索窗口 {{ run.window_start || '不限' }} 至 {{ run.window_end || '不限' }}</span></p>
          <p v-if="run.coverage_warning" class="mt-2 border-l-2 border-amber-500 bg-amber-50 px-3 py-2 text-xs leading-6 text-amber-800 dark:bg-amber-950/30 dark:text-amber-300"><strong class="font-semibold">覆盖提示：</strong>{{ run.coverage_warning }}</p>
          <p v-if="run.status === 'failed' && run.error" class="mt-1 break-words text-xs leading-6 text-red-600 dark:text-red-400">{{ run.error }}</p>
        </li>
      </ul>
    </details>
  </div>
</template>

<style scoped>
.filter-label {
  @apply mb-1.5 block text-xs font-medium text-stone-500 dark:text-stone-400;
}
.discovery-input {
  @apply block min-h-[42px] w-full min-w-0 rounded-md border border-stone-300 bg-white px-3 py-2 text-sm text-stone-700 outline-none transition-colors placeholder:text-stone-400 focus:border-accent focus:ring-1 focus:ring-accent/30 dark:border-stone-700 dark:bg-stone-950 dark:text-stone-200;
}
.pagination-button {
  @apply rounded-md border border-stone-300 px-4 py-2 text-xs text-stone-600 hover:border-accent hover:text-accent disabled:cursor-default disabled:opacity-40 disabled:hover:border-stone-300 disabled:hover:text-stone-600 dark:border-stone-700 dark:text-stone-300;
}
</style>
