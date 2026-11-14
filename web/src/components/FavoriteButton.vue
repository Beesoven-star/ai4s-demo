<script setup lang="ts">
import { ref, watch } from 'vue'
import type { DiscoveryItem } from '../discovery-types'
import { updatePersonalRecord } from '../api/discovery'
const props = defineProps<{ item: DiscoveryItem }>()
const emit = defineEmits<{ changed: [] }>()
const saved = ref(false)
const busy = ref(false)
const error = ref('')
watch(() => [props.item.id, props.item.library?.is_favorite], () => { saved.value = !!props.item.library?.is_favorite }, { immediate: true })
async function toggle() {
  busy.value = true; error.value = ''
  try {
    const record = await updatePersonalRecord(props.item.id, { is_favorite: !saved.value })
    saved.value = record.is_favorite
    emit('changed')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '收藏操作失败' }
  finally { busy.value = false }
}
</script>
<template>
  <div class="mt-3"><button type="button" :disabled="busy" :aria-pressed="saved" class="border border-accent/40 px-3 py-1.5 text-xs text-accent disabled:opacity-50" @click="toggle">{{ busy ? '保存中…' : saved ? '取消收藏' : '收藏到个人库' }}</button><p v-if="error" role="alert" class="mt-2 text-xs text-red-600">{{ error }}</p></div>
</template>
