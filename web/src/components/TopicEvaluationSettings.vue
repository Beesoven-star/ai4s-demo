<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getEvaluationSettings, saveEvaluationSettings } from '../api/ic-editor'

const state = ref<Awaited<ReturnType<typeof getEvaluationSettings>> | null>(null)
const focus = ref('')
const busy = ref(false)
const error = ref('')
const notice = ref('')

async function load() {
  error.value = ''
  try {
    state.value = await getEvaluationSettings()
    focus.value = state.value.focus
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '评价规则读取失败'
  }
}

async function save() {
  busy.value = true
  error.value = notice.value = ''
  try {
    state.value = await saveEvaluationSettings(focus.value)
    focus.value = state.value.focus
    notice.value = '已保存，下次根据新证据评价时使用。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '评价偏好保存失败'
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="mt-10 max-w-2xl border-t border-stone-200 pt-6 dark:border-stone-800" aria-labelledby="topic-evaluation-settings">
    <h3 id="topic-evaluation-settings" class="font-serif text-xl font-semibold">技术评价规则</h3>
    <template v-if="state">
      <p class="mt-2 text-sm leading-6 text-stone-600 dark:text-stone-300">{{ state.rank_rule }}</p>
      <details class="mt-3 text-sm">
        <summary class="cursor-pointer font-medium">查看三项评分尺度</summary>
        <ul class="mt-2 space-y-2 text-stone-700 dark:text-stone-300">
          <li v-for="row in state.rubric" :key="row.label"><strong>{{ row.label }}</strong> · {{ row.criteria }}</li>
        </ul>
      </details>
      <form class="mt-4" @submit.prevent="save">
        <label for="evaluation-focus" class="text-sm font-medium">补充关注点</label>
        <textarea id="evaluation-focus" v-model="focus" rows="3" :maxlength="state.max_length" :disabled="busy"
          placeholder="例如，比较供电方案时关注机柜和加速器端的测试条件。"
          class="mt-2 w-full rounded border border-stone-300 bg-transparent p-3 text-sm leading-6 dark:border-stone-700" />
        <button type="submit" :disabled="busy || focus.trim() === state.focus" class="mt-2 rounded bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50">保存关注点</button>
      </form>
    </template>
    <p v-if="notice" role="status" class="mt-2 text-sm text-green-700 dark:text-green-400">{{ notice }}</p>
    <p v-if="error" role="alert" class="mt-2 text-sm text-red-600">{{ error }}</p>
  </section>
</template>

