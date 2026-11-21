<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getICBriefing } from '../api/briefing'
import type { ICBriefing, Technology } from '../briefing-types'
import BriefingSources from '../components/BriefingSources.vue'
import TechnologyBriefing from '../components/TechnologyBriefing.vue'
import TechnologyTopicIndex from '../components/TechnologyTopicIndex.vue'
import DailyObservationView from './DailyObservationView.vue'
import PublishedObservation from '../components/PublishedObservation.vue'
import ObservationArchive from '../components/ObservationArchive.vue'
import { getPublishedWeekly } from '../api/ic-editor'
import { workspace } from '../workspace'

type OverviewMode = 'weekly' | 'daily' | 'tracking' | 'rankings'

const route = useRoute()
const router = useRouter()
const views: { id: OverviewMode; label: string; title: string }[] = [
  { id: 'weekly', label: '本周简报', title: '本周技术观察' },
  { id: 'daily', label: '今日观察', title: '今日观察' },
  { id: 'tracking', label: '技术跟踪', title: '技术跟踪' },
  { id: 'rankings', label: '查看排行', title: '热点与技术排行' },
]
const view = computed(() => views.find(option => option.id === route.query.view) || views[0]!)
const edition = ref<ICBriefing | null>(null)
const loading = ref(true)
const error = ref('')
let controller: AbortController | undefined
const weeklyPublication = ref<Awaited<ReturnType<typeof getPublishedWeekly>> | null>(null)
const weeklyDay = computed(() => typeof route.query.day === 'string' ? route.query.day : undefined)
const weeklyVersion = computed(() => typeof route.query.edition === 'string' ? route.query.edition : undefined)
const weeklyLoading = ref(false)
const weeklyError = ref('')
let weeklyController: AbortController | undefined

const technologies = computed(() => new Map(edition.value?.technologies.map(technology => [technology.id, technology])))
const events = computed(() => new Map(edition.value?.events.map(event => [event.id, event])))
const highlights = computed(() => (edition.value?.weekly_highlights || []).flatMap(highlight => {
  const event = events.value.get(highlight.event_id)
  return event?.window_source_ids.length ? [{ ...highlight, event }] : []
}))
const importance = computed(() => (edition.value?.importance_order || []).map(id => technologies.value.get(id)!))
const catalogTopics = computed(() => edition.value?.topic_catalog?.topics || [])
const catalogById = computed(() => new Map(catalogTopics.value.map(topic => [topic.id, topic])))
const storyTopics = computed(() => [...new Set(highlights.value.flatMap(highlight => highlight.event.technology_ids))]
  .map(id => technologies.value.get(id)!))
const tracking = computed(() => importance.value.filter(technology => (catalogById.value.get(technology.id)?.status || 'active') === 'active').map(technology => {
  const event = highlights.value.find(highlight => highlight.event.technology_ids.includes(technology.id))?.event
    || edition.value?.event_attention_order.map(id => events.value.get(id))
      .find(candidate => candidate?.technology_ids.includes(technology.id))
    || technology.attention.event_ids.map(id => events.value.get(id)).find(Boolean)
  return { technology: { ...technology, name: catalogById.value.get(technology.id)?.name || technology.name }, event }
}))
const trackingGroups = computed(() => [
  { id: 'ic_for_ai', label: '为 AI 做芯片' },
  { id: 'ai_for_ic', label: '用 AI 设计芯片' },
].map(group => ({
  ...group,
  entries: tracking.value.filter(entry => entry.technology.track === group.id),
})).filter(group => group.entries.length))

function topicLink(technology: Technology) {
  return { name: 'ic-exploration', query: { technology: technology.id, days: '7' } }
}

function selectView(mode: OverviewMode) {
  if (mode !== view.value.id) {
    void router.push({ name: 'home', query: mode === 'weekly' ? {} : { view: mode } })
  }
}

