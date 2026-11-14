<script setup lang="ts">
import type { ICAnalysis } from '../discovery-types'
defineProps<{ analysis: ICAnalysis }>()
const labels: Record<string,string> = {ai_for_ic:'AI用于芯片设计',ic_for_ai:'芯片用于AI计算',general_ic:'通用集成电路研究'}
</script>
<template>
  <div class="mt-4 border-l-2 border-accent/40 pl-3 text-xs leading-7">
    <p :class="analysis.scope==='archive' || analysis.scope==='excluded' ? 'text-stone-500' : 'text-accent'">{{ analysis.tracks.map(t=>labels[t]).join(' · ') || analysis.scope_label || 'AI关联待核对' }}</p>
    <p v-if="analysis.reviewed_on" class="text-stone-500">范围审核 {{ analysis.reviewed_on }} · {{ analysis.scope_label }}</p>
    <p v-if="analysis.topics.length" class="text-stone-600 dark:text-stone-300">{{ analysis.topics.join(' · ') }}</p>
    <details class="text-stone-500"><summary class="cursor-pointer">归类依据 · {{ analysis.basis==='title_only' ? '仅有题名' : '题名与摘要' }}</summary><p class="mt-2">{{ analysis.note }}</p><div v-for="(e,index) in analysis.evidence" :key="index" class="mt-2"><p>{{ e.topic_id }} · {{ e.field==='title' ? '题名线索' : e.field==='title_abstract' ? '题名与摘要依据' : '摘要线索' }}</p><p>{{ e.ai_signal }}</p><p v-if="e.ai_signal!==e.task_signal">{{ e.task_signal }}</p></div></details>
  </div>
</template>
