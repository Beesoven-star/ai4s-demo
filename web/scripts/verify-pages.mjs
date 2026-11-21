// Exercise the actual Pages data layer in fresh JS contexts, with file-backed
// Web Storage standing in for the browser. This does not replace visual QA.
import assert from 'node:assert/strict'
import { readFileSync, writeFileSync, existsSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

if (!process.env.PAGES_TEST_STORE) {
  const folder = mkdtempSync(join(tmpdir(), 'ai4s-pages-'))
  const file = fileURLToPath(import.meta.url)
  for (const phase of ['save', 'reopen']) {
    const result = spawnSync(process.execPath, [file], {
      cwd: fileURLToPath(new URL('../', import.meta.url)), stdio: 'inherit',
      env: { ...process.env, PAGES_TEST_STORE: join(folder, 'storage.json'), PAGES_TEST_PHASE: phase },
    })
    assert.equal(result.status, 0, `${phase} phase failed`)
  }
  console.log('Pages data/storage verification passed in two independent processes.')
} else {
  const storePath = process.env.PAGES_TEST_STORE
  let failWrites = false
  globalThis.location = new URL('https://example.github.io/workbench/#/discover')
  globalThis.localStorage = {
    getItem(key) { return JSON.parse(existsSync(storePath) ? readFileSync(storePath, 'utf8') : '{}')[key] ?? null },
    setItem(key, value) {
      if (failWrites) throw new DOMException('Storage full', 'QuotaExceededError')
      const records = JSON.parse(existsSync(storePath) ? readFileSync(storePath, 'utf8') : '{}')
      records[key] = value
      writeFileSync(storePath, JSON.stringify(records))
    },
  }
  const snapshot = JSON.parse(readFileSync(new URL('../public-pages/data/snapshot.json', import.meta.url), 'utf8'))
  assert(snapshot.items.length > 0)
  assert(snapshot.items.every(item => !('library' in item) && !('source_records' in item)))
  assert(snapshot.reports.every(run => !('service_url' in run) && !('error' in run)))
  globalThis.fetch = async url => {
    assert.equal(url, './data/snapshot.json', 'Pages must never call a backend')
    return { ok: true, json: async () => structuredClone(snapshot) }
  }
  // Vite normalizes relative base to '/' in its dev server; match the built
  // Pages bundle's './' explicitly for these module-level checks.
  const config = { mode: 'pages', define: { 'import.meta.env.BASE_URL': JSON.stringify('./') }, server: { middlewareMode: true, hmr: false }, appType: 'custom' }
  const server = await createServer(config)
  try {
    const api = await server.ssrLoadModule('/src/api/discovery.ts')
    const id = snapshot.items.find(item => item.content_type === 'paper' && item.ic_ai.scope === 'main').id
    const note = '静态展示持久化核验：中文备注与 <script>纯文本</script>'
    if (process.env.PAGES_TEST_PHASE === 'save') {
      const briefing = await server.ssrLoadModule('/src/api/briefing.ts')
      for (const days of [7,30]) {
        const edition = await briefing.getICBriefing(days)
        assert.equal(edition.window.days, days)
        assert.equal(edition.window.date_to, snapshot.facets.today, 'The rankings must reflect the export date')
        assert.equal(edition.technologies.length, 6)
        assert(Object.keys(edition.sources).every(id => snapshot.items.some(item => item.id===id)), 'All briefing evidence must resolve to exported details')
        assert(edition.technologies.every(t => t.review_status==='provisional'))
      }
      assert((await briefing.getICBriefing(30)).event_attention_order.length <= 50)
      const editor = await server.ssrLoadModule('/src/api/ic-editor.ts')
      const topicIndex = await editor.getTechnologyTopics()
      const topicEntry = topicIndex.topics.find(topic => topic.evaluation_status)
      assert(topicEntry, 'Exported topics must include the published evaluations')
      const topic = await editor.getTechnologyTopic(topicEntry.id)
      assert(topic.events.length && topic.evaluation?.finding.references.length, 'The topic page must contain its evidence')
      assert((await briefing.getICObservations()).report, 'Daily view defaults to the latest exported report')
      assert((await editor.getPublishedWeekly()).report, 'Weekly archive has a published report')
      const analysis = await server.ssrLoadModule('/src/api/analysis.ts')
      const options = await analysis.analysisRequest('/options')
      const filters = { date_from: snapshot.facets.publication_audit.recent_start, date_to: options.today,
        date_basis: 'published', include_papers: true, include_news: true, literature_scope: 'main',
        news_scope: 'main', research_track: '', topic: '', keyword: '' }
      const preview = await analysis.analysisRequest('/preview', filters)
      assert(preview.total > 0, 'Static analysis must return selectable materials')
      assert.equal(preview.counts.paper + preview.counts.news, preview.total)
      assert(preview.sources.every(source => source.published_at >= filters.date_from && source.published_at <= filters.date_to))
      const archiveRuns = await analysis.analysisRequest('/runs')
      assert.equal(archiveRuns.length, snapshot.reports.length)
      if (archiveRuns.length) assert.equal((await analysis.analysisRequest('/runs/' + archiveRuns[0].id)).report.title, snapshot.reports[0].report.title)
      await assert.rejects(analysis.analysisRequest('/preview', { ...filters, include_papers: false, include_news: false }), /至少选择/)
      await assert.rejects(analysis.analysisRequest('/preview', { ...filters, date_from: '2026-02-30' }), /日期范围/)
      await assert.rejects(analysis.analysisRequest('/preview', { ...filters, research_track: 'ic_for_ai', topic: 'A1' }), /不一致/)
      await assert.rejects(analysis.analysisRequest('/runs', { filters, item_ids: [] }), /生成新报告请使用本地完整版/)
      // Optional local baseline, produced using the existing Python selector.
      const baselinePath = new URL('../../.runtime/pages-analysis-baseline.json', import.meta.url)
      if (existsSync(baselinePath)) {
        const baseline = JSON.parse(readFileSync(baselinePath, 'utf8'))
        if (baseline.exported_at === snapshot.exported_at) {
          for (const entry of baseline.cases) {
            const actual = await analysis.analysisRequest('/preview', entry.filters)
            assert.deepEqual(actual.sources.map(source => source.id), entry.ids, entry.name)
            assert.deepEqual(actual.counts, entry.counts, entry.name)
            assert.deepEqual(actual.excluded, entry.excluded, entry.name)
            assert.deepEqual(actual.sources.map(source => [source.evidence_quality, source.excerpt, source.tracks, source.topics]), entry.evidence, entry.name)
          }
          console.log(`Analysis filtering matches the Python backend for ${baseline.cases.length} cases, including news classification and missing dates.`)
        }
      }
      assert.equal((await api.listPersonalLibrary({})).total, 0, 'Visitors must not inherit the owner library')
      const main = await api.listDiscoveryItems({ content_type: 'paper' })
      assert.equal(main.total, snapshot.facets.main_papers)
      const archive = await api.listDiscoveryItems({ content_type: 'paper', literature_scope: 'archive' })
      assert.equal(archive.total, snapshot.facets.archive_papers)
      const news = await api.listDiscoveryItems({ content_type: 'news' })
      assert.equal(news.total, snapshot.facets.news)
      const unknown = await api.listDiscoveryItems({ content_type: 'paper', literature_scope: 'all', publication_period: 'month_only' })
      assert.equal(unknown.total, snapshot.facets.publication_audit.counts.month_only || 0)
      const dates = await api.listDiscoveryItems({ content_type: 'paper', literature_scope: 'all', date_from: '2026-10-01', date_to: '2026-11-14', limit: 100 })
      assert(dates.items.every(item => item.published_at && item.published_at.slice(0,10) >= '2026-10-01' && item.published_at.slice(0,10) <= '2026-11-14'))
      await api.updatePersonalRecord(id, { is_favorite: true, notes: note, reading_status: 'reading', personal_tags: ['精读'] })
      assert.equal((await api.listPersonalLibrary({ q: '中文备注' })).total, 1)
      failWrites = true
      await assert.rejects(api.updatePersonalRecord(id, { notes: '不应保存成功' }), /浏览器未能保存/)
      failWrites = false
      assert.equal((await api.getDiscoveryItem(id)).library.notes, note)
      const controller = new AbortController(); controller.abort()
      await assert.rejects(api.getDiscoveryItem(id, controller.signal), { name: 'AbortError' })
    } else {
      const restored = (await api.getDiscoveryItem(id)).library
      assert.equal(restored.is_favorite, true)
      assert.equal(restored.notes, note)
      assert.equal(restored.reading_status, 'reading')
      assert.deepEqual(restored.personal_tags, ['精读'])
      await api.updatePersonalRecord(id, { is_favorite: false })
      assert.equal((await api.listPersonalLibrary({})).total, 0)
      assert.equal((await api.getDiscoveryItem(id)).library.notes, note)
      await api.updatePersonalRecord(id, { is_favorite: true })
      assert.equal((await api.getDiscoveryItem(id)).library.saved_at, restored.saved_at)
      // A different repository on the same github.io origin gets its own library.
      await server.close()
      globalThis.location = new URL('https://example.github.io/another-project/#/library')
      const isolated = await createServer(config)
      try {
        const other = await isolated.ssrLoadModule('/src/api/discovery.ts')
        assert.equal((await other.getDiscoveryItem(id)).library.is_favorite, false)
      } finally { await isolated.close() }
      console.log('Verified reopen persistence, notes, status, tags, cancellation, failed writes, filters and site isolation.')
    }
  } finally { await server.close() }
}
