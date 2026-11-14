<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { analysisRequest, type AnalysisFilters, type AnalysisPreview, type AnalysisRun, type AnalysisOptions, type AnalysisSource, type ModelConnection } from '../api/analysis'
import { localTimeLabel, safeExternalUrl } from '../api/discovery'
import AnalysisClaim from '../components/AnalysisClaim.vue'
import { IS_STATIC } from '../static-mode'

const route = useRoute(), router = useRouter()
const filters = reactive<AnalysisFilters>({date_from:'',date_to:'',date_basis:'published',include_papers:true,include_news:true,
  literature_scope:'main',news_scope:'main',research_track:'',topic:'',keyword:''})
const options = ref<AnalysisOptions>({today:'',max_sources:80,topics:[]})
const connection = ref<ModelConnection|null>(null)
const preview = ref<AnalysisPreview|null>(null)
const selected = ref<string[]>([])
const active = ref<AnalysisRun|null>(null)
const history = ref<AnalysisRun[]>([])
const error = ref(''), loading = ref(false), starting = ref(false), initializing = ref(true)
const loadingRun = ref(false)
let timer: ReturnType<typeof setTimeout>|undefined, alive = true, previewSequence = 0, runSequence = 0
const topics = computed(() => options.value.topics.filter(t => !filters.research_track || filters.research_track==='any_ai'
  ? filters.research_track!=='any_ai' || t.track!=='general_ic' : t.track===filters.research_track))
const busy = computed(() => starting.value || active.value?.status==='running')
const chosenCounts = computed(() => {
  const ids = new Set(selected.value)
  return (preview.value?.sources || []).reduce((c,s) => {if(ids.has(s.id))c[s.content_type]++;return c}, {paper:0,news:0})
})
const report = computed(() => active.value?.report)
const quality: Record<string,string> = {source_abstract:'原始摘要',source_brief:'来源简介',human_summary:'人工简述',title_only:'仅题名'}
const trackLabels: Record<string,string> = {'':'全部集成电路资料',any_ai:'两类AI交叉研究',ai_for_ic:'AI用于芯片设计',ic_for_ai:'芯片用于AI计算',general_ic:'通用集成电路研究'}
function dateLabel(source: AnalysisSource) {return source.published_at || (source.publication_month ? `${source.publication_month}（仅月份）` : source.publication_year ? `${source.publication_year}（仅年份）` : '未提供')}
watch(() => filters.research_track, () => {if(!topics.value.some(t => t.id===filters.topic)) filters.topic=''})
watch(filters, () => {previewSequence++; loading.value=false; preview.value=null;selected.value=[]})

