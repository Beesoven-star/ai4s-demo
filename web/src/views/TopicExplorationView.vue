<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { safeExternalUrl } from '../api/discovery'

interface Topic {
  id: string; name: string; scope: string; focus: string; question: string
  count: number; recent_count: number
}
interface Paper {
  id: string; arxiv_id: string; title: string; authors: string[]; url: string
  topic_id: string; published_at: string; updated_at_source: string
  abstract_text: string; abstract_truncated: boolean; date_group: string
  relevance: string; auto_cluster_id: string; auto_fine_cluster_id: string
  is_representative: boolean; doi?: string
}
interface Snapshot {
  as_of: string; recent_window: { start: string; end: string }
  counts: { included: number; recent_30_days: number; retrieved_unique: number; excluded: number; abstract_reviewed: number }
  topics: Topic[]; items: Paper[]
  method: { selected_k: number; selected_cosine_silhouette: number }
}

const snapshot = ref<Snapshot | null>(null)
const error = ref('')
const selectedTopic = ref('')
const keyword = ref('')
const period = ref('all')
const scope = ref('all')
const page = ref(1)
const pageSize = 15
const selected = computed(() => snapshot.value?.topics.find(topic => topic.id === selectedTopic.value))
const topicNames = computed(() => Object.fromEntries((snapshot.value?.topics || []).map(topic => [topic.id, topic.name])))
const filtered = computed(() => {
  const query = keyword.value.trim().toLocaleLowerCase()
  return (snapshot.value?.items || []).filter(paper => {
    const extension = ['T08', 'T09'].includes(paper.topic_id)
    const recent = paper.published_at >= (snapshot.value?.recent_window.start || '')
    return (!selectedTopic.value || paper.topic_id === selectedTopic.value)
      && (scope.value === 'all' || (scope.value === 'core' ? !extension : extension))
      && (period.value === 'all' || (period.value === 'recent' ? recent : !recent))
      && (!query || `${paper.title} ${paper.abstract_text} ${paper.authors.join(' ')} ${paper.arxiv_id} ${topicNames.value[paper.topic_id]}`.toLocaleLowerCase().includes(query))
  })
})
const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const visiblePapers = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))

function selectTopic(id: string) {
  selectedTopic.value = selectedTopic.value === id ? '' : id
  page.value = 1
}
function reset() {
  selectedTopic.value = ''; keyword.value = ''; period.value = 'all'; scope.value = 'all'; page.value = 1
}
async function load() {
  error.value = ''
  try {
    const response = await fetch('/ic-exploration-20261110.json')
    if (!response.ok) throw new Error(`数据读取失败（${response.status}）`)
    snapshot.value = await response.json() as Snapshot
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '论文样本暂时无法读取'
  }
}
onMounted(load)
</script>

