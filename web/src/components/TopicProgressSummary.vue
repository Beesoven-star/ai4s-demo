<script setup lang="ts">
import { computed } from 'vue'
import type { TechnologyTopicDetail } from '../api/ic-editor'

const props = defineProps<{ topic: TechnologyTopicDetail }>()
const recent = computed(() => props.topic.events.slice(0, 3).map(event => {
  const changes = event.stage_changes || []
  const latest = changes[changes.length - 1]
  return latest ? {
    ...event, date: latest.date, summary: latest.summary, stage: latest.to_stage, boundary: latest.boundary,
  } : event
}))

function preview(text: string, limit: number) {
  if (text.length <= limit) return text
  const leading = text.slice(0, limit)
  const end = Math.max(leading.lastIndexOf('。'), leading.lastIndexOf('！'), leading.lastIndexOf('？'))
  return end >= limit / 2 ? leading.slice(0, end + 1) : `${leading.trimEnd()}…`
}
</script>

<template>
  <section aria-labelledby="topic-changes" class="my-7">
    <p v-if="topic.overview" class="mb-5 border-l-2 border-accent pl-4 text-sm leading-7 text-stone-700 dark:text-stone-300 sm:text-base">
      {{ topic.overview }}
    </p>
    <div class="overflow-hidden rounded-lg border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
      <div class="grid gap-x-6 bg-stone-50 px-4 py-3 dark:bg-stone-800 md:grid-cols-2 md:px-5">
        <h3 id="topic-changes" class="font-semibold">近期实质变化</h3>
        <p class="hidden text-sm font-semibold md:block">证据到哪一步</p>
      </div>
      <p v-if="!topic.events.length" class="p-4 text-sm text-stone-600 dark:text-stone-400">暂无可显示的进展。</p>
      <ol v-else class="divide-y divide-stone-200 dark:divide-stone-800">
        <li v-for="change in recent" :key="change.id" class="grid gap-3 p-4 md:grid-cols-2 md:gap-x-6 md:p-5">
          <div class="min-w-0">
            <time :datetime="change.date" class="text-xs tabular-nums text-stone-600 dark:text-stone-400">{{ change.date }}</time>
            <h4 class="mt-1 font-semibold leading-6">{{ change.title }}</h4>
            <p v-if="change.summary" class="mt-1 text-sm leading-6 text-stone-700 dark:text-stone-300">{{ preview(change.summary, 120) }}</p>
          </div>
          <div class="min-w-0 border-l-2 border-stone-200 pl-3 dark:border-stone-700 md:border-0 md:pl-0" role="group" aria-label="证据到哪一步">
            <p v-if="change.stage" class="text-sm font-semibold text-stone-800 dark:text-stone-200">{{ change.stage }}</p>
            <p v-if="change.boundary" class="mt-1 text-sm leading-6 text-stone-700 dark:text-stone-300">{{ preview(change.boundary, 100) }}</p>
            <p v-if="change.sources.length" class="mt-2 text-xs text-stone-600 dark:text-stone-400">{{ change.sources.length }} 条相关出处</p>
          </div>
        </li>
      </ol>
    </div>
  </section>

  <section v-if="topic.question || topic.follow_up" aria-label="技术问题与后续验证" class="grid gap-4 rounded-lg bg-stone-100 px-4 py-4 dark:bg-stone-800/70 sm:grid-cols-2 md:px-5">
    <div v-if="topic.question"><h3 class="font-semibold">技术问题</h3><p class="mt-2 text-sm leading-6 text-stone-700 dark:text-stone-300">{{ topic.question }}</p></div>
    <div v-if="topic.follow_up"><h3 class="font-semibold">接下来关注</h3><p class="mt-2 text-sm leading-6 text-stone-700 dark:text-stone-300">{{ topic.follow_up }}</p></div>
  </section>
</template>
