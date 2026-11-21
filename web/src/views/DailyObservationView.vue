<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getICObservations } from '../api/briefing'
import PublishedObservation from '../components/PublishedObservation.vue'
import ObservationArchive from '../components/ObservationArchive.vue'

const route = useRoute()
const day = computed(() => typeof route.query.day === 'string' ? route.query.day : undefined)
const version = computed(() => typeof route.query.version === 'string' ? route.query.version : undefined)
const data = ref<Awaited<ReturnType<typeof getICObservations>> | null>(null)
const loading = ref(true)
const error = ref('')
let controller: AbortController | undefined
let refreshTimer: ReturnType<typeof setInterval> | undefined

function reportLink(date?: string, selectedVersion?: string) {
  return { name: 'home', query: { view: 'daily', day: date, version: selectedVersion } }
}

async function load(background = false) {
  controller?.abort()
  const request = new AbortController()
  controller = request
  if (!background) {
    loading.value = true
    error.value = ''
  }
  try {
    const result = await getICObservations(day.value, request.signal, version.value)
    if (!request.signal.aborted) {
      data.value = result
      error.value = ''
    }
  } catch (cause) {
    if (!request.signal.aborted && !background) error.value = cause instanceof Error ? cause.message : '观察记录暂时无法读取'
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}

watch([day, version], () => void load(), { immediate: true })
onMounted(() => {
  refreshTimer = setInterval(() => {
    if (document.visibilityState === 'visible' && !loading.value) void load(true)
  }, 60000)
})
onBeforeUnmount(() => {
  clearInterval(refreshTimer)
  controller?.abort()
})
</script>

<template>
  <p v-if="loading && !data" role="status" class="py-12 text-center text-sm text-stone-600 dark:text-stone-400">正在读取每日观察…</p>
  <div v-else-if="error" role="alert" class="rounded-lg border border-red-200 p-5 text-sm text-red-700 dark:border-red-900 dark:text-red-300">
    <p>{{ error }}</p>
    <button type="button" class="mt-2 underline" @click="load()">重新读取</button>
  </div>
  <div v-else-if="data" :aria-busy="loading" class="grid items-start gap-6 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
    <PublishedObservation v-if="data.report" :report="data.report" />
    <section v-else class="rounded-lg border border-stone-200 bg-white p-5 dark:border-stone-800 dark:bg-stone-900">
      <p class="text-xs text-stone-600 dark:text-stone-400">{{ data.selected_day }}</p>
      <h3 class="mt-2 font-serif text-xl font-bold">{{ data.selected_day===data.today ? '今日观察尚未发布' : '这一天没有已保存的观察' }}</h3>
      <div class="mt-3 flex flex-wrap gap-4 text-sm">
        <RouterLink v-if="data.editions[0]" :to="reportLink(data.editions[0].date)" class="text-accent hover:underline">回看最近一期 →</RouterLink>
        <RouterLink :to="{ name: 'discover', query: { content_type: 'news', date_from: data.selected_day, date_to: data.selected_day } }" class="text-accent hover:underline">查看当天已收录新闻 →</RouterLink>
      </div>
    </section>
    <ObservationArchive :editions="data.editions" :versions="data.versions" :selected-day="data.selected_day"
      :selected-version="data.report ? data.report.id || 'original' : null" :latest-day="data.today" />
  </div>
</template>
