import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const root = fileURLToPath(new URL('../../', import.meta.url))
const localPython = fileURLToPath(new URL(process.platform === 'win32' ? '../../.venv/Scripts/python.exe' : '../../.venv/bin/python', import.meta.url))
const result = spawnSync(existsSync(localPython) ? localPython : 'python', ['scripts/export_pages.py'], { cwd: root, stdio: 'inherit' })
if (result.error) console.error(result.error.message)
process.exit(result.status ?? 1)
