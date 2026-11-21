<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { publicationLabel, safeExternalUrl, dateKindLabel } from '../api/discovery'
import type { DiscoveryItem } from '../discovery-types'
import PublicationPeriodBadge from '../components/PublicationPeriodBadge.vue'
import { IS_STATIC } from '../static-mode'
import { staticExploration } from '../api/static-data'
import TechnologyBriefing from '../components/TechnologyBriefing.vue'
interface ResearchTopic { id: string; track: string; name: string; focus: string; count: number }
interface Exploration {
  screened_on: string; tracks: Record<string,string>; topics: ResearchTopic[]; items: DiscoveryItem[]; note: string
  counts: { total: number; ai_for_ic: number; ic_for_ai: number; both: number; general_ic: number; ai_candidates: number; unconfirmed: number; main:number; archive:number; excluded:number }
}
const data = ref<Exploration | null>(null)
const error = ref('')
const selectedTrack = ref('all')
const selectedTopic = ref('')
const keyword = ref('')
const page = ref(1)
const pageSize = 12
const controller = new AbortController()
const groups = ['ai_for_ic','ic_for_ai','general_ic']
const groupDescriptions: Record<string,string> = {
  ai_for_ic:'AI是设计方法：让模型帮助设计、预测、优化或验证芯片。',
  ic_for_ai:'AI是计算对象：为模型训练、推理和神经形态计算设计硬件。',
  general_ic:'少量背景阅读：电路实现、器件、传统算法与验证；与AI专题分开展示。',
}
const filtered = computed(() => (data.value?.items || []).filter(paper => {
  const analysis = paper.ic_ai!
  const trackMatches = selectedTrack.value === 'all' ? analysis.scope==='main'
    : selectedTrack.value === 'archive' ? analysis.scope==='archive'
    : analysis.scope==='main' && analysis.tracks.includes(selectedTrack.value)
  return trackMatches && (!selectedTopic.value || analysis.topic_ids.includes(selectedTopic.value))
    && (!keyword.value.trim() || `${paper.title} ${paper.abstract_text || ''} ${paper.doi || ''} ${paper.arxiv_id || ''}`.toLowerCase().includes(keyword.value.trim().toLowerCase()))
}))
const visible = computed(() => filtered.value.slice((page.value-1)*pageSize,page.value*pageSize))
const pages = computed(() => Math.max(1,Math.ceil(filtered.value.length/pageSize)))
function trackCount(track: string) {
  if (!data.value) return 0
  return ({ai_for_ic:data.value.counts.ai_for_ic,ic_for_ai:data.value.counts.ic_for_ai,general_ic:data.value.counts.general_ic} as Record<string,number>)[track] || 0
}
function chooseTrack(track: string) { selectedTrack.value=track; selectedTopic.value=''; page.value=1 }
function chooseTopic(topic: ResearchTopic) {
  selectedTrack.value=topic.track; selectedTopic.value=selectedTopic.value===topic.id ? '' : topic.id; page.value=1
}
async function load() {
  error.value=''
  try {
    if (IS_STATIC) { data.value = await staticExploration(controller.signal); return }
    const response = await fetch('/api/discovery/ic-exploration',{signal:controller.signal})
    if (!response.ok) throw new Error(`资料读取失败（${response.status}）`)
    data.value = await response.json() as Exploration
  } catch (reason) { if (!controller.signal.aborted) error.value=reason instanceof Error ? reason.message : '暂时无法读取专题' }
}
onMounted(load)
onBeforeUnmount(() => controller.abort())
</script>