function daysAgo(day: string, days: number) {
  const parsed = new Date(day+'T00:00:00Z'); parsed.setUTCDate(parsed.getUTCDate()-days)
  return parsed.toISOString().slice(0,10)
}
function lastMonth() {filters.date_to=options.value.today; filters.date_from=daysAgo(options.value.today,29)}
async function loadHistory() {history.value=await analysisRequest<AnalysisRun[]>('/runs')}
async function filterSources() {
  const seq=++previewSequence
  loading.value=true;error.value=''
  try {
    const result=await analysisRequest<AnalysisPreview>('/preview',{...filters})
    if(seq!==previewSequence || !alive)return
    preview.value=result
    selected.value=result.total<=options.value.max_sources ? result.sources.map(s=>s.id) : []
  } catch(e) {if(seq===previewSequence)error.value=e instanceof Error ? e.message : '筛选失败'}
  finally {if(seq===previewSequence)loading.value=false}
}
function pickLatest() {selected.value=(preview.value?.sources || []).slice(0,options.value.max_sources).map(s=>s.id)}
function toggle(id: string, checked: boolean) {
  if(checked) {if(selected.value.length<options.value.max_sources)selected.value.push(id)}
  else selected.value=selected.value.filter(value=>value!==id)
}
async function loadRun(id: string, seq=++runSequence) {
  clearTimeout(timer)
  try {
    const run=await analysisRequest<AnalysisRun>('/runs/'+encodeURIComponent(id))
    if(!alive || seq!==runSequence)return
    active.value=run
    if(run.status==='running')timer=setTimeout(()=>void loadRun(id,seq),2000)
    else await loadHistory()
  } catch(e) {if(alive && seq===runSequence)error.value=e instanceof Error ? e.message : '分析状态读取失败'}
}
async function openRun(id: string) {
  error.value='';loadingRun.value=true
  await router.replace({path:'/analysis',query:{run:id}})
  await loadRun(id)
  loadingRun.value=false
}
async function start() {
  if(!preview.value)return
  starting.value=true;error.value=''
  try {
    connection.value=await analysisRequest<ModelConnection>('/connection')
    if(!connection.value.key_configured)throw new Error('请先在设置中完成模型连接')
    const run=await analysisRequest<AnalysisRun>('/runs',{filters:preview.value.filters,fingerprint:preview.value.fingerprint,item_ids:selected.value})
    active.value=run
    await router.replace({path:'/analysis',query:{run:run.id}})
    await loadHistory()
    await loadRun(run.id)
  } catch(e) {error.value=e instanceof Error ? e.message : '无法开始分析'}
  finally {starting.value=false}
}
async function retry() {
  if(!active.value || busy.value)return
  starting.value=true;error.value=''
  const previousId=active.value.id
  try {
    const run=await analysisRequest<AnalysisRun>('/runs/'+encodeURIComponent(previousId)+'/retry',{})
    active.value=run
    await router.replace({path:'/analysis',query:{run:run.id}})
    await loadHistory()
    await loadRun(run.id)
  } catch(e) {error.value=e instanceof Error ? e.message : '无法重新开始分析'}
  finally {starting.value=false}
}
function failureMessage(run: AnalysisRun) {
  return /输出被截断|输出额度/.test(run.error || '')
    ? '该次调用达到了输出额度上限，报告未完整生成。'
    : run.error || '本次分析未完成'
}
onMounted(async () => {
  try {
    const results=await Promise.all([analysisRequest<AnalysisOptions>('/options'),IS_STATIC ? Promise.resolve(null) : analysisRequest<ModelConnection>('/connection'),analysisRequest<AnalysisRun[]>('/runs')])
    options.value=results[0];connection.value=results[1];history.value=results[2];lastMonth()
    if(typeof route.query.run==='string')await loadRun(route.query.run)
    else if(history.value[0]?.status==='running')await openRun(history.value[0].id)
  } catch(e) {error.value=e instanceof Error ? e.message : '页面加载失败'}
  finally {initializing.value=false}
})
onBeforeUnmount(()=>{alive=false;previewSequence++;runSequence++;clearTimeout(timer)})
</script>

