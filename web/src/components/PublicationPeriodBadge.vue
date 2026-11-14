<script setup lang="ts">
import type { DiscoveryItem } from '../discovery-types'
defineProps<{ item: DiscoveryItem }>()
</script>
<template>
  <span v-if="item.publication_timing" class="inline-block border px-2 py-0.5 text-[11px] leading-6" :class="item.publication_timing.kind.startsWith('recent') ? 'border-emerald-200 text-emerald-700 dark:border-emerald-800 dark:text-emerald-400' : 'border-stone-200 text-stone-500 dark:border-stone-700'" :title="item.publication_timing.note">{{ item.publication_timing.label }}</span>
</template>
