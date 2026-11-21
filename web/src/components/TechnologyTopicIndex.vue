<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getTechnologyTopics } from '../api/ic-editor'

const props = defineProps<{ compact?: boolean }>()
const result = ref<Awaited<ReturnType<typeof getTechnologyTopics>> | null>(null)
const error = ref('')
const controller = new AbortController()
const active = computed(() => (result.value?.topics || []).filter(topic => topic.status === 'active' && !topic.established))
const past = computed(() => (result.value?.topics || []).filter(topic => topic.status === 'history'))
const recentSince = computed(() => {
  const asOf = result.value?.as_of
  if (asOf) return new Date(Date.parse(asOf) - 6 * 86400000).toISOString().slice(0, 10)
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(Date.now() - 6 * 86400000)
})
const current = computed(() => props.compact
  ? active.value.filter(topic => topic.latest_event && topic.latest_event.date >= recentSince.value).slice(0, 4)
  : active.value)
const lastRun = computed(() => result.value?.runs[0])

function topicLink(id: string) {
  return { name: 'ic-technology-topic', params: { topicId: id } }
}

async function load() {
  error.value = ''
  try { result.value = await getTechnologyTopics(controller.signal) }
  catch (cause) {
    if (!controller.signal.aborted) error.value = cause instanceof Error ? cause.message : '读取专题失败'
  }
}
onMounted(load)
onBeforeUnmount(() => controller.abort())
</script>

<template>
  <section v-if="!compact || current.length || error" :id="compact ? undefined : 'tracked-topics'"
    class="space-y-4 border-stone-200 dark:border-stone-800"
    :class="compact ? 'mb-7 border-b pb-5' : 'mt-8 border-t pt-5'" aria-labelledby="tracked-topic-heading">
    <div class="flex flex-wrap items-baseline justify-between gap-2">
      <h3 id="tracked-topic-heading" class="font-serif text-xl font-semibold">{{ compact ? '近期专题进展' : '跟踪专题' }}</h3>
      <RouterLink v-if="compact" :to="{ name: 'ic-exploration', hash: '#tracked-topics' }" class="text-sm text-accent hover:underline">查看跟踪专题 →</RouterLink>
    </div>
    <p v-if="error" role="alert" class="text-sm text-stone-600 dark:text-stone-300">{{ error }} <button type="button" class="underline" @click="load">重试</button></p>
    <p v-else-if="result && !active.length" class="text-sm text-stone-600 dark:text-stone-300">暂无跟踪专题。</p>
    <p v-if="!compact && lastRun?.status === 'failed'" class="text-xs text-stone-600 dark:text-stone-400">最近一次专题整理失败。{{ lastRun.error }}</p>
    <ul v-if="current.length" class="grid gap-3 sm:grid-cols-2">
      <li v-for="topic in current" :key="topic.id" class="min-w-0 rounded-lg border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
        <h4 class="font-semibold">{{ topic.name }}</h4>
        <div v-if="topic.latest_event" class="mt-2 min-w-0">
          <p class="text-xs text-stone-600 dark:text-stone-400">{{ topic.latest_event.date }}<template v-if="topic.latest_event.sources[0]"> · {{ topic.latest_event.sources[0] }}</template></p>
          <p class="mt-1 break-words text-sm font-medium leading-6">{{ topic.latest_event.title }}</p>
          <p v-if="!compact && topic.latest_event.summary" class="mt-1 line-clamp-2 break-words text-sm leading-6 text-stone-700 dark:text-stone-300">{{ topic.latest_event.summary }}</p>
        </div>
        <p v-if="topic.follow_up" class="mt-2 line-clamp-2 break-words text-sm leading-6 text-stone-600 dark:text-stone-400">{{ topic.follow_up }}</p>
        <RouterLink :to="topicLink(topic.id)" class="mt-2 inline-block text-sm font-medium text-accent hover:underline">{{ topic.evaluation_status ? '查看评价、进展与出处 →' : '查看进展记录与出处 →' }}</RouterLink>
      </li>
    </ul>
    <template v-if="!compact">
      <details v-if="past.length" class="rounded-lg border border-stone-200 px-4 py-3 dark:border-stone-800">
        <summary class="cursor-pointer text-sm font-semibold">历史专题（{{ past.length }}）</summary>
        <ul class="mt-2 space-y-2 text-sm">
          <li v-for="topic in past" :key="topic.id">
            <RouterLink :to="topicLink(topic.id)" class="text-accent hover:underline">{{ topic.name }} →</RouterLink>
            <span class="ml-2 text-xs text-stone-600 dark:text-stone-400">最近进展 {{ topic.latest_progress }}</span>
          </li>
        </ul>
      </details>
    </template>
  </section>
</template>
