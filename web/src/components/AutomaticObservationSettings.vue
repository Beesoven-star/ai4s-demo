<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { getObservationAutomation, replayObservation, saveObservationPrompt, type AutomaticRun } from '../api/ic-editor'

const prompt = ref('')
const savedPrompt = ref('')
const version = ref('')
const runs = ref<AutomaticRun[]>([])
const day = ref(new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date()))
const busy = ref(false)
const error = ref('')
const notice = ref('')
let timer: ReturnType<typeof setInterval> | undefined

const labels: Record<AutomaticRun['status'], string> = {
  queued: '等待整理', running: '正在整理', published: '已自动更新',
  empty: '日期范围内暂无资料', unchanged: '沿用已发布版本', failed: '整理失败',
}

async function refresh() {
  try {
    const state = await getObservationAutomation()
    if (!version.value) {
      prompt.value = savedPrompt.value = state.prompt
      version.value = state.version
    }
    runs.value = state.runs
  } catch (cause) {
    if (!version.value) error.value = cause instanceof Error ? cause.message : '观察设置加载失败'
  }
}

async function save() {
  busy.value = true
  error.value = notice.value = ''
  try {
    const result = await saveObservationPrompt(prompt.value)
    prompt.value = savedPrompt.value = result.prompt
    version.value = result.version
    notice.value = '提示词已保存，下次整理时使用。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '保存失败'
  } finally {
    busy.value = false
  }
}

async function replay() {
  busy.value = true
  error.value = notice.value = ''
  try {
    await replayObservation(day.value)
    notice.value = '已提交重跑。有实质进展时才发布新版，结果会显示在下方。'
    await refresh()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法开始整理'
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  void refresh()
  timer = setInterval(refresh, 5000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <section class="mt-10 max-w-2xl border-t border-stone-200 pt-6 dark:border-stone-800" aria-labelledby="observation-settings">
    <h3 id="observation-settings" class="font-serif text-xl font-semibold">自动观察</h3>
    <p class="mt-2 text-sm leading-6 text-stone-600 dark:text-stone-300">采集完成后，工作台根据新增材料判断是否更新今日观察和本周简报。只有能写进报告的实质进展才发布新版。提示词可调整选材、写法和关注方向。</p>
    <form v-if="version" class="mt-4" @submit.prevent="save">
      <label for="observation-prompt" class="text-sm font-medium">整理提示词</label>
      <textarea id="observation-prompt" v-model="prompt" rows="6" required maxlength="3500" class="mt-2 w-full rounded border border-stone-300 bg-transparent p-3 text-sm leading-6 dark:border-stone-700" />
      <div class="mt-2 flex flex-wrap items-center gap-3 text-sm">
        <button type="submit" class="rounded bg-accent px-4 py-2 font-medium text-white disabled:opacity-50" :disabled="busy || !prompt.trim() || prompt.trim() === savedPrompt">保存提示词</button>
        <span class="text-xs text-stone-500">提示词版本 {{ version }}</span>
      </div>
    </form>
    <form v-if="version" class="mt-5 flex flex-wrap items-end gap-3 text-sm" @submit.prevent="replay">
      <label for="observation-replay-day">选择日期<input id="observation-replay-day" v-model="day" type="date" required class="mt-1 block rounded border border-stone-300 bg-transparent px-3 py-2 dark:border-stone-700"></label>
      <button type="submit" class="rounded border border-stone-300 px-4 py-2 hover:text-accent disabled:opacity-50 dark:border-stone-700" :disabled="busy || !day || prompt.trim() !== savedPrompt">用已有资料重跑</button>
    </form>
    <p v-if="notice" role="status" class="mt-3 text-sm text-green-700 dark:text-green-400">{{ notice }}</p>
    <p v-if="error" role="alert" class="mt-3 text-sm text-red-600">{{ error }}</p>
    <ul v-if="runs.length" class="mt-5 divide-y divide-stone-200 border-t border-stone-200 text-sm dark:divide-stone-800 dark:border-stone-800" aria-label="近期自动整理">
      <li v-for="run in runs" :key="run.id" class="py-2">
        <span>{{ run.date }} · {{ labels[run.status] }}<template v-if="run.usage?.total_tokens"> · {{ run.usage.total_tokens }} tokens</template></span>
        <p v-if="run.error" class="mt-1 text-xs text-stone-600 dark:text-stone-400">{{ run.error }}</p>
        <div v-if="run.publications?.length" class="mt-1 flex gap-3 text-xs text-accent">
          <RouterLink v-for="id in run.publications" :key="id" :to="{ name: 'home', query: id.endsWith('-daily') ? { view: 'daily', day: run.date, version: id } : { edition: id } }" class="hover:underline">{{ id.endsWith('-daily') ? '查看日报' : '查看周报' }}</RouterLink>
        </div>
      </li>
    </ul>
  </section>
</template>
