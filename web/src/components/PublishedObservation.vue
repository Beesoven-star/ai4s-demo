<script setup lang="ts">
import type { ICDailyEdition } from '../briefing-types'
import { newsGenreLabel, readingBasisLabel, safeExternalUrl } from '../api/discovery'
defineProps<{ report: ICDailyEdition; weekly?: boolean }>()
</script>

<template>
  <section class="min-w-0 overflow-hidden rounded-lg border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900" aria-labelledby="published-observation-title">
    <header class="border-b border-stone-200 p-5 dark:border-stone-800">
      <p class="text-xs text-stone-600 dark:text-stone-400">
        {{ weekly && report.date_from ? `${report.date_from} 至 ${report.date}` : report.date }}<span v-if="report.coverage_through && report.coverage_through < report.date"> · 资料截至 {{ report.coverage_through }}</span><span v-if="report.automation"> · {{ report.automation.generated_at.slice(report.coverage_through ? 5 : 11,16).replace('T',' ') }} 自动更新</span><span v-else-if="report.published_at"> · {{ report.published_at.slice(0,10) }} 发布</span><span v-else-if="report.prepared_on!==report.date"> · {{ report.prepared_on }} 补编</span>
      </p>
      <h3 id="published-observation-title" class="mt-2 break-words font-serif text-2xl font-bold leading-snug">{{ report.title }}</h3>
      <p class="mt-2 whitespace-pre-wrap break-words text-sm leading-7 text-stone-700 dark:text-stone-300">{{ report.intro }}</p>
      <p v-if="report.automation?.collection_partial" class="mt-2 text-xs text-stone-600 dark:text-stone-400">本批部分来源未能读取。</p>
    </header>
    <div class="divide-y divide-stone-200 dark:divide-stone-800">
      <article v-for="entry in report.entries" :key="entry.source.id" class="px-5 py-4">
        <p v-if="!entry.sources" class="text-xs leading-5 text-stone-600 dark:text-stone-400">{{ entry.source.content_type==='paper' ? '文献' : '新闻' }} · {{ entry.source.source }}<span v-if="newsGenreLabel(entry.source.news_genre)"> · {{ newsGenreLabel(entry.source.news_genre) }}</span></p>
        <h4 class="mt-1 break-words text-base font-semibold leading-6">{{ entry.title }}</h4>
        <p class="mt-2 whitespace-pre-wrap break-words text-sm leading-7 text-stone-700 dark:text-stone-300">{{ entry.summary }}</p>
        <p v-if="entry.boundary" class="mt-1 text-sm leading-6 text-stone-600 dark:text-stone-400">{{ entry.boundary }}</p>
        <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs leading-5 text-stone-600 dark:text-stone-400">
          <span v-for="category in entry.classification.categories" :key="category.id">{{ category.name }}</span>
          <span v-for="topic in entry.classification.topics" :key="topic.id" class="font-medium text-stone-800 dark:text-stone-300">
            <RouterLink :to="{ name: 'ic-technology-topic', params: { topicId: topic.id } }" class="hover:text-accent hover:underline">{{ topic.name }}</RouterLink>
          </span>
          <a v-if="!entry.sources && safeExternalUrl(entry.source.url)" :href="safeExternalUrl(entry.source.url)" target="_blank" rel="noopener noreferrer" class="text-accent hover:underline">查看原始来源 ↗</a>
        </div>
        <ul v-if="entry.sources" class="mt-2 space-y-1 text-xs leading-5 text-stone-600 dark:text-stone-400" aria-label="原始出处">
          <li v-for="source in entry.sources" :key="source.id">
            <a :href="safeExternalUrl(source.url)" target="_blank" rel="noopener noreferrer" :title="source.title" class="text-accent hover:underline">{{ source.source }} ↗</a><span v-if="newsGenreLabel(source.news_genre)"> · {{ newsGenreLabel(source.news_genre) }}</span>
            <span v-if="readingBasisLabel(source.evidence_status, source.content_type)"> · {{ readingBasisLabel(source.evidence_status, source.content_type) }}</span>
            <details v-if="source.evidence_note" class="mt-1"><summary class="cursor-pointer">来源判断依据</summary><p class="mt-1 break-words">{{ source.evidence_note }}</p></details>
          </li>
        </ul>
      </article>
    </div>
    <p class="border-t border-stone-200 px-5 py-3 text-xs text-stone-600 dark:border-stone-800 dark:text-stone-400">此期按发布时保存的分类展示 · {{ report.catalog_version }}</p>
  </section>
</template>
