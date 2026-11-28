<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getTechnologyTopic, type TechnologyEvent, type TechnologyTopicDetail } from '../api/ic-editor'
import { newsGenreLabel, readingBasisLabel, safeExternalUrl } from '../api/discovery'
import { unreadTopicEvents, useTopicFollow } from '../composables/useTopicFollow'

const props = defineProps<{ topicId: string }>()
const topic = ref<TechnologyTopicDetail | null>(null)
const error = ref('')
const unreadIds = ref<string[]>([])
const route = useRoute()
const { followed, seen, error: followError, setFollowed, markViewed } = useTopicFollow(() => props.topicId)
let controller: AbortController | undefined

async function load() {
  controller?.abort()
  const request = new AbortController()
  controller = request
  error.value = ''
  topic.value = null
  try {
    const data = await getTechnologyTopic(props.topicId, request.signal)
    if (!request.signal.aborted) topic.value = data
  }
  catch (cause) {
    if (!request.signal.aborted) error.value = cause instanceof Error ? cause.message : '读取专题失败'
  }
}
watch(() => props.topicId, load, { immediate: true })
watch([topic, followed], ([record, isFollowed]) => {
  unreadIds.value = []
  if (!record || record.id !== props.topicId || !isFollowed) return
  unreadIds.value = unreadTopicEvents(record.events, seen.value).map(event => event.id)
  markViewed(record.events)
})
watch([topic, () => route.query.progress], async ([record, progress]) => {
  if (typeof progress !== 'string' || !record?.events.some(event => event.id === progress)) return
  await nextTick()
  if (topic.value !== record || route.query.progress !== progress) return
  const target = document.getElementById(`topic-progress-${progress}`)
  target?.focus({ preventScroll: true })
  target?.scrollIntoView({ block: 'start' })
})

function evidenceUrl(event: TechnologyEvent, sourceId: string) {
  const source = event.sources.find(row => row.id === sourceId)
  return source ? safeExternalUrl(source.url) : null
}

onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <div class="mx-auto max-w-4xl">
    <RouterLink :to="{ name: 'ic-exploration', query: { technology: props.topicId, days: route.query.days, category: route.query.category } }" class="text-sm text-accent hover:underline">← 返回专题概览</RouterLink>
    <p v-if="error" role="alert" class="py-8">{{ error }} <button type="button" class="underline" @click="load">重试</button></p>
    <p v-else-if="!topic" role="status" class="py-8 text-sm">正在读取专题…</p>
    <template v-else>
      <header class="mb-6 mt-4 border-b border-stone-300 pb-5 dark:border-stone-700">
        <p class="text-xs text-stone-600 dark:text-stone-400">
          {{ topic.status === 'active' ? '跟踪中' : topic.status === 'history' ? '历史专题' : '已并入' }}
          <template v-if="topic.reviewed_through"> · 整理至 <time :datetime="topic.reviewed_through">{{ topic.reviewed_through }}</time></template>
          <template v-else-if="topic.latest_progress"> · 最近进展 {{ topic.latest_progress }}</template>
        </p>
        <div class="mt-2 flex flex-wrap items-center justify-between gap-4">
          <h2 class="min-w-0 break-words font-serif text-3xl font-bold sm:text-4xl">{{ topic.name }}</h2>
          <div class="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
            <button type="button" :aria-pressed="followed" aria-label="关注专题"
              class="rounded-md border px-4 py-2 font-medium transition-colors"
              :class="followed ? 'border-accent text-accent hover:bg-orange-50 dark:hover:bg-orange-950/40' : 'border-transparent bg-accent text-white hover:opacity-90'"
              @click="setFollowed(!followed, topic.events)">{{ followed ? '已关注' : '关注专题' }}</button>
            <RouterLink v-if="followed" :to="{ name: 'library' }" class="text-accent hover:underline">我的关注 →</RouterLink>
          </div>
        </div>
        <p v-if="followError" role="alert" class="mt-2 text-sm text-red-700 dark:text-red-400">{{ followError }}</p>
        <RouterLink v-if="topic.merged_into" :to="{ name: 'ic-technology-topic', params: { topicId: topic.merged_into } }"
          class="mt-3 inline-block text-sm text-accent hover:underline">前往合并后的专题 →</RouterLink>
      </header>
      <section aria-labelledby="topic-events">
        <div class="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h3 id="topic-events" class="font-serif text-xl font-bold">{{ topic.status === 'history' ? '历史时间线与出处' : '时间线与出处' }}</h3>
          <p v-if="topic.events.length" class="text-sm text-stone-600 dark:text-stone-400">共 {{ topic.events.length }} 条进展</p>
        </div>
        <p v-if="!topic.events.length" class="text-sm text-stone-600 dark:text-stone-400">暂无可显示的进展。</p>
        <ol v-else class="divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white dark:divide-stone-800 dark:border-stone-800 dark:bg-stone-900">
          <li v-for="event in topic.events" :id="'topic-progress-' + event.id" :key="event.id" tabindex="-1"
            class="scroll-mt-4 p-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent sm:p-5">
            <p class="text-xs text-stone-600 dark:text-stone-400"><time :datetime="event.date">{{ event.date }}</time><span v-if="unreadIds.includes(event.id)" class="ml-2 font-semibold text-accent">新进展</span></p>
            <h4 class="mt-1 break-words font-semibold">{{ event.title }}</h4>
            <p v-if="event.stage" class="mt-1 text-sm font-medium text-stone-700 dark:text-stone-300">{{ event.stage }}</p>
            <p v-if="event.summary" class="mt-2 text-sm leading-7 text-stone-700 dark:text-stone-300">{{ event.summary }}</p>
            <p v-if="event.boundary" class="mt-1 text-sm leading-6 text-stone-600 dark:text-stone-400">{{ event.boundary }}</p>
            <ol v-if="event.stage_changes?.length" aria-label="阶段变化" class="mt-3 space-y-3 border-l-2 border-accent pl-3">
              <li v-for="change in event.stage_changes" :key="change.id">
                <p class="text-xs text-stone-600 dark:text-stone-400"><time :datetime="change.date">{{ change.date }}</time> · {{ change.from_stage }} → {{ change.to_stage }}</p>
                <p v-if="change.summary" class="mt-1 text-sm leading-6">{{ change.summary }}</p>
                <p v-if="change.boundary" class="text-xs leading-5 text-stone-600 dark:text-stone-400">{{ change.boundary }}</p>
                <details class="mt-1 text-xs leading-5">
                  <summary class="w-fit cursor-pointer text-accent">查看阶段变化依据</summary>
                  <blockquote class="mt-1 break-words">{{ change.evidence }}</blockquote>
                  <a v-if="evidenceUrl(event, change.source_id)" :href="evidenceUrl(event, change.source_id)"
                    target="_blank" rel="noopener noreferrer" class="text-accent hover:underline">打开来源 ↗</a>
                </details>
              </li>
            </ol>
            <ul class="mt-2 space-y-1 text-xs leading-5" aria-label="相关报道和文献">
              <li v-for="source in event.sources" :key="source.id">
                <a v-if="safeExternalUrl(source.url)" :href="safeExternalUrl(source.url)" target="_blank" rel="noopener noreferrer" class="break-words text-accent hover:underline">{{ source.title }} ↗</a>
                <span v-else>{{ source.title }}</span>
                <span class="ml-2 text-stone-600 dark:text-stone-400">{{ source.source }}<template v-if="source.published_at"> · {{ source.published_at }}</template><template v-if="readingBasisLabel(source.reading_basis, source.content_type)"> · {{ readingBasisLabel(source.reading_basis, source.content_type) }}</template><template v-if="newsGenreLabel(source.news_genre)"> · {{ newsGenreLabel(source.news_genre) }}</template></span>
                <details v-if="source.verified_excerpt" class="mt-1">
                  <summary class="w-fit cursor-pointer text-accent">查看所引片段</summary>
                  <blockquote class="mt-1 break-words leading-5 text-stone-600 dark:text-stone-400">{{ source.verified_excerpt }}</blockquote>
                </details>
              </li>
            </ul>
          </li>
        </ol>
      </section>
    </template>
  </div>
</template>
