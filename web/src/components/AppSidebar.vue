<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { DAILY_SECTIONS, WEEKLY_SECTIONS, isWeeklyPath } from '../sections'
import ThemeToggle from './ThemeToggle.vue'
import { workspace } from '../workspace'
import { IS_STATIC } from '../static-mode'

const route = useRoute()
const discovering = computed(() => route.path.startsWith('/discover'))
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
  { label: '我的收藏', path: '/library' },
  ...(workspace.reportsEnabled ? [
    { label: '日报归档', path: '/archive' },
    { label: '周报归档', path: '/archive-weekly' },
  ] : []),
  ...(!IS_STATIC ? [{ label: '工作文档', path: '/workdocs' }, { label: '设置', path: '/settings' }] : []),
])
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
      <router-link to="/discover" class="block">
        <p class="text-[10px] font-semibold uppercase tracking-[0.23em] text-accent">AI4S · Research Desk</p>
        <h1 class="mt-2 font-serif text-2xl font-bold leading-snug text-stone-900 dark:text-stone-50">科研信息工作台</h1>
        <p class="mt-1 text-xs leading-relaxed text-stone-500">主题探索与研究资料管理</p>
      </router-link>
      <div class="mt-4 border-t-2 border-stone-900 dark:border-stone-200" />
      <div class="mt-1 border-t border-stone-200 dark:border-stone-700" />
    </div>
    <nav class="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 pb-3" aria-label="主导航">
      <router-link to="/explore/ic" class="flex items-center gap-3 rounded-lg px-3 py-2 text-sm" :class="navClass(route.name === 'ic-exploration')" :aria-current="route.name === 'ic-exploration' ? 'page' : undefined"><span aria-hidden="true">⌘</span> 集成电路主题探索</router-link>
      <router-link to="/discover" class="flex items-center gap-3 rounded-lg px-3 py-2 text-sm" :class="navClass(discovering)" :aria-current="discovering ? 'page' : undefined"><span aria-hidden="true">◈</span> 每日发现</router-link>
      <div v-if="showingReports" class="!mt-3 border-t border-stone-100 pt-3 dark:border-stone-800">
        <div class="flex gap-1 rounded-lg bg-stone-100 p-1 dark:bg-stone-800" aria-label="报告模式">
          <router-link v-for="mode in reportModes" :key="mode.path" :to="mode.path" class="flex-1 rounded-md px-3 py-1.5 text-center text-sm" :class="navClass(weekly === mode.weekly)" :aria-current="route.path === mode.path ? 'page' : undefined">{{ mode.label }}</router-link>
        </div>
        <div class="mt-2 space-y-0.5" :aria-label="weekly ? '周报栏目' : '日报栏目'">
          <router-link v-for="sec in sections" :key="sectionPath(sec.key)" :to="sectionPath(sec.key)" :title="sec.label" class="flex items-center gap-3 rounded-lg px-3 py-2 text-sm" :class="navClass(route.path === sectionPath(sec.key))" :aria-current="route.path === sectionPath(sec.key) ? 'page' : undefined"><span aria-hidden="true">{{ sec.icon }}</span>{{ sec.short }}</router-link>
        </div>
      </div>
      <div class="!mt-3 border-t border-stone-100 pt-2 dark:border-stone-800">
        <router-link v-for="item in utilityLinks" :key="item.path" :to="item.path" class="block rounded-lg px-3 py-2 text-sm" :class="navClass(route.path === item.path)" :aria-current="route.path === item.path ? 'page' : undefined">{{ item.label }}</router-link>
      </div>
    </nav>
    <div class="flex shrink-0 items-center justify-between border-t border-stone-200 px-6 py-3 dark:border-stone-800">
      <span class="text-[11px] text-stone-400">本地科研工作台</span><ThemeToggle />
    </div>
  </aside>
  <header class="border-b border-stone-200 bg-white lg:hidden dark:border-stone-800 dark:bg-stone-900">
    <div class="flex items-center justify-between px-4 py-3">
      <router-link to="/explore/ic"><p class="text-[9px] uppercase tracking-[0.2em] text-accent">AI4S · Research Desk</p><p class="mt-1 font-serif text-lg font-bold">科研信息工作台</p></router-link>
      <ThemeToggle />
    </div>
    <nav class="flex flex-wrap gap-1 border-t border-stone-100 px-3 py-2 dark:border-stone-800" aria-label="主导航">
      <router-link to="/explore/ic" class="rounded-full px-3 py-1.5 text-xs" :class="navClass(route.name === 'ic-exploration')" :aria-current="route.name === 'ic-exploration' ? 'page' : undefined">集成电路主题探索</router-link>
      <router-link to="/discover" class="rounded-full px-3 py-1.5 text-xs" :class="navClass(discovering)" :aria-current="discovering ? 'page' : undefined">每日发现</router-link>
      <router-link v-for="item in utilityLinks" :key="item.path" :to="item.path" class="rounded-full px-3 py-1.5 text-xs" :class="navClass(route.path === item.path)" :aria-current="route.path === item.path ? 'page' : undefined">{{ item.label }}</router-link>
    </nav>
    <nav v-if="showingReports" class="mx-3 flex gap-1 rounded-lg bg-stone-100 p-1 dark:bg-stone-800" aria-label="报告模式">
      <router-link v-for="mode in reportModes" :key="mode.path" :to="mode.path" class="flex-1 rounded-md px-3 py-1.5 text-center text-sm" :class="navClass(weekly === mode.weekly)" :aria-current="route.path === mode.path ? 'page' : undefined">{{ mode.label }}</router-link>
    </nav>
    <nav v-if="showingReports" class="flex flex-wrap gap-1 px-3 py-2" :aria-label="weekly ? '周报栏目' : '日报栏目'">
      <router-link v-for="sec in sections" :key="sectionPath(sec.key)" :to="sectionPath(sec.key)" :title="sec.label" class="flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs" :class="navClass(route.path === sectionPath(sec.key))" :aria-current="route.path === sectionPath(sec.key) ? 'page' : undefined"><span aria-hidden="true">{{ sec.icon }}</span>{{ sec.short }}</router-link>
    </nav>
  </header>
</template>
