<script setup lang="ts">
import type { AnalysisClaim } from '../api/analysis'
defineProps<{ claim: AnalysisClaim }>()
function scrollToSource(ref: string) {
  document.getElementById(`analysis-source-${ref}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>
<template>
  <div class="text-sm leading-7 text-stone-700 dark:text-stone-300">
    <p class="whitespace-pre-wrap">{{ claim.text }} <a v-for="ref in claim.source_ids" :key="ref" :href="`#analysis-source-${ref}`" class="ml-1 text-xs text-accent underline underline-offset-2" @click.prevent="scrollToSource(ref)">[{{ ref }}]</a></p>
    <details class="mt-1 text-xs text-stone-500"><summary class="cursor-pointer">查看引用依据</summary>
      <blockquote v-for="(e,index) in claim.evidence" :key="index" class="mt-2 border-l-2 border-stone-200 pl-3">{{ e.source_id }} · {{ e.quote }}</blockquote>
    </details>
  </div>
</template>
