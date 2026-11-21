<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getICBriefing } from '../api/briefing'
import type { ICBriefing, Technology } from '../briefing-types'
import BriefingSources from './BriefingSources.vue'
import TopicEvaluationCard from './TopicEvaluationCard.vue'
import TechnologyCard from './TechnologyCard.vue'
import TechnologyTopicIndex from './TechnologyTopicIndex.vue'
import { IS_STATIC } from '../static-mode'

const props = withDefaults(defineProps<{ topicMode?: boolean }>(), { topicMode: false })
const route = useRoute(), router = useRouter()
const days = computed(() => route.query.days === '7' ? 7 : 30)
const data = ref<ICBriefing | null>(null), loading = ref(true), error = ref('')
const track = computed(() => ['ai_for_ic', 'ic_for_ai'].includes(String(route.query.track)) ? String(route.query.track) : 'all')
let controller: AbortController | undefined
const byId = computed(() => Object.fromEntries((data.value?.technologies || []).map(t => [t.id, t])))
const eventsById = computed(() => Object.fromEntries((data.value?.events || []).map(event => [event.id, event])))
const hotspots = computed(() => (data.value?.event_attention_order || []).map(id => eventsById.value[id]!))
const importance = computed(() => (data.value?.importance_order || []).map(id => byId.value[id]!))
const ranked = computed(() => data.value?.importance_entries || importance.value.map(technology => ({
  id: technology.id, name: technology.name, score: technology.importance_score, rank: technology.importance_rank,
  caption: technology.tagline, automatic: false,
})))
const showAllHotspots = ref(IS_STATIC)
const showAllTechnologies = ref(true)
const previewCount = 3
const hotspotPreviewCount = 8
const visibleHotspots = computed(() => showAllHotspots.value ? hotspots.value : hotspots.value.slice(0, hotspotPreviewCount))
const visibleImportance = computed(() => showAllTechnologies.value ? ranked.value : ranked.value.slice(0, previewCount))
const catalogById = computed(() => new Map((data.value?.topic_catalog?.topics || []).map(topic => [topic.id, topic])))
const availableTopics = computed(() => importance.value
  .filter(t => (catalogById.value.get(t.id)?.status || 'active') === 'active' || t.id === route.query.technology)
  .map(t => ({...t, name: catalogById.value.get(t.id)?.name || t.name})))
const filtered = computed(() => availableTopics.value.filter(t => track.value === 'all' || t.track === track.value))
const selected = computed(() => filtered.value.find(t => t.id === route.query.technology) || filtered.value[0])
const selectedCatalogTopic = computed(() => selected.value && catalogById.value.get(selected.value.id))
const replacementTopic = computed(() => byId.value[selectedCatalogTopic.value?.merged_into || ''])
const tracks = [
  { id: 'all', name: '全部技术' },
  { id: 'ai_for_ic', name: 'AI用于芯片设计' },
  { id: 'ic_for_ai', name: '芯片用于AI计算' },
]
function topicLink(technology: Technology) { return { path: '/explore/ic', query: { technology: technology.id, days: String(days.value), ...(track.value !== 'all' ? { track: track.value } : {}) } } }
function importanceLink(identity: string, automatic: boolean) {
  return automatic ? { name: 'ic-technology-topic', params: { topicId: identity } } : topicLink(byId.value[identity]!)
}
function selectTechnology(event: Event) {
  const technology = filtered.value.find(t => t.id === (event.target as HTMLSelectElement).value)
  if (technology) void router.push(topicLink(technology))
}
function setDays(value: number) { void router.replace({ path: route.path, query: { ...route.query, days: String(value) } }) }
function setTrack(value: string) {
  const choices = availableTopics.value.filter(t => value === 'all' || t.track === value)
  const technology = choices.find(t => t.id === route.query.technology) || choices[0]
  void router.replace({ path: route.path, query: { days: String(days.value), ...(technology ? { technology: technology.id } : {}), ...(value !== 'all' ? { track: value } : {}) } })
}
async function load() {
  controller?.abort()
  const requestController = new AbortController()
  controller = requestController
  loading.value = true; error.value = ''
  try { const result = await getICBriefing(days.value, requestController.signal, props.topicMode); if (!requestController.signal.aborted) data.value = result }
  catch (reason) { if (!requestController.signal.aborted) error.value = reason instanceof Error ? reason.message : '暂时无法读取技术观察' }
  finally { if (!requestController.signal.aborted) loading.value = false }
}
watch(days, load, { immediate: true })
let refreshTimer: number | undefined
onMounted(() => {
  if (!props.topicMode && !IS_STATIC) {
    refreshTimer = window.setInterval(() => {
      if (!loading.value && !document.hidden) void load()
    }, 60_000)
  }
})
onBeforeUnmount(() => {
  controller?.abort()
  window.clearInterval(refreshTimer)
})
</script>

