<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { DAILY_SECTIONS, WEEKLY_SECTIONS, isWeeklyPath } from '../sections'
import ThemeToggle from './ThemeToggle.vue'
import { workspace } from '../workspace'
import { IS_STATIC } from '../static-mode'

const route = useRoute()
const mainLinks = computed(() => [
  { label: '热点与技术观察', to: '/', active: route.name === 'home' },
  { label: '技术专题与评价', to: '/explore/ic', active: route.name === 'ic-exploration' },
  { label: '每日发现', to: workspace.domain === 'ic' ? '/discover?content_type=news' : '/discover', active: route.path.startsWith('/discover') },
  { label: '我的收藏', to: '/library', active: route.name === 'library' },
])
const weekly = computed(() => isWeeklyPath(route.path))
const showingReports = computed(() => workspace.reportsEnabled && ['section','section-weekly','list','list-weekly'].includes(String(route.name)))
const sections = computed(() => weekly.value ? WEEKLY_SECTIONS : DAILY_SECTIONS)
const sectionPrefix = computed(() => weekly.value ? '/sections-weekly' : '/sections')
const reportModes = [
  { label: '日报', path: '/sections/overview', weekly: false },
  { label: '周报', path: '/sections-weekly/weekly_overview', weekly: true },
]
const utilityLinks = computed(() => [
  { label: '相关性分析', path: '/analysis' },
  ...(workspace.reportsEnabled ? [
    { label: '日报归档', path: '/archive' },
    { label: '周报归档', path: '/archive-weekly' },
  ] : []),
  ...(!IS_STATIC ? [{ label: '工作文档', path: '/workdocs' }, { label: '设置', path: '/settings' }] : []),
])
const usingTools = computed(() => utilityLinks.value.some(item => item.path === route.path))
function sectionPath(key: string) {
  return `${sectionPrefix.value}/${key}`
}
function navClass(active: boolean) {
  return active
    ? 'bg-orange-50 font-semibold text-accent dark:bg-orange-950/40 dark:text-orange-300'
    : 'text-stone-600 hover:bg-stone-100 dark:text-stone-400 dark:hover:bg-stone-800'
}
</script>

<template>
  <aside class="hidden h-screen w-64 shrink-0 flex-col border-r border-stone-200 bg-white lg:sticky lg:top-0 lg:flex dark:border-stone-800 dark:bg-stone-900">
    <div class="shrink-0 px-6 pb-4 pt-5">
      <router-link to="/" class="block">
        <h1 class="font-serif text-xl font-bold leading-snug text-stone-900 dark:text-stone-50">科研信息工作台</h1>
        <p v-if="workspace.domain==='ic'" class="mt-1 text-xs text-stone-600 dark:text-stone-400">集成电路</p>
      </router-link>
    </div>
    <nav class="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 pb-3" aria-label="主导航">
      <router-link v-for="item in mainLinks" :key="item.to" :to="item.to" class="block rounded-md px-3 py-2.5 text-sm" :class="navClass(item.active)" :aria-current="item.active ? 'page' : undefined">{{ item.label }}</router-link>
      <div v-if="showingReports" class="!mt-3 border-t border-stone-100 pt-3 dark:border-stone-800">
        <div class="flex gap-1 rounded-lg bg-stone-100 p-1 dark:bg-stone-800" aria-label="报告模式">
          <router-link v-for="mode in reportModes" :key="mode.path" :to="mode.path" class="flex-1 rounded-md px-3 py-1.5 text-center text-sm" :class="navClass(weekly === mode.weekly)" :aria-current="route.path === mode.path ? 'page' : undefined">{{ mode.label }}</router-link>
        </div>
        <div class="mt-2 space-y-0.5" :aria-label="weekly ? '周报栏目' : '日报栏目'">
          <router-link v-for="sec in sections" :key="sectionPath(sec.key)" :to="sectionPath(sec.key)" :title="sec.label" class="flex items-center gap-3 rounded-lg px-3 py-2 text-sm" :class="navClass(route.path === sectionPath(sec.key))" :aria-current="route.path === sectionPath(sec.key) ? 'page' : undefined"><span aria-hidden="true">{{ sec.icon }}</span>{{ sec.short }}</router-link>
        </div>
      </div>
      <details class="!mt-4 border-t border-stone-200 pt-2 dark:border-stone-800" :open="usingTools">
        <summary class="cursor-pointer px-3 py-2 text-sm text-stone-600 dark:text-stone-400">工具与归档</summary>
        <router-link v-for="item in utilityLinks" :key="item.path" :to="item.path" class="block rounded-lg px-3 py-2 text-sm" :class="navClass(route.path === item.path)" :aria-current="route.path === item.path ? 'page' : undefined">{{ item.label }}</router-link>
      </details>
    </nav>
    <div class="flex shrink-0 items-center justify-between border-t border-stone-200 px-6 py-3 dark:border-stone-800">
      <ThemeToggle />
    </div>
  </aside>
  <header class="border-b border-stone-200 bg-white lg:hidden dark:border-stone-800 dark:bg-stone-900">
    <div class="flex items-center justify-between px-4 py-3">
      <router-link to="/" class="font-serif text-lg font-bold">科研信息工作台</router-link>
      <ThemeToggle />
    </div>
    <nav class="border-t border-stone-100 px-3 py-2 dark:border-stone-800" aria-label="主导航">
      <div class="grid grid-cols-2 gap-1 sm:flex sm:flex-wrap">
        <router-link v-for="item in mainLinks" :key="item.to" :to="item.to" class="rounded-md px-2.5 py-2 text-sm" :class="navClass(item.active)" :aria-current="item.active ? 'page' : undefined">{{ item.label }}</router-link>
      </div>
      <details class="mt-1 text-sm" :open="usingTools">
        <summary class="cursor-pointer px-2.5 py-2 text-stone-600 dark:text-stone-400">工具与归档</summary>
        <div class="flex flex-wrap gap-1">
          <router-link v-for="item in utilityLinks" :key="item.path" :to="item.path" class="rounded-md px-2.5 py-2" :class="navClass(route.path === item.path)" :aria-current="route.path === item.path ? 'page' : undefined">{{ item.label }}</router-link>
        </div>
      </details>
    </nav>
    <nav v-if="showingReports" class="mx-3 flex gap-1 rounded-lg bg-stone-100 p-1 dark:bg-stone-800" aria-label="报告模式">
      <router-link v-for="mode in reportModes" :key="mode.path" :to="mode.path" class="flex-1 rounded-md px-3 py-1.5 text-center text-sm" :class="navClass(weekly === mode.weekly)" :aria-current="route.path === mode.path ? 'page' : undefined">{{ mode.label }}</router-link>
    </nav>
    <nav v-if="showingReports" class="flex flex-wrap gap-1 px-3 py-2" :aria-label="weekly ? '周报栏目' : '日报栏目'">
      <router-link v-for="sec in sections" :key="sectionPath(sec.key)" :to="sectionPath(sec.key)" :title="sec.label" class="flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs" :class="navClass(route.path === sectionPath(sec.key))" :aria-current="route.path === sectionPath(sec.key) ? 'page' : undefined"><span aria-hidden="true">{{ sec.icon }}</span>{{ sec.short }}</router-link>
    </nav>
  </header>
</template>
