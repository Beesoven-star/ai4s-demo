<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppSidebar from './components/AppSidebar.vue'
import { SECTION_LABEL } from './sections'

const route = useRoute()

// 页脚小字随当前页面变化:栏目页用栏目全名(如"与当前工作的相关性"),其余页面用页面名
const pageName = computed(() => {
  if (route.name === 'section' || route.name === 'section-weekly') {
    return SECTION_LABEL[String(route.params.key)] ?? '每日研判'
  }
  switch (route.name) {
    case 'library':
      return '我的收藏'
    case 'research-analysis':
      return '相关性分析'
    case 'ic-exploration':
      return '集成电路主题探索'
    case 'discover':
      return '每日发现'
    case 'discover-detail':
      return '资料详情'
    case 'workdocs':
      return '工作文档'
    case 'list':
      return '每日研判归档'
    case 'list-weekly':
      return '每周研判归档'
    case 'detail':
      return '研判归档'
    case 'settings':
      return '设置'
    default:
      return '每日研判'
  }
})
</script>

<template>
  <div class="min-h-screen lg:flex">
    <AppSidebar />
    <div class="min-w-0 flex-1">
      <main class="mx-auto max-w-4xl px-4 py-8 sm:px-6">
        <router-view :key="route.name" />
      </main>
      <footer
        class="border-t border-stone-200 py-6 text-center text-xs text-stone-400 dark:border-stone-800 dark:text-stone-600"
      >
        {{ pageName }} · 科研信息工作台
      </footer>
    </div>
  </div>
</template>
