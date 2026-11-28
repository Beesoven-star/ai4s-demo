import { IS_STATIC } from '../static-mode'
import { loadSnapshot } from './static-data'
import type { ICBriefing, ICDailyEdition } from '../briefing-types'
import { snapshotArchive, type ObservationPeriod, type PublicationVersion } from './observation-archive'

export async function getICBriefing(days: number, signal?: AbortSignal, snapshotOnly = false): Promise<ICBriefing> {
  if (IS_STATIC) {
    const snapshot = await loadSnapshot(signal)
    const result = (snapshotOnly ? undefined : snapshot.ic_rankings?.[String(days)])
      ?? snapshot.ic_briefing?.[String(days)]
    if (!result) throw new Error('当前展示快照尚未包含技术榜单，请重新导出展示数据。')
    return result
  }
  const query = new URLSearchParams({ days: String(days) })
  if (snapshotOnly) query.set('snapshot', 'true')
  const response = await fetch(`/api/discovery/ic-briefing?${query}`, { signal, cache: 'no-store' })
  if (!response.ok) throw new Error(`技术观察读取失败（${response.status}）`)
  return response.json()
}

export async function getICObservations(day?: string, signal?: AbortSignal, version?: string): Promise<{
  today: string; selected_day: string; editions: ObservationPeriod[]; report: ICDailyEdition | null; versions?: PublicationVersion[]
  automation?: { status: 'queued' | 'running' | 'failed' | 'unchanged' | 'empty' | 'published' } | null
}> {
  if (IS_STATIC) {
    const snapshot = await loadSnapshot(signal)
    const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format()
    const reports = (snapshot.daily_observations || []).filter(edition => edition.date <= today)
    return { today, ...snapshotArchive(reports, { day, version, distinctDaily: true }) }
  }
  const query = new URLSearchParams()
  if (day) query.set('day', day)
  if (version) query.set('version', version)
  const response = await fetch(`/api/discovery/ic-observations?${query}`, { signal, cache: 'no-store' })
  if (!response.ok) throw new Error(`观察记录读取失败（${response.status}）`)
  return response.json()
}
