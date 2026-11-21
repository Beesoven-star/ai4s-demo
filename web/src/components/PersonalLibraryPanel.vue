<script setup lang="ts">
import { computed, ref } from 'vue'
import type { DiscoveryItem, PersonalRecord, ReadingStatus } from '../discovery-types'
import { localTimeLabel, READING_LABELS, updatePersonalRecord } from '../api/discovery'
import { IS_STATIC } from '../static-mode'
const props = defineProps<{ item: DiscoveryItem; initiallyOpen?: boolean }>()
const initial = props.item.library
const record = ref<PersonalRecord>(initial || { is_favorite: false, notes: '', reading_status: 'unread', personal_tags: [], saved_at: null, updated_at: null })
const notes = ref(record.value.notes)
const status = ref<ReadingStatus>(record.value.reading_status)
const tags = ref(record.value.personal_tags.join('，'))
const busy = ref(false)
const message = ref('')
const error = ref('')
const editorOpen = ref(!!props.initiallyOpen)
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
    message.value = onlyToggle ? record.value.is_favorite ? '已收藏' : '已取消收藏' : '个人记录已保存'
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '保存失败，请重试' }
  finally { busy.value = false }
}
</script>
<template>
  <div class="mt-4">
    <div class="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm" role="group" aria-label="资料操作">
      <slot />
      <button type="button" :disabled="busy" :aria-pressed="record.is_favorite" :title="record.is_favorite ? '取消收藏' : undefined" class="rounded-md border border-stone-300 px-3 py-1.5 font-medium text-stone-700 hover:border-accent hover:text-accent disabled:opacity-50 dark:border-stone-600 dark:text-stone-300" :class="record.is_favorite ? 'border-accent/40 text-accent dark:text-accent' : ''" @click="save(true)">{{ record.is_favorite ? '已收藏' : '收藏' }}</button>
      <button type="button" :aria-expanded="editorOpen" aria-controls="personal-record-editor" class="py-1.5 text-stone-600 underline-offset-4 hover:text-accent hover:underline dark:text-stone-400" @click="editorOpen = !editorOpen">{{ editorOpen ? '收起个人记录' : '备注与状态' }}<span v-if="dirty" class="ml-1 text-xs text-amber-700 dark:text-amber-400">未保存</span></button>
      <span v-if="message" role="status" class="text-xs text-emerald-700 dark:text-emerald-400">{{ message }}</span>
    </div>
    <p v-if="error" role="alert" class="mt-2 text-sm text-red-700 dark:text-red-400">{{ error }}</p>
    <form v-show="editorOpen" id="personal-record-editor" aria-label="个人记录" class="mt-4 space-y-4 rounded-lg border border-stone-200 p-4 dark:border-stone-700" @submit.prevent="save()">
      <div class="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <div><label for="personal-status" class="mb-1 block text-sm">阅读状态</label><select id="personal-status" v-model="status" :disabled="busy" class="personal-input"><option v-for="(label, value) in READING_LABELS" :key="value" :value="value">{{ label }}</option></select></div>
        <div><label for="personal-tags" class="mb-1 block text-sm">个人标签</label><input id="personal-tags" v-model="tags" :disabled="busy" class="personal-input" placeholder="用逗号分隔，最多 20 个"/></div>
      </div>
      <div><label for="personal-notes" class="mb-1 block text-sm">我的备注</label><textarea id="personal-notes" v-model="notes" :disabled="busy" maxlength="20000" rows="3" class="personal-input leading-6" /></div>
      <div class="flex flex-wrap items-center gap-3"><button type="submit" :disabled="busy" class="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{{ busy ? '保存中…' : record.is_favorite ? '保存记录' : '保存并收藏' }}</button><router-link to="/library" class="text-sm text-accent hover:underline">我的收藏 →</router-link><span v-if="!dirty && record.updated_at" class="text-xs text-stone-600 dark:text-stone-400">保存于 {{ localTimeLabel(record.updated_at) }}</span></div>
      <p v-if="IS_STATIC" class="text-xs text-stone-600 dark:text-stone-400">个人记录保存在当前浏览器中。</p>
    </form>
  </div>
</template>

<style scoped>
.personal-input {
  @apply block w-full min-w-0 rounded-md border border-stone-300 bg-white px-3 py-2 text-sm dark:border-stone-700 dark:bg-stone-900;
}
</style>
