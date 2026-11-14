<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { localTimeLabel } from '../api/discovery'
import type { DiscoveryRun } from '../discovery-types'

interface CollectionSettings {
  enabled: boolean
  time: string
  lookback_days: number
}

interface CollectionJob {
  id: string
  status: 'running' | 'success' | 'partial' | 'failed' | 'interrupted'
  trigger: 'manual' | 'daily'
  started_at: string
  finished_at: string | null
  window_start: string
  window_end: string
  current_source: string | null
  sources_total: number
  sources_done: number
  runs: DiscoveryRun[]
  inserted: number
  updated: number
  error?: string | null
}

interface CollectionState {
  settings: CollectionSettings
  sources: { id: string; name: string; content_type: 'paper' | 'news' }[]
  relevance: { domain_terms: string[]; method_terms: string[] }
  today: string
  next_run_at: string | null
  job: CollectionJob | null
  available: boolean
}

const emit = defineEmits<{ completed: [] }>()
const state = ref<CollectionState | null>(null)
const dates = reactive({ date_from: '', date_to: '' })
const settings = reactive<CollectionSettings>({ enabled: true, time: '08:00', lookback_days: 7 })
const loadError = ref('')
const actionError = ref('')
const savedMessage = ref('')
const busy = ref(false)
let disposed = false
let timer: ReturnType<typeof setTimeout> | undefined
let pollController: AbortController | undefined
let actionController: AbortController | undefined
let requestVersion = 0
let seenFinishedId = ''

const running = computed(() => state.value?.job?.status === 'running')
const job = computed(() => state.value?.job)
const coverageLimited = computed(() => job.value?.runs.some(run => Boolean(run.coverage_warning)))
const noNewExplanation = computed(() => {
  if (job.value?.status !== 'success' || job.value.inserted !== 0) return ''
  return job.value.runs.some(run => run.found > 0)
    ? '本轮相关候选均已收录，去重后没有新增。'
    : '本轮已读取内容中未筛出匹配候选，请查看各来源结果与覆盖提示。'
})
const jobLabel = computed(() => ({
  running: '正在采集', success: '本轮采集完成', partial: '部分来源未完成',
  failed: '本轮采集失败', interrupted: '上次采集已中断',
})[job.value?.status || 'running'])
const jobTone = computed(() => job.value?.status === 'failed' || job.value?.status === 'interrupted'
  ? 'text-red-600 dark:text-red-400'
  : job.value?.status === 'partial' ? 'text-amber-700 dark:text-amber-400'
    : 'text-accent')

async function requestState(method: 'GET' | 'POST' | 'PUT', signal: AbortSignal, body?: unknown): Promise<CollectionState> {
  const path = method === 'PUT' ? '/api/discovery/collection/settings' : '/api/discovery/collection'
  const response = await fetch(path, {
    method, signal,
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  })
  if (!response.ok) {
    let message = `采集服务请求失败（${response.status}）`
    try {
      const result: { detail?: unknown } = await response.json()
      if (typeof result.detail === 'string') message = result.detail
      else if (Array.isArray(result.detail)) {
        message = result.detail.map((entry: unknown) => entry && typeof entry === 'object' && 'msg' in entry
          ? String(entry.msg) : '采集参数不正确').join('；')
      }
    } catch { /* Keep the useful HTTP status if the body is not JSON. */ }
    throw new Error(message)
  }
  return response.json() as Promise<CollectionState>
}

function applyState(value: CollectionState, resetSettings = false) {
  const firstLoad = state.value === null
  state.value = value
  if (firstLoad) {
    dates.date_to = value.today
    const start = new Date(`${value.today}T00:00:00Z`)
    start.setUTCDate(start.getUTCDate() - 6)
    dates.date_from = start.toISOString().slice(0, 10)
  }
  if (firstLoad || resetSettings) Object.assign(settings, value.settings)
  if (value.job && value.job.status !== 'running' && value.job.id !== seenFinishedId) {
    seenFinishedId = value.job.id
    emit('completed')
  }
}

