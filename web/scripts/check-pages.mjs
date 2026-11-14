import { readFileSync } from 'node:fs'
const snapshot = JSON.parse(readFileSync(new URL('../public-pages/data/snapshot.json', import.meta.url), 'utf8'))
if (snapshot.schema_version !== 1 || !Array.isArray(snapshot.items) || !Array.isArray(snapshot.reports)) throw new Error('Run npm run export:pages before building Pages.')
if (snapshot.items.some(item => 'library' in item || 'source_records' in item)) throw new Error('Private fields must not be included in the display snapshot.')
