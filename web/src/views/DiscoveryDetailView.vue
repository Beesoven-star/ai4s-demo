<script setup lang="ts">
import ICRelationPanel from '../components/ICRelationPanel.vue'
import PublicationPeriodBadge from '../components/PublicationPeriodBadge.vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  dateKindLabel, getDiscoveryItem, localTimeLabel,
  publicationLabel, safeExternalUrl, venueLabel,
} from '../api/discovery'
import type { DiscoveryItem } from '../discovery-types'
import PersonalLibraryPanel from '../components/PersonalLibraryPanel.vue'

const props = defineProps<{ id: string }>()
const route = useRoute()
const item = ref<DiscoveryItem | null>(null)
const loading = ref(true)
const error = ref('')
let requestNumber = 0
let controller: AbortController | undefined

const listPath = computed(() => {
  const from = route.query.from
  return typeof from === 'string' && /^\/(?:discover|library)(?:\?|$)/.test(from)
    ? from : item.value?.content_type === 'news' ? '/discover?content_type=news' : '/discover?content_type=paper'
})
const relevanceLabels: Record<string, string> = {
  pending: '相关性待核验',
  core: '核心相关', candidate_core: '核心相关候选',
  transferable_method: '方法可迁移', transferable_application: '相关应用',
  related_tool: '相关工具',
}
const relevance = computed(() => relevanceLabels[item.value?.relevance || ''] || '待进一步判断')
const abstractView = computed(() => {
  const original = item.value?.abstract_text?.trim()
  if (original) return { title: item.value?.content_type === 'news' ? '来源简介' : '原始摘要', text: original, human: false }
  const summary = item.value?.summary?.trim()
  if (item.value?.summary_kind === 'human' && summary) {
    return { title: '人工简述', text: summary, human: true }
  }
  return { title: '原始摘要', text: '', human: false }
})

async function load() {
  const currentRequest = ++requestNumber
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  error.value = ''
  item.value = null
  try {
    const result = await getDiscoveryItem(props.id, controller.signal)
    if (currentRequest === requestNumber) item.value = result
  } catch (cause) {
    if (currentRequest === requestNumber) error.value = cause instanceof Error ? cause.message : '条目加载失败'
  } finally {
    if (currentRequest === requestNumber) loading.value = false
  }
}

watch(() => props.id, () => { void load() }, { immediate: true })
onBeforeUnmount(() => { ++requestNumber; controller?.abort() })
</script>

