import type { ICDailyEdition } from '../briefing-types'

export interface ObservationPeriod { date: string; date_from?: string; title: string }

export interface PublicationVersion extends ObservationPeriod { id: string; published_at?: string }

export interface ObservationArchive {
  selected_day: string
  editions: ObservationPeriod[]
  report: ICDailyEdition | null
  versions: PublicationVersion[]
  selected_version: string | null
}

function dailyVersionKey(report: ICDailyEdition) {
  const sources = [...new Set(report.entries.flatMap(entry =>
    (entry.sources?.length ? entry.sources : [entry.source]).map(source => source.id)))].sort()
  return sources.length ? JSON.stringify([sources, report.automation?.material_change]) : report.id || 'original'
}

function calendarWeek(day: string) {
  const date = new Date(`${day}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() - (date.getUTCDay() + 6) % 7)
  const start = date.toISOString().slice(0, 10)
  date.setUTCDate(date.getUTCDate() + 6)
  return { start, end: date.toISOString().slice(0, 10) }
}

function naturalWeekReport(report: ICDailyEdition | null | undefined) {
  if (!report || report.coverage_through) return report || null
  const { start, end } = calendarWeek(report.date)
  return { ...report, date_from: start, date: end, coverage_through: report.date,
    entries: report.entries.filter(entry => (entry.sources?.length ? entry.sources : [entry.source]).every(source =>
      Boolean(source.published_at && source.published_at >= start && source.published_at <= report.date))) }
}

export function snapshotArchive(
  reports: ICDailyEdition[],
  { day, version, original, distinctDaily = false, naturalWeek = false }: {
    day?: string; version?: string; original?: PublicationVersion; distinctDaily?: boolean; naturalWeek?: boolean
  },
): ObservationArchive {
  const rows = reports.map(report => ({
    id: report.id || 'original', date: report.date, date_from: report.date_from,
    title: report.title, published_at: report.published_at, report,
  }))
  rows.sort((a, b) => b.date.localeCompare(a.date)
    || (b.published_at || '').localeCompare(a.published_at || '') || b.id.localeCompare(a.id))
  const archive: (PublicationVersion & { report: ICDailyEdition | null })[] = rows
  if (original) archive.push({ ...original, report: null })
  if (naturalWeek) {
    const issues = new Map<string, typeof archive[number]>()
    for (const row of archive) {
      const { end } = calendarWeek(row.date)
      if (!issues.has(end) || (row.report?.coverage_through && !issues.get(end)?.report?.coverage_through)) issues.set(end, row)
    }
    const dates = [...issues.keys()].sort((a, b) => b.localeCompare(a))
    const requested = day || archive.find(row => row.id === version)?.date
    const selectedDay = requested && /^\d{4}-\d{2}-\d{2}$/.test(requested) ? calendarWeek(requested).end : dates[0] || ''
    const selected = original && version === 'original' && calendarWeek(original.date).end === selectedDay
      ? { ...original, report: null } : issues.get(selectedDay)
    return {
      selected_day: selectedDay, selected_version: selected?.id || null, report: naturalWeekReport(selected?.report), versions: [],
      editions: dates.map(date => ({ date, date_from: calendarWeek(date).start, title: issues.get(date)!.title })),
    }
  }
  const groups = new Map<string, typeof archive>()
  for (const row of archive) {
    const group = groups.get(row.date) || []
    group.push(row)
    groups.set(row.date, group)
  }
  const days = [...groups.keys()].sort((a, b) => b.localeCompare(a))
  const selectedDay = day ?? archive.find(row => row.id === version)?.date ?? days[0] ?? ''
  const versions = groups.get(selectedDay) || []
  const selected = versions.find(row => row.id === version) || versions[0]
  const seen = new Set<string>()
  const visibleVersions = distinctDaily ? versions.filter(row => {
    const key = row.report ? dailyVersionKey(row.report) : row.id
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }) : versions
  return {
    selected_day: selectedDay,
    selected_version: selected?.id ?? null,
    editions: days.map(date => {
      const latest = groups.get(date)![0]
      return { date, date_from: latest.date_from, title: latest.title }
    }),
    report: selected?.report ?? null,
    versions: visibleVersions.map(({ id, title, date, date_from, published_at }) => ({ id, title, date, date_from, published_at })),
  }
}