<template>
  <div>
    <header class="mb-6"><h2 class="font-serif text-3xl font-bold">相关性分析</h2><p class="mt-2 text-sm text-stone-500">从一批文献和新闻中梳理研究动向，提出有来源依据的探索问题。</p><div class="mt-5 border-t-2 border-stone-900 dark:border-stone-100" /></header>
    <p v-if="initializing" role="status" class="py-8 text-sm text-stone-500">正在加载…</p>
    <template v-else>
      <p v-if="IS_STATIC" class="mb-5 border-l-2 border-accent pl-3 text-sm leading-7">可筛选、勾选分析材料，并查看下方的历史报告。当前为静态展示，生成新报告需使用本地完整版。</p>
      <p v-else-if="!connection?.key_configured" class="mb-5 border-l-2 border-accent pl-3 text-sm leading-7">模型服务尚未连接。可先筛选材料，再到 <router-link to="/settings" class="text-accent underline">设置</router-link> 完成连接。</p>
      <form class="border border-stone-200 p-5 dark:border-stone-800" @submit.prevent="filterSources">
        <h3 class="mb-4 font-serif text-xl font-semibold">筛选分析材料</h3>
        <div class="grid gap-4 sm:grid-cols-3">
          <label class="text-xs text-stone-500">开始日期<input v-model="filters.date_from" type="date" required :max="options.today" class="analysis-input" /></label>
          <label class="text-xs text-stone-500">结束日期<input v-model="filters.date_to" type="date" required :min="filters.date_from" :max="options.today" class="analysis-input" /></label>
          <label class="text-xs text-stone-500">日期依据<select v-model="filters.date_basis" class="analysis-input"><option value="published">发表 / 新闻发布日期</option><option value="collected">平台收录日期</option></select></label>
        </div>
        <div class="mt-4 grid gap-4 sm:grid-cols-2">
          <label class="text-xs text-stone-500">研究主线<select v-model="filters.research_track" class="analysis-input"><option value="">全部集成电路资料</option><option value="any_ai">两类 AI 交叉研究</option><option value="ai_for_ic">AI用于芯片设计</option><option value="ic_for_ai">芯片用于AI计算</option><option value="general_ic">通用集成电路研究</option></select></label>
          <label class="text-xs text-stone-500">细分专题<select v-model="filters.topic" class="analysis-input"><option value="">全部专题</option><option v-for="topic in topics" :key="topic.id" :value="topic.id">{{ topic.name }}</option></select></label>
        </div>
        <label class="mt-4 block text-xs text-stone-500">进一步限定关键词<input v-model="filters.keyword" type="search" class="analysis-input" placeholder="例如 RTL、布局、模拟电路" /></label>
        <div class="mt-4 flex flex-wrap items-center gap-5 text-sm"><label class="flex items-center gap-2"><input v-model="filters.include_papers" type="checkbox" />文献</label><label class="flex items-center gap-2"><input v-model="filters.include_news" type="checkbox" />新闻</label><button type="button" class="text-xs text-accent" @click="lastMonth">近30天</button></div>
        <details class="mt-4 text-xs text-stone-500"><summary class="cursor-pointer">资料范围</summary><div class="mt-3 grid gap-3 sm:grid-cols-2"><label>文献范围<select v-model="filters.literature_scope" class="analysis-input"><option value="main">主文献库</option><option value="all">全部文献（含扩展归档）</option><option value="archive">扩展归档</option></select></label><label>新闻范围<select v-model="filters.news_scope" class="analysis-input"><option value="main">集成电路新闻与动态</option><option value="all">全部新闻（含拓展）</option><option value="archive">算力软件与应用拓展</option></select></label></div></details>
        <button type="submit" :disabled="loading || busy" class="mt-5 bg-accent px-5 py-2.5 text-sm text-white disabled:opacity-50">{{ loading ? '正在筛选…' : '筛选材料' }}</button>
      </form>
      <p v-if="error" role="alert" class="mt-4 text-sm text-red-600">{{ error }}</p>
      <section v-if="preview" class="mt-6 border border-stone-200 p-5 dark:border-stone-800" aria-label="分析材料清单">
        <h3 class="font-serif text-xl font-semibold">确认分析材料 <span class="text-sm font-normal text-stone-500">文献 {{ preview.counts.paper || 0 }} · 新闻 {{ preview.counts.news || 0 }}</span></h3>
        <p v-if="preview.excluded.incomplete_publication_date" class="mt-2 text-xs text-stone-500">当前研究范围内 {{ preview.excluded.incomplete_publication_date }} 条资料未提供精确发表日，未纳入日期筛选。</p>
        <p class="mt-2 text-xs text-stone-500">研究主线和专题同时筛选文献与新闻；新闻按题名和简介匹配。</p>
        <p v-if="!preview.total" class="mt-5 text-sm text-stone-500">当前条件下没有材料，可调整时间、研究方向或资料范围。</p>
        <template v-else>
          <div class="mt-4 flex flex-wrap items-center gap-4 text-xs"><button type="button" :disabled="preview.total>options.max_sources" class="text-accent disabled:text-stone-400" @click="selected=preview.sources.map(s=>s.id)">全选</button><button v-if="preview.total>options.max_sources" type="button" class="text-accent" @click="pickLatest">选取最新 {{ options.max_sources }} 条</button><button type="button" class="text-stone-500" @click="selected=[]">清空选择</button><span class="ml-auto text-stone-500">已选 {{ selected.length }} / {{ preview.total }} 条，单次最多 {{ options.max_sources }} 条</span></div>
          <div class="mt-3 max-h-96 divide-y divide-stone-100 overflow-y-auto border-y border-stone-200 dark:divide-stone-800 dark:border-stone-800">
            <label v-for="source in preview.sources" :key="source.id" class="flex gap-3 py-3 text-sm"><input type="checkbox" class="mt-1 shrink-0" :aria-label="`选择 ${source.title}`" :checked="selected.includes(source.id)" :disabled="!selected.includes(source.id) && selected.length>=options.max_sources" @change="toggle(source.id,($event.target as HTMLInputElement).checked)" /><span class="min-w-0"><span class="mr-2 text-xs text-accent">{{ source.ref }} · {{ source.content_type==='paper' ? source.venue_type==='preprint' ? '预印本' : '文献' : '新闻' }}</span>{{ source.title }}<span class="mt-1 block text-xs text-stone-400">{{ dateLabel(source) }} · {{ source.source }} · {{ quality[source.evidence_quality] }}</span></span></label>
          </div>
          <div class="mt-4 flex flex-wrap items-center gap-4"><button type="button" :disabled="IS_STATIC || busy || selected.length<2 || !connection?.key_configured" class="bg-accent px-5 py-2.5 text-sm text-white disabled:opacity-50" @click="start">{{ busy ? '分析进行中…' : '生成相关性分析' }}</button><span class="text-xs text-stone-500">文献 {{ chosenCounts.paper }} · 新闻 {{ chosenCounts.news }}；{{ IS_STATIC ? '静态展示可预览材料选择，暂不在线生成报告。' : '发送选中资料的题名与摘要/简介至所配置模型服务。' }}</span></div>
        </template>
      </section>
      <section v-if="active" class="mt-7" aria-label="分析报告">
        <div v-if="active.status==='running'" role="status" class="border border-stone-200 p-5 text-sm leading-7 dark:border-stone-800"><p>正在分析 {{ active.source_count }} 条材料，模型 {{ active.model }}。完成后会自动显示报告，也可稍后从分析记录打开。</p><button v-if="error" type="button" class="mt-2 text-accent underline" @click="error='';loadRun(active.id)">重新读取状态</button></div>
        <div v-if="active.status==='failed'" role="alert" class="border border-red-200 p-5 text-sm text-red-600"><p>{{ failureMessage(active) }}</p><p class="mt-2 text-xs text-stone-500">已保留当次选中的 {{ active.source_count }} 条材料，可以使用当前模型设置重新生成。</p><button type="button" :disabled="busy || !connection?.key_configured" class="mt-4 bg-accent px-4 py-2 text-sm text-white disabled:opacity-50" @click="retry">{{ starting ? '正在重试…' : '按原材料重试' }}</button></div>
        <p v-if="active.usage?.total_tokens" class="my-3 text-xs leading-6 text-stone-500">本次用量：输入 {{ active.usage.prompt_tokens || 0 }} · 输出 {{ active.usage.completion_tokens || 0 }}<span v-if="active.usage.reasoning_tokens!==undefined">（含思考 {{ active.usage.reasoning_tokens }}）</span> · 合计 {{ active.usage.total_tokens }} token<span v-if="active.elapsed_seconds!==undefined"> · 用时 {{ active.elapsed_seconds }} 秒</span></p>
        <template v-if="report && active.status==='success'">
          <header class="border-b-2 border-stone-900 pb-4 dark:border-stone-100"><span class="text-xs text-accent">模型分析草稿 · 待人工核验</span><h3 class="mt-2 font-serif text-2xl font-bold">{{ report.title }}</h3><p class="mt-2 text-xs leading-6 text-stone-500">{{ active.filters.date_from }} 至 {{ active.filters.date_to }} · 按{{ active.filters.date_basis==='published' ? '发表日期' : '收录日期' }}筛选 · 匹配 {{ active.matched_count }} 条 / 分析 {{ active.source_count }} 条 · {{ active.model }}</p><a v-if="!IS_STATIC" :href="`/api/analysis/runs/${active.id}/export`" download class="mt-2 inline-block text-xs text-accent underline">导出分析报告</a></header>
          <p class="mt-3 text-xs leading-6 text-stone-500">{{ trackLabels[active.filters.research_track] }} · {{ options.topics.find(t=>t.id===active.filters.topic)?.name || '全部专题' }} · 文献 {{ active.counts.paper || 0 }} / 新闻 {{ active.counts.news || 0 }}<span v-if="active.filters.keyword"> · 关键词：{{ active.filters.keyword }}</span></p>
          <div class="mt-5"><AnalysisClaim :claim="report.overview" /></div>
          <h4 class="mt-7 font-serif text-xl font-semibold">该时间段的研究动向</h4>
          <article v-for="(trend,index) in report.trends" :key="index" class="mt-5 border-l-2 border-accent/30 pl-4"><h5 class="mb-3 font-semibold">{{ trend.title }}</h5><p class="mb-1 text-xs text-stone-400">来源陈述</p><AnalysisClaim :claim="trend.observation" /><p class="mb-1 mt-3 text-xs text-stone-400">模型推断</p><AnalysisClaim :claim="trend.interpretation" /></article>
          <h4 class="mb-4 mt-7 font-serif text-xl font-semibold">文献与新闻的关联 <span class="text-xs font-normal text-stone-400">模型推断</span></h4><div v-for="(claim,index) in report.connections" :key="index" class="mt-4"><AnalysisClaim :claim="claim" /></div><p v-if="!report.connections.length" class="text-sm text-stone-500">现有材料不足以支持明确的跨来源关联。</p>
          <section class="mt-7 border border-accent/30 bg-accent/5 p-5"><h4 class="mb-3 font-serif text-xl font-semibold">值得进一步探索的候选问题</h4><AnalysisClaim :claim="report.research_question.question" /><h5 class="mb-2 mt-5 text-sm font-semibold">为什么值得探索</h5><AnalysisClaim :claim="report.research_question.motivation" /><div class="mt-5 grid gap-5 sm:grid-cols-2"><div><h5 class="mb-2 text-sm font-semibold">探索路径</h5><ol class="list-decimal space-y-2 pl-5 text-sm leading-7"><li v-for="(text,index) in report.research_question.approach" :key="index">{{ text }}</li></ol></div><div><h5 class="mb-2 text-sm font-semibold">如何验证</h5><ol class="list-decimal space-y-2 pl-5 text-sm leading-7"><li v-for="(text,index) in report.research_question.validation" :key="index">{{ text }}</li></ol></div></div><p class="mt-4 text-xs text-stone-500">候选问题由所选材料启发，新颖性与可行性仍需进一步检索和实验确认。</p></section>
          <details class="mt-5 text-sm text-stone-500"><summary class="cursor-pointer">局限与待核验</summary><ul class="mt-3 list-disc space-y-2 pl-5"><li>分析依据题名及已收录摘要/简介，未逐篇阅读全文。</li><li v-for="(text,index) in report.limitations" :key="index">{{ text }}</li></ul></details>
          <section class="mt-7"><h4 class="font-serif text-xl font-semibold">信息来源与分析材料</h4><article v-for="source in active.sources" :id="`analysis-source-${source.ref}`" :key="source.ref" class="scroll-mt-5 border-b border-stone-200 py-4 dark:border-stone-800"><p class="text-sm leading-7"><span class="mr-2 font-semibold text-accent">{{ source.ref }}</span>{{ source.title }}</p><p class="mt-1 text-xs leading-6 text-stone-500">{{ source.content_type==='paper' ? source.venue_type==='preprint' ? '预印本' : '文献' : '新闻' }} · {{ source.source }} · 发表 {{ dateLabel(source) }} · 收录 {{ localTimeLabel(source.collected_at) }} · {{ quality[source.evidence_quality] }}</p><div class="mt-2 flex gap-4 text-xs"><router-link :to="`/discover/item/${source.id}`" class="text-accent">资料详情</router-link><a v-if="safeExternalUrl(source.url)" :href="safeExternalUrl(source.url)" target="_blank" rel="noopener noreferrer" class="text-accent">原始出处 ↗</a></div><details class="mt-2 text-xs text-stone-500"><summary class="cursor-pointer">查看本次分析使用的材料片段</summary><p class="mt-2 whitespace-pre-wrap leading-7">{{ source.excerpt || '仅使用题名。' }}</p><p v-if="source.excerpt_truncated">材料过长，本次使用前4000字符。</p></details></article></section>
        </template>
      </section>
      <details v-if="history.length" class="mt-7 border-t border-stone-200 pt-5 dark:border-stone-800"><summary class="cursor-pointer text-sm text-stone-500">分析记录（最近 {{ history.length }} 次）</summary><div class="mt-3 divide-y divide-stone-100 dark:divide-stone-800"><button v-for="run in history" :key="run.id" type="button" :disabled="loadingRun || busy" class="block w-full py-3 text-left text-sm disabled:opacity-50" @click="openRun(run.id)">{{ localTimeLabel(run.created_at) }} · {{ run.filters.date_from }} 至 {{ run.filters.date_to }} · {{ run.source_count }} 条 <span class="ml-2 text-xs text-stone-500">{{ run.status==='success' ? '已完成' : run.status==='running' ? '分析中' : '未完成' }}</span></button></div></details>
    </template>
  </div>
</template>

<style scoped>
.analysis-input { @apply mt-2 block w-full border border-stone-300 bg-white px-3 py-2.5 text-sm text-stone-800 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-200; }
</style>
