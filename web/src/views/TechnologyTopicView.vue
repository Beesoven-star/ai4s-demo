<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { getTechnologyTopic, type TechnologyTopicDetail } from '../api/ic-editor'
import TopicEvaluationCard from '../components/TopicEvaluationCard.vue'
import { newsGenreLabel, readingBasisLabel, safeExternalUrl } from '../api/discovery'

const props = defineProps<{ topicId: string }>()
const topic = ref<TechnologyTopicDetail | null>(null)
const error = ref('')
let controller: AbortController | undefined

async function load() {
  controller?.abort()
  const request = new AbortController()
  controller = request
  error.value = ''
  topic.value = null
  try { topic.value = await getTechnologyTopic(props.topicId, request.signal) }
  catch (cause) {
    if (!request.signal.aborted) error.value = cause instanceof Error ? cause.message : '读取专题失败'
  }
}
watch(() => props.topicId, load, { immediate: true })
onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <div class="mx-auto max-w-4xl">
    <RouterLink :to="{ name: 'ic-exploration' }" class="text-sm text-accent hover:underline">← 全部技术专题</RouterLink>
    <p v-if="error" role="alert" class="py-8">{{ error }} <button type="button" class="underline" @click="load">重试</button></p>
    <p v-else-if="!topic" role="status" class="py-8 text-sm">正在读取专题…</p>
    <template v-else>
      <header class="mb-6 mt-4 border-b border-stone-300 pb-5 dark:border-stone-700">
        <p class="text-xs text-stone-600 dark:text-stone-400">{{ topic.status === 'active' ? '跟踪中' : topic.status === 'history' ? '历史专题' : '已并入' }}<template v-if="topic.latest_progress"> · 最近进展 {{ topic.latest_progress }}</template></p>
        <h2 class="mt-2 break-words font-serif text-3xl font-bold sm:text-4xl">{{ topic.name }}</h2>
        <RouterLink v-if="topic.merged_into" :to="{ name: 'ic-technology-topic', params: { topicId: topic.merged_into } }"
          class="mt-3 inline-block text-sm text-accent hover:underline">前往合并后的专题 →</RouterLink>
        <p v-if="topic.overview" class="mt-4 text-sm leading-7 text-stone-700 dark:text-stone-300">{{ topic.overview }}</p>
        <RouterLink v-if="topic.established && topic.seeded && !topic.evaluation" :to="{ name: 'ic-exploration', query: { technology: topic.id } }" class="mt-3 inline-block text-sm text-accent hover:underline">查看技术评价 →</RouterLink>
      </header>
      <section v-if="topic.question || topic.follow_up" class="grid gap-4 sm:grid-cols-2" aria-label="技术问题与后续验证">
        <div v-if="topic.question" class="border-l-2 border-accent pl-4"><h3 class="font-semibold">技术问题</h3><p class="mt-1 text-sm leading-6">{{ topic.question }}</p></div>
        <div v-if="topic.follow_up" class="border-l-2 border-stone-300 pl-4 dark:border-stone-700"><h3 class="font-semibold">接下来关注</h3><p class="mt-1 text-sm leading-6">{{ topic.follow_up }}</p></div>
      </section>
      <TopicEvaluationCard v-if="topic.evaluation" :evaluation="topic.evaluation" />
      <section v-if="topic.events.length" class="mt-7" aria-labelledby="topic-events">
        <h3 id="topic-events" class="mb-3 font-serif text-xl font-bold">{{ topic.status === 'history' ? '历史进展' : '进展与资料' }}</h3>
        <ol class="divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white dark:divide-stone-800 dark:border-stone-800 dark:bg-stone-900">
          <li v-for="event in topic.events" :key="event.id" class="p-4 sm:p-5">
            <p class="text-xs text-stone-600 dark:text-stone-400">{{ event.date }}</p>
            <h4 class="mt-1 break-words font-semibold">{{ event.title }}</h4>
            <p class="mt-2 text-sm leading-7 text-stone-700 dark:text-stone-300">{{ event.summary }}</p>
            <p v-if="event.boundary" class="mt-1 text-sm leading-6 text-stone-600 dark:text-stone-400">{{ event.boundary }}</p>
            <ul class="mt-2 space-y-1 text-xs leading-5" aria-label="相关报道和文献">
              <li v-for="source in event.sources" :key="source.id">
                <a v-if="safeExternalUrl(source.url)" :href="safeExternalUrl(source.url)" target="_blank" rel="noopener noreferrer" class="break-words text-accent hover:underline">{{ source.title }} ↗</a>
                <span v-else>{{ source.title }}</span>
                <span class="ml-2 text-stone-600 dark:text-stone-400">{{ source.source }}<template v-if="source.published_at"> · {{ source.published_at }}</template><template v-if="readingBasisLabel(source.reading_basis, source.content_type)"> · {{ readingBasisLabel(source.reading_basis, source.content_type) }}</template><template v-if="newsGenreLabel(source.news_genre)"> · {{ newsGenreLabel(source.news_genre) }}</template></span>
              </li>
            </ul>
          </li>
        </ol>
      </section>
    </template>
  </div>
</template>