<template>
  <div>
    <TechnologyBriefing :topic-mode="true" />
    <details class="mt-8 border-t border-stone-200 pt-5 dark:border-stone-700">
    <summary class="cursor-pointer text-base font-semibold">浏览完整研究分类与论文库</summary>
    <div class="mt-6">
    <header class="mb-7">
      <p class="text-[11px] font-semibold tracking-[0.2em] text-accent">AI + INTEGRATED CIRCUITS</p>
      <h2 class="mt-3 font-serif text-3xl font-bold sm:text-4xl">集成电路研究专题</h2>
      <p class="mt-3 text-sm leading-7 text-stone-500">区分AI用于芯片设计、芯片用于AI计算，并保留少量通用电路研究。</p>
      <div class="mt-5 border-t-2 border-stone-900 dark:border-stone-100" />
      <div class="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm"><RouterLink to="/discover?research_track=any_ai" class="text-accent underline">查看AI交叉论文</RouterLink><RouterLink to="/discover?content_type=news" class="text-accent underline">集成电路新闻</RouterLink><RouterLink to="/library" class="text-accent underline">我的收藏</RouterLink></div>
    </header>
    <p v-if="error" role="alert" class="border border-red-200 p-5 text-sm text-red-700">{{ error }} <button class="underline" @click="load">重试</button></p>
    <p v-else-if="!data" class="py-12 text-center text-stone-500">正在读取专题和归类线索…</p>
    <template v-else>
      <div class="mb-6 grid gap-3 sm:grid-cols-3" aria-label="主线概览"><button v-for="track in groups" :key="track" class="border border-stone-200 p-4 text-left dark:border-stone-700" @click="chooseTrack(track)"><span class="block text-xs text-accent">{{ data.tracks[track] }}</span><span class="mt-2 block font-serif text-2xl font-bold">{{ trackCount(track) }} <span class="text-xs font-normal text-stone-500">篇候选</span></span></button></div>
      <section aria-label="研究主线" class="space-y-6">
        <div v-for="track in groups" :key="track" class="border border-stone-200 p-5 dark:border-stone-700">
          <div class="flex flex-wrap items-center justify-between gap-3"><h3 class="font-serif text-xl font-bold">{{ data.tracks[track] }}</h3><button class="text-xs text-accent underline" @click="chooseTrack(track)">只看这一类</button></div>
          <p class="mt-2 text-sm leading-7 text-stone-500">{{ groupDescriptions[track] }}</p>
          <div class="mt-4 grid gap-3 sm:grid-cols-2">
            <button v-for="topic in data.topics.filter(t => t.track===track)" :key="topic.id" type="button" :aria-pressed="selectedTopic===topic.id" class="border p-4 text-left" :class="selectedTopic===topic.id ? 'border-accent bg-orange-50 dark:bg-orange-950/30' : 'border-stone-200 dark:border-stone-700'" @click="chooseTopic(topic)">
              <span class="flex justify-between gap-4 text-xs text-accent"><span>{{ topic.id }}</span><span>{{ topic.count }} 篇候选</span></span><span class="mt-2 block text-sm font-semibold leading-6">{{ topic.name }}</span><span class="mt-2 block text-xs leading-6 text-stone-500">{{ topic.focus }}</span>
            </button>
          </div>
        </div>
      </section>
      <section class="mt-8" aria-label="专题论文">
        <h3 class="font-serif text-xl font-bold">论文与归类线索</h3>
        <div class="mt-4 grid gap-3 sm:grid-cols-2"><label><span class="mb-2 block text-xs text-stone-500">研究主线</span><select v-model="selectedTrack" class="w-full border border-stone-300 bg-transparent px-3 py-2 text-sm dark:border-stone-600" @change="selectedTopic='';page=1"><option value="all">主文献库</option><option v-for="track in groups" :key="track" :value="track">{{ data.tracks[track] }}</option><option value="archive">扩展归档</option></select></label><label><span class="mb-2 block text-xs text-stone-500">关键词</span><input v-model="keyword" type="search" placeholder="例如 LLM、chiplet、GNN" class="w-full border border-stone-300 bg-transparent px-3 py-2 text-sm dark:border-stone-600" @input="page=1" /></label></div>
        <div class="mt-4 flex flex-wrap justify-between gap-3 text-xs text-stone-500"><p aria-live="polite">找到 {{ filtered.length }} 篇<span v-if="selectedTopic"> · {{ data.topics.find(t=>t.id===selectedTopic)?.name }}</span></p><button class="text-accent underline" @click="chooseTrack('all');keyword=''">重置筛选</button></div>
        <p v-if="!filtered.length" class="py-10 text-sm text-stone-500">当前条件下没有候选论文。</p>
        <article v-for="paper in visible" :key="paper.id" class="border-b border-stone-200 py-5 dark:border-stone-700">
          <p class="text-xs leading-6 text-stone-500">{{ dateKindLabel(paper.date_kind) }} · {{ publicationLabel(paper) }} · {{ paper.venue_name || paper.journal || paper.source }}</p>
          <PublicationPeriodBadge :item="paper" />
          <h4 class="mt-2 text-base font-semibold leading-7"><RouterLink :to="`/discover/item/${encodeURIComponent(paper.id)}`" class="hover:text-accent">{{ paper.title }}</RouterLink></h4>
          <p class="mt-2 text-xs leading-7 text-accent">{{ paper.ic_ai!.topics.join(' · ') || (paper.ic_ai!.basis === 'title_only' ? '依据题名' : '依据题名与摘要') }}</p>
          <p class="mt-1 text-xs leading-6 text-stone-500">{{ paper.ic_ai!.reviewed_on ? '题名/摘要范围审核' : '新候选自动线索初筛' }} · {{ paper.ic_ai!.basis==='title_only' ? '只有题名，缺少原始摘要' : '依据题名与可用摘要' }} · 尚未核验全文</p>
          <details class="mt-3 text-sm"><summary class="cursor-pointer text-stone-600 dark:text-stone-300">查看归类依据与摘要节选</summary><div v-for="(e,index) in paper.ic_ai!.evidence" :key="index" class="mt-3 border-l-2 border-stone-200 pl-3 text-xs leading-7 text-stone-500"><p>{{ e.topic_id }} · {{ e.field==='title' ? '题名线索' : '摘要线索' }}</p><p>{{ e.ai_signal }}</p><p v-if="e.task_signal!==e.ai_signal">{{ e.task_signal }}</p></div><p class="mt-3 text-xs leading-7 text-stone-500">{{ paper.ic_ai!.note }}</p><p class="mt-3 break-words text-xs leading-7 text-stone-500">{{ paper.abstract_text || '暂无原始摘要，请查看原始出处。' }}</p></details>
          <div class="mt-3 flex gap-5 text-xs"><RouterLink :to="`/discover/item/${encodeURIComponent(paper.id)}`" class="text-accent underline">详情、收藏与备注</RouterLink><a :href="safeExternalUrl(paper.url)" target="_blank" rel="noopener noreferrer" class="text-stone-500 underline">原始出处 ↗</a></div>
        </article>
        <nav v-if="pages>1" aria-label="论文分页" class="mt-6 flex items-center justify-between text-sm"><button :disabled="page===1" class="border px-4 py-2 disabled:opacity-30" @click="page--">上一页</button><span>{{ page }} / {{ pages }}</span><button :disabled="page>=pages" class="border px-4 py-2 disabled:opacity-30" @click="page++">下一页</button></nav>
      </section>
    </template>
    </div>
    </details>
  </div>
</template>
