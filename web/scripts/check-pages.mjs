import { readFileSync } from 'node:fs'
const snapshot = JSON.parse(readFileSync(new URL('../public-pages/data/snapshot.json', import.meta.url), 'utf8'))
if (snapshot.schema_version !== 1 || !Array.isArray(snapshot.items) || !Array.isArray(snapshot.reports)) throw new Error('Run npm run export:pages before building Pages.')
if (snapshot.items.some(item => 'library' in item || 'source_records' in item)) throw new Error('Private fields must not be included in the display snapshot.')
if (!snapshot.ic_topics?.topics.length || !Object.keys(snapshot.ic_topics.details).length) throw new Error('Export the topic pages before building Pages.')
for (const days of ['7', '30']) {
  if (!snapshot.ic_briefing?.[days] || !snapshot.ic_rankings?.[days]) throw new Error('Export the two ranking windows before building Pages.')
  if (snapshot.ic_rankings[days].window.date_to !== snapshot.facets.today) throw new Error(`Stale ${days}-day ranking in export.`)
}
if (snapshot.ic_rankings['30'].event_attention_order.length > 50) throw new Error('The 30-day hotspot ranking is limited to 50 entries.')
