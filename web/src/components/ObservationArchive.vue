<script setup lang="ts">
import { computed } from 'vue'
import type { ObservationPeriod, PublicationVersion } from '../api/observation-archive'

const props = defineProps<{
  editions: ObservationPeriod[]
  versions?: Pick<PublicationVersion, 'id' | 'title' | 'published_at'>[]
  selectedDay: string
  selectedVersion?: string | null
  latestDay?: string
  weekly?: boolean
}>()

const today = computed(() => !props.weekly && props.selectedDay === props.latestDay)
const periods = computed(() => props.weekly ? props.editions : props.editions.filter(edition => edition.date !== props.latestDay))

function reportLink(day?: string, version?: string) {
  return {
    name: 'home',
    query: props.weekly ? { day, edition: version } : { view: 'daily', day, version },
  }
}
</script>

<template>
  <nav class="min-w-0 border-t-2 border-accent pt-3" aria-labelledby="observation-archive-title">
    <h3 id="observation-archive-title" class="font-serif text-xl font-bold">{{ weekly ? '往期周报' : '往期每日观察' }}</h3>
    <RouterLink v-if="latestDay && selectedDay !== latestDay" :to="reportLink()" class="mt-2 inline-block text-sm text-accent hover:underline">
      {{ weekly ? '返回最新一期 →' : '返回今日 →' }}
    </RouterLink>
    <ul v-if="periods.length" class="mt-2 divide-y divide-stone-200 dark:divide-stone-800">
      <li v-for="edition in periods" :key="edition.date">
        <RouterLink :to="reportLink(edition.date)" :aria-current="edition.date===selectedDay ? 'page' : undefined"
          class="block py-3 hover:text-accent" :class="edition.date===selectedDay ? 'text-accent' : ''">
          <span class="block text-xs tabular-nums text-stone-600 dark:text-stone-400">{{ edition.date_from ? edition.date_from + ' 至 ' + edition.date : edition.date }}</span>
          <span class="mt-1 block break-words text-sm font-medium leading-6">{{ edition.title }}</span>
        </RouterLink>
      </li>
    </ul>
    <p v-else class="mt-2 text-sm text-stone-500">暂无往期记录</p>
    <details v-if="versions && (today ? versions.length : weekly && versions.length > 1)" :key="selectedDay" :open="today" class="mt-4 border-t border-stone-200 pt-3 text-sm dark:border-stone-800">
      <summary class="cursor-pointer font-medium">{{ weekly ? '查看本期版本' : '今日发布' }}（{{ versions.length }}）</summary>
      <ul class="mt-1 space-y-2">
        <li v-for="(row, index) in versions" :key="row.id">
          <RouterLink :to="reportLink(selectedDay, row.id)" :aria-current="selectedVersion===row.id ? 'page' : undefined"
            class="block break-words leading-6 text-accent hover:underline">
            <span class="block">{{ row.title }}</span>
            <span class="block text-xs tabular-nums text-stone-600 dark:text-stone-400">{{ row.published_at ? row.published_at.slice(0,16).replace('T',' ') : '原始版本' }}<template v-if="index===0"> · 最新版</template></span>
          </RouterLink>
        </li>
      </ul>
    </details>
  </nav>
</template>

