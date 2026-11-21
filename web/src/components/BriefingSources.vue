<script setup lang="ts">
import type { BriefingSource } from '../briefing-types'
import { newsGenreLabel, safeExternalUrl } from '../api/discovery'
import { useRoute } from 'vue-router'
const route = useRoute()
defineProps<{ ids: string[]; sources: Record<string, BriefingSource>; excerpts?: boolean; eventId?: string }>()
</script>

<template>
  <ul class="space-y-3">
    <li v-for="id in [...new Set(ids)]" :key="id" class="border-l-2 border-stone-200 pl-3 dark:border-stone-700">
      <template v-if="sources[id]">
        <p class="text-xs leading-6 text-stone-500">{{ sources[id].source }} · {{ sources[id].published_at || (sources[id].publication_month ? `${sources[id].publication_month}（仅月份）` : '未收录发布日期') }} · {{ sources[id].evidence_kind }}</p>
        <p v-if="sources[id].author" class="text-xs leading-6 text-stone-500">{{ [sources[id].author, newsGenreLabel(sources[id].news_genre), sources[id].attention_eligible ? '计入关注度' : '背景材料'].filter(Boolean).join(' · ') }}</p>
        <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <RouterLink :to="{path:`/discover/item/${id}`,query:{from:route.fullPath,event:eventId}}" class="min-w-0 break-words text-sm leading-6 text-accent hover:underline">{{ sources[id].title }}</RouterLink>
          <a v-if="safeExternalUrl(sources[id].url)" :href="safeExternalUrl(sources[id].url)" target="_blank" rel="noopener noreferrer" class="shrink-0 text-xs text-stone-500 underline underline-offset-4">原始出处</a>
        </div>
        <p v-if="excerpts" class="mt-2 break-words text-sm leading-6 text-stone-600 dark:text-stone-400"><span v-if="sources[id].reading_takeaway" class="mr-2 font-medium">主要发现</span>{{ sources[id].reading_takeaway || sources[id].excerpt || '仅有题名，尚无可用简介。' }}</p>
        <p v-if="excerpts && sources[id].content_type==='news'" class="mt-2 text-xs leading-6 text-stone-500">{{ sources[id].attention_note }}</p>
      </template>
    </li>
  </ul>
</template>
