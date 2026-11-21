<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listPersonalLibrary, localTimeLabel, publicationLabel, READING_LABELS } from '../api/discovery'
import type { PersonalList } from '../api/discovery'
import FavoriteButton from '../components/FavoriteButton.vue'
import { IS_STATIC } from '../static-mode'
const route = useRoute()
const router = useRouter()
const result = ref<PersonalList | null>(null)
const loading = ref(true)
const error = ref('')
const q = ref(''), status = ref(''), topic = ref(''), tag = ref(''), type = ref('')
const offset = ref(0)
let generation = 0
let controller: AbortController | undefined
async function load() {
  const current = ++generation
  controller?.abort(); controller = new AbortController()
  loading.value = true; error.value = ''
  const text = (key: string) => typeof route.query[key] === 'string' ? String(route.query[key]) : ''
  q.value = text('q'); status.value = text('reading_status'); topic.value = text('topic'); tag.value = text('personal_tag'); type.value = text('content_type')
  const n = Number(text('offset'))
  offset.value = Number.isSafeInteger(n) && n >= 0 ? n : 0
  try {
    const data = await listPersonalLibrary({ q: q.value, reading_status: status.value, topic: topic.value, personal_tag: tag.value, content_type: type.value, offset: offset.value, limit: 20 }, controller.signal)
    if (current === generation) result.value = data
  } catch (cause) { if (current === generation) error.value = cause instanceof Error ? cause.message : '读取失败' }
  finally { if (current === generation) loading.value = false }
}
async function query(nextOffset = 0) {
  const params: Record<string, string> = {}
  for (const [key, value] of Object.entries({ q: q.value, reading_status: status.value, topic: topic.value, personal_tag: tag.value, content_type: type.value })) if (value.trim()) params[key] = value.trim()
  if (nextOffset) params.offset = String(nextOffset)
  if (router.resolve({ path: '/library', query: params }).fullPath === route.fullPath) await load()
  else await router.push({ path: '/library', query: params })
}
async function reset() { q.value = ''; status.value = ''; topic.value = ''; tag.value = ''; type.value = ''; await query() }
watch(() => route.fullPath, load, { immediate: true })
onBeforeUnmount(() => { ++generation; controller?.abort() })
</script>
<template>
  <div>
    <p class="text-[11px] font-semibold tracking-[0.22em] text-accent">PERSONAL RESEARCH LIBRARY</p>
    <h2 class="mt-3 font-serif text-3xl font-bold">我的收藏</h2>
    <p class="mt-3 text-sm leading-7 text-stone-500">保存值得继续阅读的论文与动态，记录自己的判断和阅读进度。</p>
    <p v-if="IS_STATIC" class="mt-2 text-xs leading-6 text-stone-500">收藏和备注保存在当前浏览器，刷新或关闭网页后仍保留。清除网站数据或结束无痕浏览会删除记录。</p>
    <p v-if="result" class="mt-4 text-sm text-stone-500">当前资料库收藏 {{ result.facets.total }} 条 · 待读 {{ result.facets.status_counts.unread || 0 }} · 阅读中 {{ result.facets.status_counts.reading || 0 }} · 已读 {{ result.facets.status_counts.read || 0 }} · 重点跟进 {{ result.facets.status_counts.follow_up || 0 }}</p>
    <form class="my-6 grid gap-4 border-y border-stone-200 py-5 sm:grid-cols-2 dark:border-stone-700" @submit.prevent="query()">
      <label class="sm:col-span-2"><span class="mb-2 block text-xs">关键词（资料、备注或个人标签）</span><input v-model="q" type="search" class="library-input" placeholder="检索标题、摘要或自己的备注"/></label>
      <label><span class="mb-2 block text-xs">阅读状态</span><select v-model="status" class="library-input"><option value="">全部状态</option><option v-for="(label, value) in READING_LABELS" :key="value" :value="value">{{ label }}</option></select></label>
      <label><span class="mb-2 block text-xs">研究专题</span><select v-model="topic" class="library-input"><option value="">全部专题</option><option v-for="value in result?.facets.topics" :key="value" :value="value">{{ value }}</option></select></label>
      <label><span class="mb-2 block text-xs">个人标签</span><select v-model="tag" class="library-input"><option value="">全部个人标签</option><option v-for="value in result?.facets.personal_tags" :key="value" :value="value">{{ value }}</option></select></label>
      <label><span class="mb-2 block text-xs">资料类型</span><select v-model="type" class="library-input"><option value="">全部类型</option><option value="paper">论文</option><option value="news">新闻与动态</option></select></label>
      <div class="flex flex-wrap gap-3 sm:col-span-2"><button type="submit" :disabled="loading" class="bg-accent px-5 py-2 text-sm text-white disabled:opacity-50">筛选收藏</button><button type="button" class="border border-stone-300 px-4 py-2 text-sm dark:border-stone-600" @click="reset">重置条件</button><router-link to="/discover" class="px-2 py-2 text-sm text-accent">去每日发现挑选资料 →</router-link></div>
    </form>
    <p v-if="loading" role="status" class="py-10 text-sm text-stone-500">正在读取个人信息库…</p>
    <div v-else-if="error" role="alert" class="py-6 text-sm text-red-600">{{ error }} <button class="underline" @click="load">重试</button></div>
    <template v-else-if="result">
      <p aria-live="polite" class="mb-4 text-sm text-stone-500">找到 {{ result.total }} 条收藏</p>
      <div v-if="!result.items.length" class="border border-dashed border-stone-300 p-8 text-center text-sm leading-7 text-stone-500">{{ result.facets.total ? '没有匹配的收藏，可放宽条件或返回第一页。' : '还没有收藏。到每日发现中点击“收藏到个人库”，或进入详情保存备注。' }}<button v-if="offset" class="ml-2 text-accent underline" @click="query()">返回第一页</button></div>
      <article v-for="item in result.items" :key="item.id" class="mb-4 border border-stone-200 p-5 dark:border-stone-700">
        <p class="text-xs leading-6 text-stone-500">{{ item.content_type === 'paper' ? '论文' : '新闻与动态' }} · {{ publicationLabel(item) }} · {{ READING_LABELS[item.library!.reading_status] }}</p>
        <router-link :to="{ path: `/discover/item/${item.id}`, query: { from: route.fullPath } }" class="mt-2 block text-base font-semibold leading-7 hover:text-accent">{{ item.title }}</router-link>
        <p class="mt-2 text-xs leading-6 text-accent">{{ item.topics.join(' · ') || '专题待分类' }}<span v-if="item.library?.personal_tags.length"> · 个人标签：{{ item.library.personal_tags.join('、') }}</span></p>
        <p class="mt-3 whitespace-pre-wrap break-words text-sm leading-7 text-stone-600 dark:text-stone-300">{{ item.library?.notes || '尚未填写个人备注' }}</p>
        <p class="mt-2 text-xs text-stone-500">收藏于 {{ localTimeLabel(item.library?.saved_at) }}</p>
        <div class="flex flex-wrap items-center gap-4"><FavoriteButton :item="item" @changed="load"/><router-link :to="{ path: `/discover/item/${item.id}`, query: { from: route.fullPath, edit: 'notes' } }" class="mt-3 text-sm text-accent underline">编辑备注与状态</router-link></div>
      </article>
      <nav v-if="result.total > 20 || offset" class="mt-5 flex items-center justify-between text-sm" aria-label="收藏分页"><button :disabled="offset === 0" class="border px-4 py-2 disabled:opacity-30" @click="query(Math.max(0, offset - 20))">上一页</button><span>{{ Math.floor(offset / 20) + 1 }} / {{ Math.max(1, Math.ceil(result.total / 20)) }}</span><button :disabled="offset + 20 >= result.total" class="border px-4 py-2 disabled:opacity-30" @click="query(offset + 20)">下一页</button></nav>
    </template>
  </div>
</template>
<style scoped>
.library-input { @apply w-full min-w-0 border border-stone-300 bg-white px-3 py-2 text-sm dark:border-stone-600 dark:bg-stone-900; }
</style>
