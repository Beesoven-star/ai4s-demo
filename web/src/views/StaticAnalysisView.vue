<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import type { AnalysisRun } from '../api/analysis'
import { localTimeLabel, safeExternalUrl } from '../api/discovery'
import { loadSnapshot } from '../api/static-data'
import AnalysisClaim from '../components/AnalysisClaim.vue'

const route = useRoute()
const runs = ref<AnalysisRun[]>([]), loading = ref(true), error = ref('')
const itemIds = ref(new Set<string>())
const controller = new AbortController()
const active = computed(() => typeof route.query.run === 'string' ? runs.value.find(run => run.id === route.query.run) : undefined)
const report = computed(() => active.value?.report)
const missing = computed(() => typeof route.query.run === 'string' && !active.value)
watch(() => route.query.run, () => window.scrollTo({ top: 0 }))
onMounted(async () => {
  try {
    const data = await loadSnapshot(controller.signal)
    runs.value = data.reports
    itemIds.value = new Set(data.items.map(item => item.id))
  } catch (cause) { if (!controller.signal.aborted) error.value = cause instanceof Error ? cause.message : '报告读取失败' }
  finally { loading.value = false }
})
onBeforeUnmount(() => controller.abort())
</script>

<template>
  <div>
    <header class="mb-7 border-b-2 border-stone-900 pb-5 dark:border-stone-100"><h2 class="font-serif text-3xl font-bold">相关性分析</h2><p class="mt-3 text-sm leading-7 text-stone-500">浏览已经生成的历史报告、引用依据和分析材料。</p></header>
    <p v-if="loading" role="status" class="py-8 text-sm text-stone-500">正在读取分析报告…</p>
    <p v-else-if="error" role="alert" class="text-sm text-red-600">{{ error }}</p>
    <template v-else>
      <router-link v-if="route.query.run" to="/analysis" class="text-sm text-accent">← 返回历史报告</router-link>
      <p v-if="missing" role="alert" class="mt-5 text-sm text-stone-500">当前发布版本中没有这份报告。</p>
      <article v-if="active && report" class="mt-5" aria-label="分析报告">
        <header class="border-b border-stone-200 pb-4 dark:border-stone-700"><p class="text-xs text-accent">模型分析草稿 · 待人工核验</p><h3 class="mt-3 font-serif text-2xl font-bold leading-9">{{ report.title }}</h3><p class="mt-3 text-xs leading-6 text-stone-500">生成于 {{ localTimeLabel(active.created_at) }} · {{ active.model }}<br />{{ active.filters.date_from }} 至 {{ active.filters.date_to }} · 按{{ active.filters.date_basis === 'published' ? '发表日期' : '收录日期' }}筛选 · 匹配 {{ active.matched_count }} 条 / 分析 {{ active.source_count }} 条</p></header>
        <div class="mt-5"><AnalysisClaim :claim="report.overview" /></div>
        <h4 class="mt-7 font-serif text-xl font-semibold">该时间段的研究动向</h4>
        <section v-for="(trend,index) in report.trends" :key="index" class="mt-5 border-l-2 border-accent/30 pl-4"><h5 class="mb-3 font-semibold">{{ trend.title }}</h5><p class="mb-1 text-xs text-stone-400">来源陈述</p><AnalysisClaim :claim="trend.observation" /><p class="mb-1 mt-3 text-xs text-stone-400">模型推断</p><AnalysisClaim :claim="trend.interpretation" /></section>
        <h4 class="mb-4 mt-7 font-serif text-xl font-semibold">文献与新闻的关联</h4><div v-for="(claim,index) in report.connections" :key="index" class="mt-4"><AnalysisClaim :claim="claim" /></div><p v-if="!report.connections.length" class="text-sm text-stone-500">现有材料不足以支持明确的跨来源关联。</p>
        <section class="mt-7 border border-accent/30 bg-accent/5 p-5"><h4 class="mb-3 font-serif text-xl font-semibold">值得进一步探索的候选问题</h4><AnalysisClaim :claim="report.research_question.question" /><h5 class="mb-2 mt-5 font-semibold">为什么值得探索</h5><AnalysisClaim :claim="report.research_question.motivation" /><div class="mt-5 grid gap-5 sm:grid-cols-2"><div><h5 class="mb-2 font-semibold">探索路径</h5><ol class="list-decimal space-y-2 pl-5 text-sm leading-7"><li v-for="(text,index) in report.research_question.approach" :key="index">{{ text }}</li></ol></div><div><h5 class="mb-2 font-semibold">如何验证</h5><ol class="list-decimal space-y-2 pl-5 text-sm leading-7"><li v-for="(text,index) in report.research_question.validation" :key="index">{{ text }}</li></ol></div></div></section>
        <details class="mt-5 text-sm text-stone-500"><summary class="cursor-pointer">局限与待核验</summary><ul class="mt-3 list-disc space-y-2 pl-5"><li v-for="(text,index) in report.limitations" :key="index">{{ text }}</li></ul></details>
        <section class="mt-7"><h4 class="font-serif text-xl font-semibold">信息来源与分析材料</h4><article v-for="source in active.sources" :id="`analysis-source-${source.ref}`" :key="source.ref" class="scroll-mt-5 border-b border-stone-200 py-4 dark:border-stone-800"><p class="text-sm leading-7"><span class="mr-2 font-semibold text-accent">{{ source.ref }}</span>{{ source.title }}</p><p class="mt-1 text-xs leading-6 text-stone-500">{{ source.content_type === 'paper' ? '文献' : '新闻' }} · {{ source.source }} · {{ source.published_at || source.publication_month || source.publication_year || '发表日期未提供' }}</p><div class="mt-2 flex gap-4 text-xs"><router-link v-if="itemIds.has(source.id)" :to="`/discover/item/${source.id}`" class="text-accent">资料详情</router-link><a v-if="safeExternalUrl(source.url)" :href="safeExternalUrl(source.url)" target="_blank" rel="noopener noreferrer" class="text-accent">原始出处 ↗</a></div><details class="mt-2 text-xs text-stone-500"><summary class="cursor-pointer">查看本次分析使用的材料片段</summary><p class="mt-2 whitespace-pre-wrap leading-7">{{ source.excerpt || '仅使用题名。' }}</p><p v-if="source.excerpt_truncated">本次使用前4000字符。</p></details></article></section>
      </article>
      <section v-if="!route.query.run" aria-label="历史分析报告"><p v-if="!runs.length" class="py-8 text-sm text-stone-500">当前发布版本尚无已完成的分析报告。</p><article v-for="run in runs" :key="run.id" class="border-b border-stone-200 py-5 dark:border-stone-700"><router-link :to="{ path: '/analysis', query: { run: run.id } }" class="font-serif text-xl font-semibold leading-8 hover:text-accent">{{ run.report?.title }}</router-link><p class="mt-2 text-xs leading-6 text-stone-500">{{ localTimeLabel(run.created_at) }} · {{ run.filters.date_from }} 至 {{ run.filters.date_to }} · {{ run.source_count }} 条材料</p></article></section>
    </template>
  </div>
</template>