<template>
  <div>
    <header class="mb-7">
      <p class="text-[11px] font-semibold tracking-[0.22em] text-accent">INTEGRATED CIRCUITS · TOPIC EXPLORATION</p>
      <h2 class="mt-3 font-serif text-3xl font-bold text-stone-900 sm:text-4xl dark:text-stone-50">集成电路主题探索</h2>
      <p class="mt-3 text-sm leading-7 text-stone-500 dark:text-stone-400">先从真实论文看研究任务，再形成可继续阅读与跟踪的子方向。</p>
      <div class="mt-5 border-t-2 border-stone-900 dark:border-stone-100" />
      <p v-if="snapshot" class="mt-3 text-xs leading-6 text-stone-500">检索截至 {{ snapshot.as_of }} · arXiv 作者预印本 · 本轮为固定样本</p>
      <p class="mt-3 text-sm leading-7 text-stone-600 dark:text-stone-300">后续采集的正式期刊论文和新闻可在每日发现中查看：<RouterLink to="/discover?publication_kind=journal" class="text-accent underline">期刊论文</RouterLink><span class="mx-2">·</span><RouterLink to="/discover?content_type=news" class="text-accent underline">集成电路新闻</RouterLink>。新增资料尚未纳入本页九个专题。</p>
    </header>

    <p v-if="error" role="alert" class="border border-red-200 bg-red-50 p-4 text-sm text-red-800">{{ error }} <button class="ml-2 underline" @click="load">重试</button></p>
    <p v-else-if="!snapshot" class="py-12 text-center text-stone-500">正在读取论文与专题…</p>
    <template v-else>
      <dl class="grid grid-cols-3 gap-4 border-b border-stone-200 pb-5 dark:border-stone-700">
        <div><dt class="text-xs text-stone-500">初筛论文</dt><dd class="mt-2 font-serif text-3xl font-bold">{{ snapshot.counts.included }}</dd></div>
        <div><dt class="text-xs text-stone-500">近30天首次提交</dt><dd class="mt-2 font-serif text-3xl font-bold">{{ snapshot.counts.recent_30_days }}</dd></div>
        <div><dt class="text-xs text-stone-500">候选子方向</dt><dd class="mt-2 font-serif text-3xl font-bold">{{ snapshot.topics.length }}</dd></div>
      </dl>

      <p class="my-5 border-l-2 border-accent pl-4 text-sm leading-7 text-stone-600 dark:text-stone-300">专题来自文本聚类后的语义整理，仍可调整。已抽查 {{ snapshot.counts.abstract_reviewed }} 篇摘要，其余待逐篇核验；日期为预印本首次提交日，正式出版状态待核实。</p>

      <section aria-labelledby="topic-heading">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2"><h3 id="topic-heading" class="font-serif text-xl font-bold">从一个子方向开始</h3><button v-if="selectedTopic" class="text-xs text-accent underline" @click="selectTopic('')">查看全部方向</button></div>
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <button v-for="topic in snapshot.topics" :key="topic.id" type="button" :aria-pressed="selectedTopic === topic.id" class="border p-4 text-left transition-colors" :class="selectedTopic === topic.id ? 'border-accent bg-orange-50 dark:bg-orange-950/30' : 'border-stone-200 hover:border-accent/50 dark:border-stone-700'" @click="selectTopic(topic.id)">
            <span class="flex items-center justify-between gap-3"><span class="text-xs text-accent">{{ topic.id }}<span v-if="['T08', 'T09'].includes(topic.id)"> · 拓展</span></span><span class="text-xs text-stone-500">{{ topic.count }} 篇</span></span>
            <span class="mt-2 block text-sm font-semibold leading-6">{{ topic.name }}</span>
            <span class="mt-2 block text-xs leading-6 text-stone-500">近30天 {{ topic.recent_count }} 篇</span>
          </button>
        </div>
        <div v-if="selected" class="mt-4 border-l-2 border-accent pl-4">
          <p class="text-sm leading-7">{{ selected.focus }}</p><p class="mt-2 text-sm leading-7 text-stone-500">可展开的问题：{{ selected.question }}</p>
        </div>
      </section>

      <section class="mt-8" aria-labelledby="papers-heading">
        <h3 id="papers-heading" class="font-serif text-xl font-bold">论文样本</h3>
        <div class="mt-4 grid gap-3 sm:grid-cols-2">
          <label class="sm:col-span-2"><span class="mb-2 block text-xs text-stone-500">关键词 · 题名、摘要节选、作者或 arXiv 编号</span><input v-model="keyword" type="search" class="w-full border border-stone-300 bg-transparent px-3 py-2 text-sm dark:border-stone-600" placeholder="例如 RTL、analog、chiplet" @input="page = 1"></label>
          <label><span class="mb-2 block text-xs text-stone-500">时间范围</span><select v-model="period" class="w-full border border-stone-300 bg-transparent px-3 py-2 text-sm dark:border-stone-600" @change="page = 1"><option value="all">全部首次提交日期</option><option value="recent">近30天 · {{ snapshot.recent_window.start }} 至 {{ snapshot.as_of }}</option><option value="earlier">历史补录 · 本年较早资料</option></select></label>
          <label><span class="mb-2 block text-xs text-stone-500">研究范围</span><select v-model="scope" class="w-full border border-stone-300 bg-transparent px-3 py-2 text-sm dark:border-stone-600" @change="page = 1"><option value="all">全部专题</option><option value="core">电子集成电路与器件</option><option value="extension">光子/声子、低温/超导拓展</option></select></label>
        </div>
        <div class="mt-4 flex justify-between gap-4 text-xs text-stone-500"><p aria-live="polite">找到 {{ filtered.length }} 篇 · 首次提交日倒序</p><button type="button" class="text-accent underline" @click="reset">重置筛选</button></div>

        <p v-if="!filtered.length" class="py-10 text-center text-sm text-stone-500">当前条件下没有论文，可调整关键词、专题或时间范围。</p>
        <article v-for="paper in visiblePapers" :key="paper.id" class="border-b border-stone-200 py-5 dark:border-stone-700">
          <div class="flex flex-wrap gap-x-3 gap-y-1 text-xs leading-6 text-stone-500"><span>{{ paper.published_at }} · 首次提交</span><span>{{ paper.date_group }}</span><span v-if="paper.is_representative" class="text-accent">代表性材料</span></div>
          <router-link :to="{ path: '/discover', query: { q: paper.arxiv_id } }" class="mt-2 inline-block text-xs text-accent underline">查看详情与收藏 →</router-link>
          <h4 class="mt-2 text-base font-semibold leading-7"><a :href="safeExternalUrl(paper.url)" target="_blank" rel="noopener noreferrer" class="hover:text-accent">{{ paper.title }} <span aria-hidden="true">↗</span></a></h4>
          <p class="mt-2 text-xs leading-6 text-stone-500">{{ paper.authors.slice(0, 4).join(' · ') }}<span v-if="paper.authors.length > 4"> 等</span></p>
          <p class="mt-2 text-xs leading-6 text-accent">{{ topicNames[paper.topic_id] }} · {{ paper.relevance === 'abstract_reviewed' ? '依据摘要' : '依据论文题名' }}</p>
          <details class="mt-3 text-sm"><summary class="cursor-pointer text-stone-600 dark:text-stone-300">摘要节选与来源信息</summary><p class="mt-3 break-words leading-7 text-stone-600 dark:text-stone-300">{{ paper.abstract_text }}</p><p class="mt-2 text-xs leading-6 text-stone-500">{{ paper.abstract_truncated ? '节选最多140个英文词，完整摘要见原文。' : '摘要读取自原始题录。' }} arXiv:{{ paper.arxiv_id }} · 来源版本更新 {{ paper.updated_at_source.slice(0, 10) }}</p></details>
        </article>
        <nav v-if="totalPages > 1" class="mt-6 flex items-center justify-between gap-3 text-sm" aria-label="论文分页"><button type="button" :disabled="page === 1" class="border border-stone-300 px-4 py-2 disabled:opacity-30 dark:border-stone-600" @click="page--">上一页</button><span class="text-xs text-stone-500">{{ page }} / {{ totalPages }}</span><button type="button" :disabled="page >= totalPages" class="border border-stone-300 px-4 py-2 disabled:opacity-30 dark:border-stone-600" @click="page++">下一页</button></nav>
      </section>

      <details class="mt-8 border-t border-stone-200 pt-4 text-sm dark:border-stone-700"><summary class="cursor-pointer text-stone-500">检索与分组方法</summary><div class="mt-3 space-y-3 text-xs leading-7 text-stone-500"><p>五组宽检索返回200条记录，去重后 {{ snapshot.counts.retrieved_unique }} 篇，排除 {{ snapshot.counts.excluded }} 篇后保留 {{ snapshot.counts.included }} 篇。每组最多40条，查询存在截断；仅覆盖 arXiv，未覆盖全部正式期刊、会议与工业成果。</p><p>题名/摘要 TF-IDF 与球面 K-means 的自动粗分为 {{ snapshot.method.selected_k }} 组，平均轮廓系数 {{ snapshot.method.selected_cosine_silhouette }}，区分度较弱。对照细分并按主要研究任务整理为九个候选专题，每篇暂设一个主专题。专题篇数不代表领域热度。</p><p>这是截至 {{ snapshot.as_of }} 的独立探索快照。本页为固定检索快照；在每日发现与资料详情中可收藏、备注并维护阅读状态。新增采集资料尚不自动更新本页聚类。</p></div></details>
    </template>
  </div>
</template>
