<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps<{ id: string; text: string; label: string }>()
const paragraph = ref<HTMLParagraphElement | null>(null)
const expanded = ref(false)
const overflowing = ref(false)
const showToggle = computed(() => overflowing.value || expanded.value)
let observer: ResizeObserver | undefined

function measureOverflow() {
  const element = paragraph.value
  if (!element) return
  const lineHeight = Number.parseFloat(getComputedStyle(element).lineHeight)
  const hasOverflow = Number.isFinite(lineHeight) && element.scrollHeight > lineHeight * 3 + 1
  if (overflowing.value !== hasOverflow) overflowing.value = hasOverflow
}

watch(() => props.text, async () => {
  expanded.value = false
  await nextTick()
  measureOverflow()
})

onMounted(() => {
  measureOverflow()
  observer = new ResizeObserver(measureOverflow)
  if (paragraph.value) observer.observe(paragraph.value)
})

onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <div class="mt-3">
    <p
      :id="id"
      ref="paragraph"
      class="break-words whitespace-pre-wrap text-sm leading-6 text-stone-600 dark:text-stone-400"
      :class="{ 'summary-preview-collapsed': !expanded }"
    ><span class="mr-2 text-xs text-stone-400">{{ label }}</span>{{ text }}</p>
    <button
      v-if="showToggle"
      type="button"
      :aria-expanded="expanded"
      :aria-controls="id"
      class="mt-1 rounded-sm text-xs leading-6 text-accent underline-offset-4 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      @click="expanded = !expanded"
    >{{ expanded ? '收起摘要' : '展开摘要' }}</button>
  </div>
</template>

<style scoped>
.summary-preview-collapsed {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
}
</style>