<template>
  <div>
    <router-link :to="listPath" class="inline-block text-sm text-stone-500 hover:text-accent dark:text-stone-400">{{ listPath.startsWith('/library') ? '← 返回我的收藏' : '← 返回每日发现' }}</router-link>
    <p v-if="loading" role="status" class="py-20 text-center text-sm text-stone-400">正在读取条目…</p>
    <div v-else-if="error" role="alert" class="mt-8 border border-red-200 bg-red-50 p-6 dark:border-red-900 dark:bg-red-950/30"><h2 class="font-serif text-xl text-red-800 dark:text-red-300">暂时无法打开这条资料</h2><p class="mt-3 text-sm text-red-600 dark:text-red-400">{{ error }}</p><button type="button" class="mt-4 text-sm text-accent underline underline-offset-4" @click="load">重新读取</button></div>
    <template v-else-if="item">
      <header class="mt-7">
        <div class="flex flex-wrap items-center gap-3 text-xs text-stone-400"><span class="px-2 py-1 font-semibold" :class="item.content_type === 'paper' ? 'bg-accent/10 text-accent' : 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400'">{{ item.content_type === 'paper' ? '研究论文' : '新闻与研究动态' }}</span><span>{{ item.origin === 'seed' ? '已核验样本' : '公开来源采集' }}</span><span>{{ relevance }}</span></div>
        <h2 class="mt-5 break-words font-serif text-2xl font-bold leading-relaxed text-stone-900 sm:text-3xl dark:text-stone-50">{{ item.title }}</h2>
        <p class="mt-4 break-words text-sm text-stone-500 dark:text-stone-400">采集来源：{{ item.source || '未提供' }}</p>
        <p v-if="item.news_genre" class="mt-2 text-xs text-stone-500">来源性质：{{ item.news_genre }}</p>
        <div class="mt-5 flex flex-wrap items-center gap-4 text-sm"><a v-if="safeExternalUrl(item.url)" :href="safeExternalUrl(item.url)" target="_blank" rel="noopener noreferrer" class="inline-block bg-accent px-5 py-2.5 font-medium text-white hover:bg-accent-soft">查看原始出处 ↗</a><span v-else class="text-stone-400">暂无有效原文链接</span><span class="text-xs leading-6 text-stone-400">全文访问以来源网站提供的权限为准。</span></div>
        <div class="mt-7 border-t-2 border-stone-900 dark:border-stone-100" /><div class="mt-[3px] border-t border-stone-300 dark:border-stone-700" />
      </header>

      <PersonalLibraryPanel :key="item.id" :item="item" />
      <ICRelationPanel v-if="item.ic_ai && item.content_type==='paper'" :analysis="item.ic_ai" />
      <div v-if="item.content_type==='paper'" class="mt-4"><PublicationPeriodBadge :item="item" /><p class="mt-2 text-xs leading-6 text-stone-500">平台收录时间与来源发表时间分别保存。近期预印本指首次提交，不等同于正式发表。</p></div>

      <dl class="mt-7 grid gap-x-8 gap-y-5 border-b border-stone-200 pb-7 text-sm sm:grid-cols-2 dark:border-stone-800">
        <div><dt class="text-xs text-stone-400">期刊 / 会议</dt><dd class="mt-2 break-words text-stone-700 dark:text-stone-200">{{ venueLabel(item) || (item.venue_type === 'preprint' ? '未提供（预印本）' : '未提供') }}</dd></div>
        <div v-if="item.conference_year"><dt class="text-xs text-stone-400">会议年份</dt><dd class="mt-2 tabular-nums text-stone-700 dark:text-stone-200">{{ item.conference_year }}</dd></div>
        <div v-if="item.track"><dt class="text-xs text-stone-400">会议 Track</dt><dd class="mt-2 break-words text-stone-700 dark:text-stone-200">{{ item.track }}</dd></div>
        <div><dt class="text-xs text-stone-400">{{ dateKindLabel(item.date_kind) }}</dt><dd class="mt-2 tabular-nums text-stone-700 dark:text-stone-200">{{ publicationLabel(item) }}</dd></div>
        <div><dt class="text-xs text-stone-400">收录时间（北京时间）</dt><dd class="mt-2 tabular-nums text-stone-700 dark:text-stone-200">{{ localTimeLabel(item.collected_at) }}</dd></div>
        <div><dt class="text-xs text-stone-400">DOI</dt><dd class="mt-2 break-all text-stone-700 dark:text-stone-200">{{ item.doi || '未提供' }}</dd></div>
        <div><dt class="text-xs text-stone-400">arXiv 标识</dt><dd class="mt-2 break-all text-stone-700 dark:text-stone-200">{{ item.arxiv_id || '未提供' }}</dd></div>
      </dl>

      <section class="mt-8" aria-label="条目摘要">
        <h3 class="font-serif text-xl font-semibold text-stone-900 dark:text-stone-100">{{ abstractView.title }}</h3>
        <p class="mt-4 whitespace-pre-wrap break-words text-sm leading-8 text-stone-600 dark:text-stone-300">{{ abstractView.text || '暂未收录原始摘要，请查看原始出处。' }}</p>
        <p v-if="abstractView.human" class="mt-3 text-xs leading-6 text-stone-400">{{ item.content_type==='news' ? '以上为依据官方检索或列表整理的人工简述，未作新闻全文核验。' : '当前未收录原始摘要，以上为依据来源材料整理的人工简述。' }}</p>
        <p v-for="(entry,index) in item.abstract_provenance || []" :key="index" class="mt-3 text-xs leading-6 text-stone-500">摘要补充来源：<a :href="safeExternalUrl(entry.url)" target="_blank" rel="noopener noreferrer" class="text-accent underline">{{ entry.source }}</a>。摘要补全不改变原发表日期精度。</p>
      </section>

      <section class="mt-8 border-t border-stone-200 pt-7 dark:border-stone-800" aria-label="研究分类">
        <h3 class="font-serif text-xl font-semibold text-stone-900 dark:text-stone-100">研究分类</h3>
        <dl class="mt-5 space-y-5 text-sm">
          <div><dt class="mb-2 text-xs text-stone-400">专题</dt><dd class="flex flex-wrap gap-2"><span v-for="tag in (item.ic_ai ? item.ic_ai.topics : item.topics)" :key="tag" class="border border-accent/20 bg-accent/5 px-2.5 py-1 text-xs text-accent">{{ tag }}</span><span v-if="!(item.ic_ai ? item.ic_ai.topics : item.topics).length" class="text-stone-400">待分类</span></dd></div>
        </dl>
      </section>

      <section class="mt-8 border border-stone-200 bg-white p-5 dark:border-stone-800 dark:bg-stone-900" aria-label="来源与核验说明">
        <h3 class="text-sm font-semibold text-stone-700 dark:text-stone-200">来源与核验说明</h3>
        <p class="mt-3 whitespace-pre-wrap break-words text-xs leading-7 text-stone-500 dark:text-stone-400">{{ item.verification_note || '本条保留来源信息，内容与分类仍需结合原文进一步核验。' }}</p>
        <a v-if="safeExternalUrl(item.url)" :href="safeExternalUrl(item.url)" target="_blank" rel="noopener noreferrer" class="mt-3 block break-all text-xs leading-6 text-accent hover:underline">{{ item.url }}</a>
      </section>
    </template>
  </div>
</template>
