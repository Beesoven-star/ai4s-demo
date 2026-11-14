# Research workbench static demo

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