function schedule(delay?: number) {
  clearTimeout(timer)
  if (!disposed) timer = setTimeout(() => void refresh(), delay ?? (running.value ? 3000 : 30000))
}

async function refresh() {
  if (disposed || busy.value) return
  const version = ++requestVersion
  pollController?.abort()
  pollController = new AbortController()
  try {
    const value = await requestState('GET', pollController.signal)
    if (disposed || version !== requestVersion) return
    applyState(value)
    loadError.value = ''
  } catch (error) {
    if (disposed || version !== requestVersion) return
    loadError.value = error instanceof Error ? error.message : '暂时无法读取采集状态'
  } finally {
    if (!disposed && version === requestVersion) schedule(loadError.value ? 10000 : undefined)
  }
}

function validDay(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

async function act(method: 'POST' | 'PUT', body: unknown) {
  if (busy.value || disposed) return
  busy.value = true
  clearTimeout(timer)
  ++requestVersion
  pollController?.abort()
  actionController = new AbortController()
  actionError.value = ''
  savedMessage.value = ''
  try {
    const value = await requestState(method, actionController.signal, body)
    if (disposed) return
    applyState(value, method === 'PUT')
    loadError.value = ''
    if (method === 'PUT') savedMessage.value = '每日采集设置已保存。'
  } catch (error) {
    if (!disposed) actionError.value = error instanceof Error ? error.message : '操作未完成，请重试'
  } finally {
    busy.value = false
    if (!disposed) schedule(actionError.value ? 3000 : undefined)
  }
}

async function collect() {
  actionError.value = ''
  if (!validDay(dates.date_from) || !validDay(dates.date_to)) {
    actionError.value = '请选择有效的采集开始日期和结束日期。'
    return
  }
  const span = (Date.parse(`${dates.date_to}T00:00:00Z`) - Date.parse(`${dates.date_from}T00:00:00Z`)) / 86400000 + 1
  if (span < 1 || span > 366) {
    actionError.value = '开始日期不能晚于结束日期，单次最多补查 366 天。'
    return
  }
  if (state.value && dates.date_to > state.value.today) {
    actionError.value = '采集结束日期不能晚于今天。'
    return
  }
  await act('POST', { ...dates })
}

async function saveSettings() {
  actionError.value = ''
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(settings.time)
    || !Number.isInteger(settings.lookback_days) || settings.lookback_days < 1 || settings.lookback_days > 30) {
    actionError.value = '请选择有效的每日采集时间和 1 至 30 天的回看范围。'
    return
  }
  await act('PUT', { ...settings })
}

function runLabel(run: DiscoveryRun): string {
  return { success: '完成', no_results: '本轮无匹配', failed: '失败' }[run.status]
}

onMounted(() => void refresh())
onBeforeUnmount(() => {
  disposed = true
  ++requestVersion
  clearTimeout(timer)
  pollController?.abort()
  actionController?.abort()
})
</script>

