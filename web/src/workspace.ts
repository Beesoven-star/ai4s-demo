import { reactive, readonly } from 'vue'
import { IS_STATIC } from './static-mode'

// Report navigation follows the server's workspace, never the current URL alone.
const state = reactive({ reportsEnabled: false })
export const workspace = readonly(state)
let pending: Promise<void> | undefined

export function loadWorkspace(): Promise<void> {
  if (IS_STATIC) return Promise.resolve()
  if (!pending) {
    pending = fetch('/api/workspace', { cache: 'no-store' })
      .then(async response => {
        if (!response.ok) return
        const options = await response.json()
        state.reportsEnabled = options.reports_enabled === true
      })
      // Core discovery pages remain usable if the optional report configuration fails.
      .catch(() => { state.reportsEnabled = false })
  }
  return pending
}
