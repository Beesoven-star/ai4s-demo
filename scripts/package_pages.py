"""Package the built website, including .nojekyll, without source or local DBs."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import json

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / 'web/dist-pages'
if not (source / 'index.html').is_file() or not (source / 'data/snapshot.json').is_file():
    raise SystemExit('Build the Pages website first.')
output = ROOT / 'dist/github-pages-site.zip'
output.parent.mkdir(parents=True, exist_ok=True)
with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
    for path in sorted(source.rglob('*')):
        if path.is_file():
            archive.write(path, path.relative_to(source).as_posix())
print(output)

# A separate, minimal source repository is ready for GitHub Actions. Include
# only the frontend, published snapshot and workflow, never backend documents.
source_output = ROOT / 'dist/github-pages-source.zip'
with ZipFile(source_output, 'w', ZIP_DEFLATED) as archive:
    files = [ROOT / '.github/workflows/pages.yml']
    files.extend(ROOT / 'web' / name for name in (
        'index.html', 'package-lock.json', 'vite.config.ts', 'tsconfig.json',
        'tailwind.config.js', 'postcss.config.js',
        'scripts/check-pages.mjs', 'scripts/verify-pages.mjs',
    ))
    for folder in ('web/src', 'web/public-pages'):
        files.extend(path for path in (ROOT / folder).rglob('*') if path.is_file())
    for path in sorted(files):
        archive.write(path, path.relative_to(ROOT).as_posix())
    package = json.loads((ROOT / 'web/package.json').read_text(encoding='utf-8'))
    package['scripts'] = {
        'dev': 'vite --mode pages',
        'build': 'node scripts/check-pages.mjs && vite build --mode pages',
        'build:pages': 'node scripts/check-pages.mjs && vite build --mode pages',
        'verify:pages': 'node scripts/verify-pages.mjs',
        'preview': 'vite preview --mode pages',
    }
    archive.writestr('web/package.json', json.dumps(package, ensure_ascii=False, indent=2) + '\n')
    archive.writestr('.gitignore', 'node_modules/\ndist-pages/\n.env\n.env.local\n')
    archive.writestr('README.md', '''# Research workbench static demo

This repository contains the public frontend and an exported data snapshot.
Personal favorites and notes are saved in each visitor's browser.

## Publish
Push this directory to the main branch of an empty GitHub repository.
Open Settings > Pages > Source and select GitHub Actions.
The included workflow builds and publishes the site automatically.

## Local preview
In web/: npm ci, npm run build:pages, npm run preview.

## Update data
Run the preparation script in the original local workbench, then replace
this repository's files with the new source archive and commit/push again.
''')
print(source_output)

update_output = ROOT / 'dist/github-pages-analysis-update.zip'
with ZipFile(update_output, 'w', ZIP_DEFLATED) as archive:
    for name in (
        'web/src/api/analysis.ts', 'web/src/api/static-analysis.ts',
        'web/src/discovery-types.ts', 'web/src/router/index.ts',
        'web/src/views/ResearchAnalysisView.vue', 'web/public-pages/data/snapshot.json',
    ):
        archive.write(ROOT / name, name)
print(update_output)