<template>
  <div>
    <header v-if="props.topicMode" class="mb-6 flex flex-wrap items-end justify-between gap-3 border-b border-stone-300 pb-5 dark:border-stone-700">
      <h2 class="font-serif text-3xl font-bold tracking-tight sm:text-4xl">技术专题与评价</h2>
      <div class="flex flex-wrap gap-x-4 gap-y-2 text-sm font-medium text-accent">
        <RouterLink v-if="!IS_STATIC" :to="{ query: route.query, hash: '#tracked-topics' }" class="hover:underline">查看跟踪专题 ↓</RouterLink>
        <RouterLink to="/" class="hover:underline">返回技术观察</RouterLink>
      </div>
    </header>
    <p v-if="loading && !data" role="status" class="border border-dashed border-stone-300 p-10 text-center text-sm text-stone-500 dark:border-stone-700">正在读取技术观察与排名依据…</p>
    <div v-else-if="error" role="alert" class="border border-red-200 p-6 text-sm text-red-700 dark:text-red-300"><p>{{ error }}</p><button class="mt-3 underline" @click="load">重新读取</button></div>
    <div v-else-if="data" :aria-busy="loading">
      <template v-if="!props.topicMode">
        <div class="grid items-start gap-5 md:grid-cols-2">
          <section class="min-w-0 rounded-lg border border-stone-200 bg-white dark:border-stone-700 dark:bg-stone-900" aria-labelledby="attention-heading">
            <div class="border-b border-stone-200 px-5 py-4 dark:border-stone-700">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <h3 id="attention-heading" class="font-serif text-xl font-bold">热点关注度榜</h3>
                <div class="inline-flex rounded-md bg-stone-100 p-0.5 dark:bg-stone-800" role="group" aria-label="关注度统计窗口">
                  <button v-for="value in [7,30]" :key="value" type="button" :aria-pressed="data.window.days===value" class="rounded px-3 py-1.5 text-xs" :class="data.window.days===value ? 'bg-white font-semibold text-stone-900 shadow-sm dark:bg-stone-700 dark:text-white' : 'text-stone-600 dark:text-stone-300'" @click="setDays(value)">{{ value }}天</button>
                </div>
              </div>
              <p class="mt-1 text-xs leading-5 text-stone-600 dark:text-stone-400">近期事件与报道议题 · {{ data.window.date_from.slice(5) }} 至 {{ data.window.date_to.slice(5) }}</p>
            </div>
            <ol v-if="hotspots.length" id="hotspot-list" class="divide-y divide-stone-100 px-5 dark:divide-stone-800">
              <li v-for="event in visibleHotspots" :key="event.id">
                <details class="group">
                  <summary class="flex cursor-pointer list-none items-start gap-3 py-4 [&::-webkit-details-marker]:hidden">
                    <span class="w-6 shrink-0 text-lg font-semibold tabular-nums text-accent">{{ event.attention_rank }}</span>
                    <span class="min-w-0 flex-1">
                      <span class="block text-sm font-semibold leading-6 group-hover:text-accent">{{ event.title }}</span>
                      <span class="mt-0.5 block text-xs leading-5 text-stone-600 dark:text-stone-400">{{ event.attention.source_count }} 家媒体 · 最近报道 {{ event.attention.latest_reported_at?.slice(5) }}</span>
                    </span>
                    <span class="text-stone-500 group-open:rotate-90" aria-hidden="true">›</span>
                  </summary>
                  <div class="mb-4 ml-9 space-y-3">
                    <p v-if="event.occurred_at" class="text-xs text-stone-600 dark:text-stone-400">事件或披露日期 {{ event.occurred_at }}</p>
                    <BriefingSources :ids="event.attention.source_ids" :sources="data.sources" :event-id="event.id" />
                    <div class="flex flex-wrap gap-x-3 gap-y-1 text-xs">
                      <RouterLink v-for="technologyId in event.technology_ids" :key="technologyId" :to="topicLink(byId[technologyId]!)" class="text-accent hover:underline">专题 · {{ byId[technologyId]!.name }} →</RouterLink>
                      <template v-for="topicId in event.tracked_topic_ids" :key="topicId">
                        <RouterLink v-if="catalogById.has(topicId)" :to="{ name: 'ic-technology-topic', params: { topicId } }" class="text-accent hover:underline">专题 · {{ catalogById.get(topicId)?.name }} →</RouterLink>
                      </template>
                    </div>
                  </div>
                </details>
              </li>
            </ol>
            <p v-else class="p-5 text-sm text-stone-600 dark:text-stone-400">这段时间没有符合条件的媒体报道。</p>
            <div v-if="hotspots.length > hotspotPreviewCount" class="border-t border-stone-200 px-5 py-3 dark:border-stone-700">
              <button type="button" :aria-expanded="showAllHotspots" aria-controls="hotspot-list" class="text-sm font-medium text-accent hover:underline" @click="showAllHotspots=!showAllHotspots">{{ showAllHotspots ? '收起热点' : `展开全部热点（${hotspots.length}）` }}</button>
            </div>
          </section>
          <section class="min-w-0 rounded-lg border border-stone-200 bg-white dark:border-stone-700 dark:bg-stone-900" aria-labelledby="importance-heading">
            <div class="border-b border-stone-200 px-5 py-4 dark:border-stone-700">
              <div class="flex min-h-7 flex-wrap items-center justify-between gap-2"><h3 id="importance-heading" class="font-serif text-xl font-bold">技术重要性榜</h3><span class="text-xs text-stone-600 dark:text-stone-400">初步判断</span></div>
              <p class="mt-1 text-xs leading-5 text-stone-600 dark:text-stone-400">瓶颈价值、影响范围、带动作用 · 满分 15</p>
            </div>
            <ol id="importance-list" class="divide-y divide-stone-100 px-5 dark:divide-stone-800">
              <li v-for="technology in visibleImportance" :key="technology.id">
                <RouterLink :to="importanceLink(technology.id, technology.automatic)" class="group flex items-start gap-3 py-4">
                  <span class="w-5 shrink-0 text-lg font-semibold tabular-nums text-accent">{{ technology.rank }}</span>
                  <div class="min-w-0 flex-1"><p class="text-sm font-semibold leading-6 group-hover:text-accent">{{ technology.name }}</p><p class="mt-0.5 line-clamp-2 text-xs leading-5 text-stone-600 dark:text-stone-400">{{ technology.caption }}</p></div>
                  <span class="shrink-0 text-sm font-semibold tabular-nums">{{ technology.score }} 分</span>
                </RouterLink>
              </li>
            </ol>
            <div class="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-t border-stone-200 px-5 py-3 dark:border-stone-700">
              <button v-if="ranked.length > previewCount" type="button" :aria-expanded="showAllTechnologies" aria-controls="importance-list" class="text-sm font-medium text-accent hover:underline" @click="showAllTechnologies=!showAllTechnologies">{{ showAllTechnologies ? '收起技术排行' : `展开全部技术（${ranked.length}）` }}</button>
              <RouterLink :to="{path:'/explore/ic',query:{days:String(days)}}" class="text-sm font-medium text-accent hover:underline">浏览技术专题 →</RouterLink>
            </div>
          </section>
        </div>
      </template>
      <template v-else>
        <div class="grid items-start gap-5 md:grid-cols-[12rem_minmax(0,1fr)] xl:grid-cols-[14rem_minmax(0,1fr)]">
          <div class="space-y-3">
            <div class="grid gap-2 sm:grid-cols-2 md:grid-cols-1">
              <div>
                <label for="briefing-track" class="block text-xs font-medium text-stone-600 dark:text-stone-400">研究主线</label>
                <select id="briefing-track" :value="track" class="mt-1 block w-full rounded-md border border-stone-200 bg-white px-3 py-2 text-sm text-stone-800 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-200" @change="setTrack(($event.target as HTMLSelectElement).value)">
                  <option v-for="option in tracks" :key="option.id" :value="option.id">{{ option.name }}</option>
                </select>
              </div>
              <div class="md:hidden">
                <label for="briefing-technology" class="block text-xs font-medium text-stone-600 dark:text-stone-400">技术方向</label>
                <select id="briefing-technology" :value="selected?.id" class="mt-1 block w-full rounded-md border border-stone-200 bg-white px-3 py-2 text-sm text-stone-800 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-200" @change="selectTechnology">
                  <option v-for="technology in filtered" :key="technology.id" :value="technology.id">{{ technology.name }}</option>
                </select>
              </div>
            </div>
            <nav class="hidden space-y-1 md:block" aria-label="技术方向">
              <RouterLink v-for="technology in filtered" :key="technology.id" :to="topicLink(technology)" :aria-current="selected?.id===technology.id ? 'page' : undefined" class="block rounded-md px-3 py-2.5 text-sm leading-5" :class="selected?.id===technology.id ? 'bg-orange-50 font-semibold text-accent dark:bg-orange-950/40' : 'hover:bg-stone-100 dark:hover:bg-stone-800'">{{ technology.name }}</RouterLink>
            </nav>
          </div>
          <div v-if="selected" class="min-w-0">
            <p v-if="selectedCatalogTopic?.status==='paused' || selectedCatalogTopic?.status==='merged'" class="mb-3 text-sm leading-6 text-stone-600 dark:text-stone-400">
              {{ selectedCatalogTopic.status==='paused' ? '这个专题已暂停跟踪，以下是此前保存的评价。' : '这个专题已合并，以下是此前保存的评价。' }}
              <RouterLink v-if="replacementTopic" :to="topicLink(replacementTopic)" class="ml-2 text-accent hover:underline">查看合并后的专题 →</RouterLink>
            </p>
            <RouterLink v-if="!IS_STATIC" :to="{ name: 'ic-technology-topic', params: { topicId: selected.id } }" class="mb-3 inline-block text-sm font-medium text-accent hover:underline">查看专题进展记录 →</RouterLink>
            <template v-if="data.evaluations?.[selected.id]">
              <TopicEvaluationCard :evaluation="data.evaluations[selected.id]" />
              <details class="mt-4 text-sm">
                <summary class="cursor-pointer font-medium text-accent">查看此前评价与所引资料</summary>
                <TechnologyCard :key="selected.id" class="mt-3" :technology="selected" :briefing="data" @change-days="setDays" />
              </details>
            </template>
            <TechnologyCard v-else :key="selected.id" :technology="selected" :briefing="data" @change-days="setDays" />
          </div>
        </div>
      </template>
    </div>
    <TechnologyTopicIndex v-if="props.topicMode && !IS_STATIC" />
  </div>
</template>
