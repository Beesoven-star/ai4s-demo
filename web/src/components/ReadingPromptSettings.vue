<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { getReadingPrompts, saveReadingPrompt, type ReadingPromptKind } from '../api/ic-editor'

const labels = { paper: '论文详情提示词', news: '新闻详情提示词' }
const kinds: ReadingPromptKind[] = ['paper', 'news']
const systemPrompt = ref('')
const maxLength = ref(8000)
const loading = ref(true)
const loadError = ref('')
const editors = reactive({
  paper: { value: '', saved: '', defaultPrompt: '', footer: '', busy: false, error: '', notice: '' },
  news: { value: '', saved: '', defaultPrompt: '', footer: '', busy: false, error: '', notice: '' },
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const result = await getReadingPrompts()
    systemPrompt.value = result.system_prompt
    maxLength.value = result.max_length
    for (const kind of kinds) {
      const prompt = result.prompts[kind]
      const editor = editors[kind]
      editor.value = editor.saved = prompt.prompt
      editor.defaultPrompt = prompt.default_prompt
      editor.footer = prompt.request_footer
    }
  } catch (cause) {
    loadError.value = cause instanceof Error ? cause.message : '详情提示词加载失败'
  } finally {
    loading.value = false
  }
}

async function save(kind: ReadingPromptKind, reset = false) {
  const editor = editors[kind]
  editor.busy = true
  editor.error = editor.notice = ''
  try {
    const result = await saveReadingPrompt(kind, reset ? null : editor.value)
    editor.value = editor.saved = result.prompt
    editor.notice = reset ? '已恢复默认提示词。' : '已保存，下次整理时使用。'
  } catch (cause) {
    editor.error = cause instanceof Error ? cause.message : '提示词保存失败'
  } finally {
    editor.busy = false
  }
}

onMounted(load)
</script>

<template>
  <section class="mt-10 max-w-2xl border-t border-stone-200 pt-6 dark:border-stone-800" aria-labelledby="reading-prompt-settings">
    <h3 id="reading-prompt-settings" class="font-serif text-xl font-semibold">详情页阅读要点</h3>
    <p class="mt-2 text-sm leading-6 text-stone-600 dark:text-stone-300">这里的提示词用于逐条整理资料。保存后，下次生成该类要点时生效。</p>
    <p v-if="loading" role="status" class="mt-4 text-sm text-stone-500">正在加载提示词…</p>
    <div v-else-if="loadError" class="mt-4">
      <p role="alert" class="text-sm text-red-600">{{ loadError }}</p>
      <button type="button" class="mt-2 text-sm text-accent underline" @click="load">重新加载</button>
    </div>
    <template v-else>
      <form v-for="kind in kinds" :key="kind" class="mt-6" @submit.prevent="save(kind)">
        <label :for="'reading-prompt-' + kind" class="font-medium">{{ labels[kind] }}</label>
        <span class="ml-3 text-xs text-stone-600 dark:text-stone-400">{{ editors[kind].saved === editors[kind].defaultPrompt ? '默认' : '自定义' }}</span>
        <textarea :id="'reading-prompt-' + kind" v-model="editors[kind].value" rows="12" required :maxlength="maxLength" :disabled="editors[kind].busy"
          class="mt-2 w-full rounded border border-stone-300 bg-transparent p-3 text-sm leading-6 dark:border-stone-700" />
        <div class="mt-2 flex flex-wrap items-center gap-3 text-sm">
          <button type="submit" class="rounded bg-accent px-4 py-2 font-medium text-white disabled:opacity-50"
            :disabled="editors[kind].busy || !editors[kind].value.trim() || editors[kind].value.trim() === editors[kind].saved">保存提示词</button>
          <button type="button" class="rounded border border-stone-300 px-4 py-2 hover:text-accent disabled:opacity-50 dark:border-stone-700"
            :disabled="editors[kind].busy || editors[kind].value === editors[kind].defaultPrompt && editors[kind].saved === editors[kind].defaultPrompt"
            @click="save(kind, true)">恢复默认</button>
        </div>
        <p v-if="editors[kind].notice" role="status" class="mt-2 text-sm text-green-700 dark:text-green-400">{{ editors[kind].notice }}</p>
        <p v-if="editors[kind].error" role="alert" class="mt-2 text-sm text-red-600">{{ editors[kind].error }}</p>
        <details class="mt-3 rounded border border-stone-200 p-3 text-sm dark:border-stone-800">
          <summary class="cursor-pointer font-medium">查看完整默认提示词</summary>
          <h4 class="mt-3 font-medium">系统指令</h4>
          <p class="mt-1 whitespace-pre-wrap break-words leading-6">{{ systemPrompt }}</p>
          <h4 class="mt-3 font-medium">默认整理指令</h4>
          <p class="mt-1 whitespace-pre-wrap break-words leading-6">{{ editors[kind].defaultPrompt }}</p>
          <h4 class="mt-3 font-medium">程序附加的规则与输出结构</h4>
          <p class="mt-1 whitespace-pre-wrap break-words leading-6">{{ editors[kind].footer }}</p>
          <p class="mt-3 text-xs text-stone-600 dark:text-stone-400">发送请求时，程序在末尾附上本批待整理资料。</p>
        </details>
      </form>
    </template>
  </section>
</template>