async function load() {
  controller?.abort()
  const request = new AbortController()
  controller = request
  loading.value = true
  error.value = ''
  try {
    const result = await getICBriefing(7, request.signal, true)
    if (!request.signal.aborted) edition.value = result
  } catch (cause) {
    if (!request.signal.aborted) error.value = cause instanceof Error ? cause.message : '暂时无法读取技术观察'
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}

watch(() => view.value.id, mode => {
  if (mode === 'rankings' || mode === 'daily') controller?.abort()
  else if (!edition.value) void load()
}, { immediate: true })
async function loadWeekly() {
  weeklyController?.abort()
  if (view.value.id !== 'weekly' || workspace.domain !== 'ic') return
  const request = new AbortController()
  weeklyController = request
  weeklyLoading.value = true
  weeklyError.value = ''
  try {
    const result = await getPublishedWeekly(weeklyDay.value, weeklyVersion.value, request.signal)
    if (!request.signal.aborted) weeklyPublication.value = result
  } catch (cause) {
    if (!request.signal.aborted) weeklyError.value = cause instanceof Error ? cause.message : '周报暂时无法读取'
  } finally {
    if (!request.signal.aborted) weeklyLoading.value = false
  }
}

watch([() => view.value.id, weeklyDay, weeklyVersion], loadWeekly, { immediate: true })
onBeforeUnmount(() => {
  controller?.abort()
  weeklyController?.abort()
})
</script>

<template>
  <div>
    <header class="mb-6 border-b border-stone-200 dark:border-stone-800">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 class="font-serif text-3xl font-bold tracking-tight sm:text-4xl">{{ view.title }}</h2>
          <p v-if="view.id==='weekly' && weeklyPublication?.report" class="mt-2 text-sm text-stone-600 dark:text-stone-400">集成电路 · {{ weeklyPublication.report.date_from }} 至 {{ weeklyPublication.report.date }}</p>
          <p v-else-if="edition && view.id==='weekly' && weeklyPublication?.selected_version==='original'" class="mt-2 text-sm text-stone-600 dark:text-stone-400">集成电路 · {{ edition.window.date_from }} 至 {{ edition.window.date_to }}</p>
        </div>
        <div class="flex flex-wrap gap-4 pt-1 text-sm font-medium text-accent">
          <RouterLink to="/discover?content_type=news" class="hover:underline">查看最新资讯 →</RouterLink>
        </div>
      </div>
      <div class="mt-4 flex flex-wrap gap-x-3 gap-y-1" role="group" aria-label="技术观察视图">
        <button v-for="option in views" :key="option.id" type="button" :aria-pressed="view.id===option.id" class="border-b-2 px-2 pb-2.5 pt-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent sm:px-3" :class="view.id===option.id ? 'border-accent font-semibold text-accent' : 'border-transparent text-stone-600 hover:text-accent dark:text-stone-300'" @click="selectView(option.id)">{{ option.label }}</button>
      </div>
    </header>

    <TechnologyTopicIndex v-if="view.id==='tracking'" compact />
    <DailyObservationView v-if="view.id==='daily'" />
    <TechnologyBriefing v-else-if="view.id==='rankings'" />
    <div v-else-if="view.id==='weekly' && workspace.domain==='ic'" :aria-busy="weeklyLoading">
      <div v-if="weeklyError" role="alert" class="rounded-md border border-red-200 p-5 text-sm text-red-700 dark:border-red-900 dark:text-red-300">
        <p>{{ weeklyError }}</p>
        <button type="button" class="mt-2 underline" @click="loadWeekly">重新读取</button>
      </div>
      <p v-else-if="!weeklyPublication" role="status" class="py-12 text-center text-sm text-stone-600 dark:text-stone-400">正在读取周报…</p>
      <div v-else class="grid items-start gap-6 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <PublishedObservation v-if="weeklyPublication.report" :report="weeklyPublication.report" weekly />
        <div v-else-if="weeklyPublication.selected_version==='original'">
          <p v-if="loading" role="status" class="py-12 text-center text-sm text-stone-600 dark:text-stone-400">正在读取原始周报…</p>
          <div v-else-if="error" role="alert" class="rounded-md border border-red-200 p-5 text-sm text-red-700 dark:border-red-900 dark:text-red-300">
            <p>{{ error }}</p>
            <button type="button" class="mt-2 underline" @click="load">重新读取</button>
          </div>
          <div v-else-if="edition" class="space-y-6">
            <section v-if="edition.weekly_story" class="border-l-2 border-accent pl-4 sm:pl-5" aria-labelledby="weekly-question">
              <h3 id="weekly-question" class="font-serif text-2xl font-bold leading-snug sm:text-3xl">{{ edition.weekly_story.question }}</h3>
              <p class="mt-2 max-w-3xl text-sm leading-7 text-stone-700 sm:text-base dark:text-stone-300">{{ edition.weekly_story.overview }}</p>
            </section>
            <section class="min-w-0 divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white dark:divide-stone-800 dark:border-stone-800 dark:bg-stone-900" aria-label="本周技术进展">
              <p v-if="!highlights.length" class="p-5 text-sm text-stone-600 dark:text-stone-400">本期暂无已整理的简报条目。可从「查看排行」浏览已有动态。</p>
              <article v-for="(highlight, index) in highlights" :key="highlight.event_id" class="px-4 py-5 sm:px-6">
                <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                  <span v-if="index === 0" class="font-semibold text-accent">本周重点</span>
                  <span v-if="highlight.event.occurred_at" class="text-stone-600 dark:text-stone-400">披露 {{ highlight.event.occurred_at.slice(5) }}</span>
                  <span v-if="highlight.event.attention.latest_reported_at && highlight.event.attention.latest_reported_at !== highlight.event.occurred_at" class="text-stone-600 dark:text-stone-400">最近报道 {{ highlight.event.attention.latest_reported_at.slice(5) }}</span>
                </div>
                <h4 class="mt-2 break-words font-serif font-bold leading-snug" :class="index === 0 ? 'text-xl sm:text-2xl' : 'text-lg'">{{ highlight.reading_question || highlight.event.title }}</h4>
                <p v-if="highlight.reading_question" class="mt-2 text-sm font-semibold leading-6">{{ highlight.event.title }}</p>
                <p class="mt-2 text-sm leading-6 text-stone-700 dark:text-stone-300">{{ highlight.what_happened }}</p>
                <p class="mt-2 text-sm leading-6 text-stone-700 dark:text-stone-300">{{ highlight.why_it_matters }}</p>
                <details class="mt-3 text-sm">
                  <summary class="w-fit cursor-pointer text-accent hover:underline">报道与原始资料</summary>
                  <p class="mt-2 text-xs leading-6 text-stone-600 dark:text-stone-400">{{ highlight.evidence_stage }}<span v-if="highlight.event.attention.source_count"> · 本期收录 {{ highlight.event.attention.source_count }} 家独立媒体</span></p>
                  <BriefingSources class="mt-3" :ids="highlight.event.source_ids" :sources="edition.sources" :event-id="highlight.event.id" />
                </details>
                <div class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
                  <RouterLink v-for="id in highlight.event.technology_ids" :key="id" :to="topicLink(technologies.get(id)!)" class="text-stone-600 hover:text-accent hover:underline dark:text-stone-400">专题 · {{ technologies.get(id)!.name }} →</RouterLink>
                </div>
              </article>
              <section v-if="edition.weekly_story && highlights.length" class="bg-stone-50 px-4 py-5 sm:px-6 dark:bg-stone-900/70" aria-labelledby="weekly-research">
                <h4 id="weekly-research" class="font-serif text-lg font-bold">本周留下的问题</h4>
                <p class="mt-2 text-sm leading-7 text-stone-700 dark:text-stone-300">{{ edition.weekly_story.research_question }}</p>
              </section>
            </section>
          </div>
        </div>
        <p v-else class="rounded-lg border border-stone-200 p-5 text-sm text-stone-600 dark:border-stone-800 dark:text-stone-400">这一天没有已保存的周报。</p>
        <div class="min-w-0 space-y-6">
          <ObservationArchive weekly :editions="weeklyPublication.editions" :versions="weeklyPublication.versions"
            :selected-day="weeklyPublication.selected_day" :selected-version="weeklyPublication.selected_version"
            :latest-day="weeklyPublication.editions[0]?.date" />
          <aside v-if="weeklyPublication.selected_version==='original' && storyTopics.length" class="min-w-0 border-t-2 border-accent pt-3" aria-labelledby="weekly-topics">
            <h3 id="weekly-topics" class="font-serif text-xl font-bold">沿着本周问题继续读</h3>
            <div class="mt-1 divide-y divide-stone-200 dark:divide-stone-800">
              <article v-for="technology in storyTopics" :key="technology.id" class="py-3">
                <h4 class="font-semibold"><RouterLink :to="topicLink(technology)" class="hover:text-accent hover:underline">{{ technology.name }}</RouterLink></h4>
                <p class="mt-1 text-sm leading-6 text-stone-600 dark:text-stone-400">{{ technology.tagline }}</p>
              </article>
            </div>
            <RouterLink :to="{ name: 'home', query: { view: 'tracking' } }" class="mt-3 inline-block text-sm font-medium text-accent hover:underline">查看全部跟踪方向 →</RouterLink>
          </aside>
        </div>
      </div>
    </div>
    <p v-else-if="loading" role="status" class="py-12 text-center text-sm text-stone-600 dark:text-stone-400">正在读取技术观察…</p>
    <div v-else-if="error" role="alert" class="rounded-md border border-red-200 p-5 text-sm text-red-700 dark:border-red-900 dark:text-red-300">
      <p>{{ error }}</p>
      <button type="button" class="mt-2 underline" @click="load">重新读取</button>
    </div>

    <template v-else-if="edition">
      <div class="space-y-6" aria-label="技术跟踪方向">
        <section v-for="group in trackingGroups" :key="group.id" :aria-labelledby="`tracking-${group.id}`">
          <h3 :id="`tracking-${group.id}`" class="mb-2 font-serif text-xl font-bold">{{ group.label }}</h3>
          <div class="divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white dark:divide-stone-800 dark:border-stone-800 dark:bg-stone-900">
            <article v-for="{ technology, event } in group.entries" :key="technology.id" class="min-w-0 px-4 py-4 sm:px-6">
              <h4 class="font-serif text-lg font-bold"><RouterLink :to="topicLink(technology)" class="hover:text-accent hover:underline">{{ technology.name }}</RouterLink></h4>
              <p class="mt-1 text-sm leading-6 text-stone-700 dark:text-stone-300">{{ technology.tagline }}</p>
              <p class="mt-2 text-sm leading-6 text-stone-600 dark:text-stone-400"><strong class="font-medium text-stone-800 dark:text-stone-200">后续关注</strong>　{{ technology.watch_next.text }}</p>
              <details v-if="event" class="mt-2 text-sm">
                <summary class="w-fit cursor-pointer leading-6 text-accent hover:underline">近期进展 · {{ event.title }}</summary>
                <p class="mt-2 leading-6 text-stone-600 dark:text-stone-400">目前做到哪一步 · {{ technology.maturity }}</p>
                <BriefingSources class="mt-2" :ids="event.source_ids" :sources="edition.sources" :event-id="event.id" />
              </details>
              <p v-else class="mt-2 text-xs text-stone-600 dark:text-stone-400">目前做到哪一步 · {{ technology.maturity }}</p>
            </article>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>
