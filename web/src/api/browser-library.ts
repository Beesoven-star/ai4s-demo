import type { PersonalRecord, ReadingStatus } from '../discovery-types'

// github.io projects share an origin. Use the site path and a stable version
// so records survive deployments without mixing different workbenches.
const prefix = `ai4s:${new URL(import.meta.env.BASE_URL, location.href).pathname}:library:v1:`
const statuses: ReadingStatus[] = ['unread', 'reading', 'read', 'follow_up']

export function emptyRecord(): PersonalRecord {
  return { is_favorite: false, notes: '', reading_status: 'unread', personal_tags: [], saved_at: null, updated_at: null }
}

export function readRecord(id: string): PersonalRecord {
  let raw: string | null
  try { raw = localStorage.getItem(prefix + id) }
  catch { return emptyRecord() }
  if (!raw) return emptyRecord()
  try {
    const record = JSON.parse(raw) as PersonalRecord
    if (typeof record.is_favorite !== 'boolean' || typeof record.notes !== 'string'
      || !statuses.includes(record.reading_status) || !Array.isArray(record.personal_tags)
      || !record.personal_tags.every(tag => typeof tag === 'string')
      || !(record.saved_at === null || typeof record.saved_at === 'string')
      || !(record.updated_at === null || typeof record.updated_at === 'string')) throw new Error()
    return record
  } catch { throw new Error('这条资料的浏览器保存记录无法读取，请保留网站数据并联系维护者。') }
}

export function writeRecord(id: string, changes: Partial<PersonalRecord>): PersonalRecord {
  const previous = readRecord(id)
  const next = { ...previous, ...changes }
  if (typeof next.is_favorite !== 'boolean' || typeof next.notes !== 'string' || next.notes.length > 20000
    || !statuses.includes(next.reading_status) || !Array.isArray(next.personal_tags)
    || next.personal_tags.length > 20 || !next.personal_tags.every(tag => typeof tag === 'string' && tag.length <= 50)) {
    throw new Error('备注、阅读状态或标签无效；备注最多20000字，标签最多20个，每个最多50字。')
  }
  next.personal_tags = [...new Set(next.personal_tags.map(tag => tag.trim()).filter(Boolean))]
  next.saved_at = previous.saved_at || (next.is_favorite ? new Date().toISOString() : null)
  next.updated_at = new Date().toISOString()
  try { localStorage.setItem(prefix + id, JSON.stringify(next)) }
  catch { throw new Error('浏览器未能保存记录，请允许网站存储或释放浏览器存储空间后重试。') }
  return next
}
