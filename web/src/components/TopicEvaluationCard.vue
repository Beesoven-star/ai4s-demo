<script setup lang="ts">
import { computed } from 'vue'
import { newsGenreLabel, readingBasisLabel, safeExternalUrl } from '../api/discovery'
import type { TopicEvaluation } from '../briefing-types'

const props = defineProps<{ evaluation: TopicEvaluation }>()
const points = computed(() => [
  { id: 'finding', label: '综合判断', ...props.evaluation.finding, score: null },
  { id: 'limits', label: '适用条件与局限', ...props.evaluation.limits, score: null },
  ...props.evaluation.dimensions,
])
const missing = computed(() => [
  ['bottleneck', '瓶颈价值'], ['breadth', '影响范围'], ['enablement', '带动作用'],
].filter(([id]) => !props.evaluation.dimensions.some(point => point.id === id)).map(([, label]) => label))
</script>

<template>
  <section class="mt-6 rounded-lg border border-stone-200 bg-white p-5 dark:border-stone-700 dark:bg-stone-900" aria-label="技术评价">
    <div class="flex flex-wrap items-baseline justify-between gap-2">
      <h3 class="font-serif text-xl font-bold">技术评价</h3>
      <p v-if="evaluation.total !== null" class="text-sm font-semibold tabular-nums text-accent">{{ evaluation.total }} / 15 分</p>
    </div>
    <p class="mt-2 text-xs text-stone-600 dark:text-stone-400">{{ evaluation.stage }} · 证据截至 {{ evaluation.evidence_through.slice(0,10) }}</p>
    <div class="mt-3 divide-y divide-stone-200 dark:divide-stone-800">
      <div v-for="point in points" :key="point.id" class="py-3.5">
        <h4 class="text-sm font-semibold">{{ point.label }}<span v-if="point.score !== null" class="ml-2 font-medium text-accent">{{ point.score }} / 5</span></h4>
        <p class="mt-1 break-words text-sm leading-7 text-stone-700 dark:text-stone-300">{{ point.text }}</p>
        <details class="mt-1.5 text-sm">
          <summary class="cursor-pointer text-accent">查看所引材料</summary>
          <ul class="mt-2 space-y-2">
            <li v-for="reference in point.references" :key="reference.source_id + '-' + reference.excerpt_index" class="border-l border-stone-300 pl-3 text-xs dark:border-stone-700">
              <a :href="safeExternalUrl(evaluation.sources[reference.source_id].url)" target="_blank" rel="noopener noreferrer"
                class="font-medium text-accent hover:underline">{{ evaluation.sources[reference.source_id].title }} ↗</a>
              <p class="mt-1 text-stone-600 dark:text-stone-400">{{ evaluation.sources[reference.source_id].source }} · {{ readingBasisLabel(evaluation.sources[reference.source_id].basis) }}<template v-if="newsGenreLabel(evaluation.sources[reference.source_id].genre)"> · {{ newsGenreLabel(evaluation.sources[reference.source_id].genre) }}</template></p>
              <blockquote class="mt-1 break-words leading-6 text-stone-700 dark:text-stone-300">{{ reference.quote }}</blockquote>
            </li>
          </ul>
        </details>
      </div>
    </div>
    <p v-if="evaluation.total === null" class="mt-2 border-t border-stone-200 pt-3 text-xs leading-6 text-stone-600 dark:border-stone-800 dark:text-stone-400">
      {{ missing.length ? '尚缺依据的维度：' + missing.join('、') + '。' : '当前判断适用于所引材料。评分入榜还需不同机构的独立进展。' }}
    </p>
  </section>
</template>