<template>
  <section aria-labelledby="collection-heading" class="mb-7 border border-stone-200 bg-white p-5 sm:p-6 dark:border-stone-800 dark:bg-stone-900">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 id="collection-heading" class="font-serif text-xl font-semibold text-stone-900 dark:text-stone-100">采集更新</h3>
        <p class="mt-2 text-xs leading-6 text-stone-500 dark:text-stone-400">先从期刊与研究动态来源采集、去重入库，再在下方按日期和关键词查询。</p>
      </div>
      <span v-if="state" class="border px-2.5 py-1 text-xs" :class="state.settings.enabled ? 'border-accent/25 text-accent' : 'border-stone-200 text-stone-400 dark:border-stone-700'">{{ state.settings.enabled ? `每日 ${state.settings.time} 自动采集` : '每日自动采集已关闭' }}</span>
    </div>

    <template v-if="state">
      <p class="mt-3 text-xs leading-6 text-stone-400">北京时间 · 自动回看最近 {{ state.settings.lookback_days }} 天，补录延迟更新的资料。服务关闭时暂停，重新启动后补查设置的回看范围。</p>
      <p v-if="state.next_run_at && state.settings.enabled" class="mt-1 text-xs text-stone-400">下次自动采集：{{ localTimeLabel(state.next_run_at) }}</p>
      <p v-if="!state.available" role="status" class="mt-3 text-xs leading-6 text-amber-700 dark:text-amber-400">采集服务当前不可用，可继续查询已入库资料。</p>

      <form class="mt-4 flex flex-wrap items-end gap-3" @submit.prevent="collect">
        <div class="min-w-0 flex-1 basis-40"><label for="collection-from" class="mb-2 block text-xs text-stone-600 dark:text-stone-300">采集开始日期</label><input id="collection-from" v-model="dates.date_from" type="date" required :max="dates.date_to || state.today" class="collection-input" /></div>
        <div class="min-w-0 flex-1 basis-40"><label for="collection-to" class="mb-2 block text-xs text-stone-600 dark:text-stone-300">采集结束日期</label><input id="collection-to" v-model="dates.date_to" type="date" required :min="dates.date_from" :max="state.today" class="collection-input" /></div>
        <button type="submit" :disabled="busy || running || !state.available" class="min-h-[42px] bg-accent px-5 py-2 text-sm font-medium text-white hover:bg-accent-soft disabled:cursor-default disabled:opacity-50">{{ running ? '采集进行中…' : busy ? '正在提交…' : '立即采集' }}</button>
      </form>
      <p class="mt-2 text-xs leading-5 text-stone-400">日期指来源发表日期。立即采集会联网更新资料库；下方查询只筛选库内资料。</p>

      <div v-if="job" class="mt-4 border-l-2 border-accent/40 bg-stone-50 px-4 py-3 dark:bg-stone-950/50">
        <div class="flex flex-wrap items-center justify-between gap-2" role="status" aria-live="polite">
          <p class="text-sm font-medium" :class="jobTone">{{ jobLabel }}<span v-if="running" class="ml-2 text-xs font-normal tabular-nums">{{ job.sources_done }} / {{ job.sources_total }} 个来源</span></p>
          <p class="text-xs tabular-nums text-stone-500 dark:text-stone-400">新增 {{ job.inserted }} 条 · 更新 {{ job.updated }} 条</p>
        </div>
        <p class="mt-2 text-xs leading-6 text-stone-400">{{ job.trigger === 'daily' ? '自动采集' : '手动采集' }} · {{ job.window_start }} 至 {{ job.window_end }} · {{ localTimeLabel(job.finished_at || job.started_at) }}</p>
        <p v-if="running && job.current_source" class="mt-1 break-words text-xs leading-6 text-stone-500 dark:text-stone-400">正在读取：{{ job.current_source }}</p>
        <p v-if="noNewExplanation" class="mt-1 text-xs leading-6 text-stone-500 dark:text-stone-400">{{ noNewExplanation }}</p>
        <p v-if="job.error" class="mt-1 break-words text-xs leading-6 text-red-600 dark:text-red-400">{{ job.error }}</p>
        <p v-if="coverageLimited" class="mt-1 text-xs leading-6 text-amber-700 dark:text-amber-400">部分来源存在覆盖限制，请展开查看各来源结果。</p>
        <details v-if="job.runs.length" class="mt-2">
          <summary class="cursor-pointer text-xs text-stone-600 dark:text-stone-300">查看各来源结果</summary>
          <p class="mt-2 text-xs leading-6 text-stone-400">读取量受分页与订阅范围限制；日期初筛保留日期未知的候选。跨来源候选数不能直接相加为独立论文数。</p>
          <ul class="mt-2 divide-y divide-stone-200 dark:divide-stone-800">
            <li v-for="run in job.runs" :key="`${run.source_id}-${run.started_at}`" class="py-2 text-xs leading-6">
              <p class="flex flex-wrap justify-between gap-x-3"><span class="text-stone-600 dark:text-stone-300">{{ run.source_name }}</span><span :class="run.status === 'failed' ? 'text-red-600 dark:text-red-400' : 'text-stone-500 dark:text-stone-400'">{{ runLabel(run) }}<template v-if="run.selection"> · 读取 {{ run.selection.parsed }} · 日期初筛 {{ run.selection.date_matched }}</template> · 相关候选 {{ run.found }} · 新增 {{ run.inserted }} · 更新 {{ run.updated }}</span></p>
              <p v-if="run.error" class="break-words text-red-600 dark:text-red-400">{{ run.error }}</p>
              <p v-if="run.coverage_warning" class="break-words text-amber-700 dark:text-amber-400">覆盖提示：{{ run.coverage_warning }}</p>
            </li>
          </ul>
        </details>
      </div>

      <div class="mt-4 grid gap-3 border-t border-stone-100 pt-4 text-xs sm:grid-cols-2 dark:border-stone-800">
        <details>
          <summary class="cursor-pointer text-stone-600 dark:text-stone-300">每日采集设置</summary>
          <form class="mt-3 space-y-3" @submit.prevent="saveSettings">
            <label class="flex items-center gap-2 text-stone-600 dark:text-stone-300"><input v-model="settings.enabled" type="checkbox" class="accent-accent" />开启每日自动采集</label>
            <div class="grid grid-cols-2 gap-3">
              <div><label for="collection-time" class="mb-2 block text-stone-500 dark:text-stone-400">时间（北京时间）</label><input id="collection-time" v-model="settings.time" type="time" required class="collection-input" /></div>
              <div><label for="collection-lookback" class="mb-2 block text-stone-500 dark:text-stone-400">自动回看天数</label><input id="collection-lookback" v-model.number="settings.lookback_days" type="number" min="1" max="30" step="1" required class="collection-input" /></div>
            </div>
            <button type="submit" :disabled="busy || !state.available" class="border border-stone-300 px-3 py-2 text-stone-600 hover:border-accent hover:text-accent disabled:opacity-50 dark:border-stone-700 dark:text-stone-300">保存设置</button>
            <p v-if="savedMessage" role="status" class="leading-6 text-emerald-700 dark:text-emerald-400">{{ savedMessage }}</p>
          </form>
        </details>
        <details>
          <summary class="cursor-pointer text-stone-600 dark:text-stone-300">采集来源与关键词（{{ state.sources.length }} 个来源）</summary>
          <ul class="mt-3 space-y-2 leading-6 text-stone-500 dark:text-stone-400"><li v-for="source in state.sources" :key="source.id"><span class="mr-2 text-stone-400">{{ source.content_type === 'paper' ? '论文' : '动态' }}</span>{{ source.name }}</li></ul>
          <p class="mt-3 leading-6 text-stone-400">按领域词与方法词共同初筛，相关性仍需核验。</p>
          <p class="mt-2 break-words leading-6 text-stone-500 dark:text-stone-400">领域：{{ state.relevance.domain_terms.join('、') }}</p>
          <p class="mt-2 break-words leading-6 text-stone-500 dark:text-stone-400">方法：{{ state.relevance.method_terms.join('、') }}</p>
          <p class="mt-2 leading-6 text-stone-400">订阅与元数据接口有覆盖范围；本轮无匹配不表示当天没有相关研究。</p>
        </details>
      </div>
    </template>
    <p v-else-if="!loadError" role="status" class="mt-4 text-sm text-stone-400">正在读取采集状态…</p>
    <div v-if="loadError" class="mt-4 flex flex-wrap items-center gap-3" role="status"><p class="text-xs leading-6 text-amber-700 dark:text-amber-400">{{ loadError }}，稍后将自动重试。</p><button type="button" :disabled="busy" class="text-xs text-accent underline underline-offset-4" @click="refresh">重新读取</button></div>
    <p v-if="actionError" role="alert" class="mt-3 text-sm leading-6 text-red-600 dark:text-red-400">{{ actionError }}</p>
  </section>
</template>

<style scoped>
.collection-input {
  @apply block min-h-[42px] w-full min-w-0 rounded-none border border-stone-300 bg-white px-3 py-2 text-sm text-stone-700 outline-none focus:border-accent focus:ring-1 focus:ring-accent/30 dark:border-stone-700 dark:bg-stone-950 dark:text-stone-200;
}
</style>
