<script setup lang="ts">
import { computed, ref } from 'vue'
import type { DiscoveryItem, PersonalRecord, ReadingStatus } from '../discovery-types'
import { localTimeLabel, READING_LABELS, updatePersonalRecord } from '../api/discovery'
import { IS_STATIC } from '../static-mode'
const props = defineProps<{ item: DiscoveryItem }>()
const initial = props.item.library
const record = ref<PersonalRecord>(initial || { is_favorite: false, notes: '', reading_status: 'unread', personal_tags: [], saved_at: null, updated_at: null })
const notes = ref(record.value.notes)
const status = ref<ReadingStatus>(record.value.reading_status)
const tags = ref(record.value.personal_tags.join('，'))
const busy = ref(false)
const message = ref('')
const error = ref('')
const dirty = computed(() => notes.value !== record.value.notes || status.value !== record.value.reading_status || tags.value !== record.value.personal_tags.join('，'))
async function save(onlyToggle = false) {
  busy.value = true; error.value = ''; message.value = ''
  try {
    const changes = onlyToggle ? { is_favorite: !record.value.is_favorite } : {
      is_favorite: true, notes: notes.value, reading_status: status.value,
      personal_tags: [...new Set(tags.value.split(/[,，;；\n]/).map(t => t.trim()).filter(Boolean))],
    }
    record.value = await updatePersonalRecord(props.item.id, changes)
    if (!onlyToggle) tags.value = record.value.personal_tags.join('，')
    message.value = onlyToggle ? record.value.is_favorite ? '已加入我的收藏。' : '已取消收藏，已保存的备注和阅读记录仍保留。' : '备注、阅读状态和个人标签已保存。'
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '保存失败，请重试' }
  finally { busy.value = false }
}
</script>
<template>
  <section class="mt-7 border border-accent/30 bg-accent/5 p-5" aria-label="个人信息库">
    <div class="flex flex-wrap items-center justify-between gap-3"><h3 class="font-serif text-xl font-semibold">个人信息库</h3><router-link to="/library" class="text-sm text-accent underline">我的收藏 →</router-link></div>
    <div class="mt-4 flex flex-wrap items-center gap-3"><button type="button" :disabled="busy" :aria-pressed="record.is_favorite" class="border border-accent/40 px-4 py-2 text-sm text-accent disabled:opacity-50" @click="save(true)">{{ record.is_favorite ? '取消收藏' : '收藏到个人库' }}</button><span v-if="record.saved_at" class="text-xs text-stone-500">首次收藏：{{ localTimeLabel(record.saved_at) }}</span></div>
    <form class="mt-5 space-y-4" @submit.prevent="save()">
      <div><label for="personal-status" class="mb-2 block text-sm">阅读状态</label><select id="personal-status" v-model="status" :disabled="busy" class="w-full border border-stone-300 bg-white px-3 py-2 text-sm dark:border-stone-600 dark:bg-stone-900"><option v-for="(label, value) in READING_LABELS" :key="value" :value="value">{{ label }}</option></select></div>
      <div><label for="personal-tags" class="mb-2 block text-sm">个人标签</label><input id="personal-tags" v-model="tags" :disabled="busy" class="w-full border border-stone-300 bg-white px-3 py-2 text-sm dark:border-stone-600 dark:bg-stone-900" placeholder="例如：待精读，工具反馈，方法比较"/><p class="mt-1 text-xs text-stone-500">用逗号分隔，最多20个；与来源专题分别保存。</p></div>
      <div><label for="personal-notes" class="mb-2 block text-sm">我的备注</label><textarea id="personal-notes" v-model="notes" :disabled="busy" maxlength="20000" rows="5" class="w-full border border-stone-300 bg-white px-3 py-2 text-sm leading-7 dark:border-stone-600 dark:bg-stone-900" placeholder="记录研究任务、方法、评价设置，以及需要继续核验的问题。"/></div>
      <div class="flex flex-wrap items-center gap-3"><button type="submit" :disabled="busy" class="bg-accent px-5 py-2.5 text-sm text-white disabled:opacity-50">{{ busy ? '保存中…' : record.is_favorite ? '保存备注与状态' : '保存并收藏' }}</button><span v-if="dirty" class="text-xs text-amber-700">有尚未保存的修改</span><span v-else-if="record.updated_at" class="text-xs text-stone-500">已保存 {{ localTimeLabel(record.updated_at) }}</span></div>
    </form>
    <p v-if="message" role="status" class="mt-3 text-sm text-emerald-700 dark:text-emerald-400">{{ message }}</p><p v-if="error" role="alert" class="mt-3 text-sm text-red-600">{{ error }}</p>
    <p class="mt-4 text-xs leading-6 text-stone-500">修改后点击保存。取消收藏保留已保存的备注和阅读记录，可再次收藏恢复。{{ IS_STATIC ? '记录保存在你当前的浏览器中，刷新或关闭网页后仍保留；清除网站数据或结束无痕浏览会删除记录。' : '记录保存在当前主题的本机资料库。' }}</p>
  </section>
</template>
