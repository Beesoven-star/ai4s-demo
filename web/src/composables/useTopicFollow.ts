import { computed, onMounted, onUnmounted, ref, toValue, watch, type MaybeRefOrGetter } from 'vue'
import type { TechnologyEvent } from '../api/ic-editor'

function progressKeys(event: TechnologyEvent): string[] {
  return [`event:${event.id}`, ...(event.stage_changes || []).map(change => `stage:${change.id}`)]
}

export function unreadTopicEvents(events: TechnologyEvent[], seen: string[] | null) {
  const read = new Set(seen || [])
  return seen === null ? [] : events.filter(event => progressKeys(event).some(key => !read.has(key)))
}

function storagePrefix() {
  return `ai4s:${new URL(import.meta.env.BASE_URL, location.href).pathname}:topic-follow:v1:`
}

export function followedTopicIds() {
  const prefix = storagePrefix()
  return Object.keys(localStorage).filter(key => key.startsWith(prefix)).map(key => key.slice(prefix.length))
}

export function savedTopicProgress(topicId: string) {
  const stored = localStorage.getItem(storagePrefix() + topicId)
  if (stored === null || stored === '1') return stored
  const keys: unknown = JSON.parse(stored)
  if (!Array.isArray(keys) || !keys.every(value => typeof value === 'string')) throw new Error('Invalid follow state')
  return keys as string[]
}

export function initializeFollowProgress(topicId: string, events: TechnologyEvent[]) {
  if (savedTopicProgress(topicId) === '1') localStorage.setItem(storagePrefix() + topicId, JSON.stringify(events.flatMap(progressKeys)))
}

export function useTopicFollow(topicId: MaybeRefOrGetter<string>) {
  const key = computed(() => storagePrefix() + toValue(topicId))
  const followed = ref(false)
  const seen = ref<string[] | null>(null)
  const error = ref('')

  function readFollow() {
    try {
      const stored = savedTopicProgress(toValue(topicId))
      followed.value = stored !== null
      seen.value = Array.isArray(stored) ? stored : null
      error.value = ''
    } catch {
      error.value = '无法读取浏览器中的关注记录。'
    }
  }

  function setFollowed(next: boolean, events: TechnologyEvent[]) {
    try {
      const keys = [...new Set(events.flatMap(progressKeys))]
      if (next) localStorage.setItem(key.value, JSON.stringify(keys))
      else localStorage.removeItem(key.value)
      followed.value = next
      seen.value = next ? keys : null
      error.value = ''
    } catch {
      error.value = '无法保存关注状态，请检查浏览器的网站存储设置。'
    }
  }

  function markViewed(events: TechnologyEvent[]) {
    try {
      const stored = savedTopicProgress(toValue(topicId))
      if (stored === null) return
      const prior = Array.isArray(stored) ? stored : []
      const keys = [...new Set([...prior, ...events.flatMap(progressKeys)])]
      if (stored === '1' || keys.length !== prior.length) localStorage.setItem(key.value, JSON.stringify(keys))
      seen.value = keys
      error.value = ''
    } catch {
      error.value = '无法保存专题查看记录，请检查浏览器的网站存储设置。'
    }
  }

  function sync(event: StorageEvent) {
    if (event.key === key.value || event.key === null) readFollow()
  }

  onMounted(() => {
    readFollow()
    window.addEventListener('storage', sync)
  })
  watch(key, readFollow)
  onUnmounted(() => window.removeEventListener('storage', sync))

  return { followed, seen, error, setFollowed, markViewed }
}
