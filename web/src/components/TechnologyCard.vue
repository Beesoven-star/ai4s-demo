<script setup lang="ts">
import { computed } from 'vue'
import type { ICBriefing, Technology } from '../briefing-types'
import BriefingSources from './BriefingSources.vue'
const props = defineProps<{ technology: Technology; briefing: ICBriefing }>()
const emit = defineEmits<{ changeDays: [days: number] }>()
const events = computed(() => props.briefing.events.filter(e => props.technology.attention.event_ids.includes(e.id)))
const sections = computed(() => [
  { label: '技术与问题', claim: props.technology.overview },
  { label: '条件与局限', claim: props.technology.limitations },
  { label: '后续关注', claim: props.technology.watch_next },
])
</script>

<template>
  <article :id="`technology-${technology.id}`" class="min-w-0 scroll-mt-6 rounded-lg border border-stone-200 bg-white dark:border-stone-700 dark:bg-stone-900">
    <header class="border-b border-stone-200 p-5 sm:p-6 dark:border-stone-700">
      <div class="flex flex-wrap items-center gap-2 text-sm">
        <span class="font-semibold text-accent">{{ technology.track==='ai_for_ic' ? 'AI用于芯片设计' : '芯片用于AI计算' }}</span>
      </div>
      <h3 class="mt-3 font-serif text-2xl font-bold">{{ technology.name }}</h3>
      <p class="mt-2 text-base leading-7 text-stone-600 dark:text-stone-400">{{ technology.tagline }}</p>
    </header>
    <div class="p-5 sm:p-6">
      <section>
        <h4 class="text-base font-semibold">综合评价</h4>
        <p class="mt-2 text-base leading-7 text-stone-700 dark:text-stone-300">{{ technology.assessment.text }}</p>
        <details class="mt-2 text-sm"><summary class="cursor-pointer text-accent">评价依据（{{ technology.assessment.source_ids.length }}）</summary><BriefingSources class="mt-3" :ids="technology.assessment.source_ids" :sources="briefing.sources" :excerpts="true" /></details>
      </section>
      <section class="mt-6 border-t border-stone-200 pt-4 dark:border-stone-700">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h4 class="text-base font-semibold">近期动态 <span class="ml-1 text-sm font-normal text-stone-600 dark:text-stone-400">{{ events.length }} 组</span></h4>
          <div class="inline-flex rounded-md bg-stone-100 p-0.5 dark:bg-stone-800" role="group" aria-label="动态统计窗口">
            <button v-for="days in [7,30]" :key="days" type="button" :aria-pressed="briefing.window.days===days" class="rounded px-3 py-1.5 text-xs" :class="briefing.window.days===days ? 'bg-white font-semibold text-stone-900 shadow-sm dark:bg-stone-700 dark:text-white' : 'text-stone-600 dark:text-stone-300'" @click="emit('changeDays', days)">{{ days }}天</button>
          </div>
        </div>
        <p v-if="!events.length" class="mt-3 text-sm leading-6 text-stone-500">当前窗口内没有已关联的动态。可切换30天，或查看下方代表文献；没有报道不等于技术不重要。</p>
        <details v-for="event in events" :key="event.id" class="mt-3 border-l-2 border-accent/30 pl-3">
          <summary class="cursor-pointer text-sm leading-6">{{ event.title }}</summary>
          <p v-if="event.occurred_at" class="mt-2 text-xs leading-6 text-stone-500">事件或披露日期 {{ event.occurred_at }}</p>
          <p class="my-2 text-sm leading-6 text-stone-500">{{ event.grouping_note }}</p>
          <BriefingSources :ids="event.window_source_ids" :sources="briefing.sources" :event-id="event.id" :excerpts="true" />
          <details v-if="event.source_ids.length > event.window_source_ids.length" class="mt-3 text-sm">
            <summary class="cursor-pointer text-stone-500">其他参考来源</summary>
            <BriefingSources class="mt-2" :ids="event.source_ids.filter(id => !event.window_source_ids.includes(id))" :sources="briefing.sources" :event-id="event.id" :excerpts="true" />
          </details>
        </details>
      </section>
      <div class="mt-6 divide-y divide-stone-200 border-y border-stone-200 dark:divide-stone-700 dark:border-stone-700">
        <details v-for="section in sections" :key="section.label" class="py-3 text-sm">
          <summary class="cursor-pointer font-semibold">{{ section.label }}</summary>
          <p class="mt-2 leading-7 text-stone-600 dark:text-stone-300">{{ section.claim.text }}</p>
          <BriefingSources class="mt-3" :ids="section.claim.source_ids" :sources="briefing.sources" :excerpts="true" />
        </details>
        <details class="py-3">
          <summary class="cursor-pointer text-sm font-semibold">重要性评分依据 <span class="ml-1 font-normal text-stone-600 dark:text-stone-400">{{ technology.importance_score }} / 15 分</span></summary>
          <p class="mt-3 text-sm leading-6 text-stone-600 dark:text-stone-400">{{ technology.review_status==='provisional' ? '评分反映本版资料支持的技术判断，依据列在下方。' : '评分及依据已复核。' }}</p>
          <div class="mt-3 space-y-3">
            <section v-for="score in technology.scores" :key="score.label" class="rounded-md border border-stone-200 p-4 dark:border-stone-700">
              <p class="flex justify-between gap-2 text-sm font-semibold">{{ score.label }}<span class="text-accent">{{ score.value }} / 5</span></p>
              <p class="mt-2 text-sm leading-6 text-stone-600 dark:text-stone-400">{{ score.text }}</p>
              <BriefingSources class="mt-3" :ids="score.source_ids" :sources="briefing.sources" />
            </section>
          </div>
          <p class="mt-3 text-sm leading-6 text-stone-500">评分依据为综合判断，分别考虑瓶颈价值、影响范围和带动作用。</p>
        </details>
        <details class="py-3">
          <summary class="cursor-pointer text-sm font-semibold">代表文献（{{ technology.paper_ids.length }}）</summary>
          <p class="my-3 text-sm leading-6 text-stone-500">用于理解方法与局限，含历史或仅月份资料。</p>
          <BriefingSources :ids="technology.paper_ids" :sources="briefing.sources" :excerpts="true" />
        </details>
      </div>
      <div class="mt-6 space-y-2 bg-stone-50 p-4 text-sm leading-6 text-stone-600 dark:bg-stone-800/60 dark:text-stone-400">
        <p><span class="font-semibold">目前做到哪一步</span>　{{ technology.maturity }}</p>
        <p><span class="font-semibold">判断依据</span>　{{ technology.evidence_status }}</p>
        <p>评价制作于 {{ briefing.prepared_on }}；资料截至 {{ briefing.data_through }}。各项评价以所列证据为限。</p>
      </div>
    </div>
  </article>
</template>
