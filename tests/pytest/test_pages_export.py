"""Public export must neither publish personal records nor alter the source DB."""
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
import unittest

from scripts.export_pages import export_snapshot


def check_export(tmp_path):
    database = tmp_path / 'private.sqlite'
    marker = 'PRIVATE_RECORD_MUST_NOT_BE_PUBLISHED'
    item = {
        'id': 'pages-fixture', 'content_type': 'paper', 'origin': 'collected',
        'title': 'AI accelerator hardware design', 'source': 'Public journal',
        'url': 'https://example.org/paper', 'published_at': '2026-11-01',
        'collected_at': '2026-11-02T00:00:00+08:00', 'topics': [], 'methods': [], 'views': [],
        'library': {'notes': marker}, 'source_records': [{'api_key': marker}], 'api_key': marker,
    }
    run = {
        'id': 'completed', 'status': 'success', 'created_at': '2026-11-03',
        'report': {'title': 'Public analysis'}, 'service_url': marker, 'error': marker,
        'sources': [{'id': item['id'], 'title': item['title'], 'excerpt': 'Public abstract', 'private_note': marker}],
    }
    with sqlite3.connect(database) as connection:
        connection.executescript('''
            CREATE TABLE discovery_items(payload TEXT,created_at TEXT,published_date TEXT,id TEXT);
            CREATE TABLE personal_library(notes TEXT);
            CREATE TABLE research_analysis_runs(id TEXT,created_at TEXT,payload TEXT);
        ''')
        connection.execute('INSERT INTO discovery_items VALUES (?,?,?,?)', (json.dumps(item), '2026-11-02', '2026-11-01', item['id']))
        connection.execute('INSERT INTO personal_library VALUES (?)', (marker,))
        connection.execute('INSERT INTO research_analysis_runs VALUES (?,?,?)', ('completed', '2026-11-03', json.dumps(run)))
        connection.execute('INSERT INTO research_analysis_runs VALUES (?,?,?)', ('failed', '2026-11-03', json.dumps({**run, 'status': 'failed'})))
    connection.close()
    before = hashlib.sha256(database.read_bytes()).digest()
    output = tmp_path / 'snapshot.json'
    result = export_snapshot(database, output)
    assert hashlib.sha256(database.read_bytes()).digest() == before
    assert marker not in output.read_text(encoding='utf-8')
    assert len(result['items']) == 1
    assert len(result['reports']) == 1
    assert result['reports'][0]['sources'][0]['excerpt'] == 'Public abstract'
    assert result['facets']['total'] == 1


class PagesExportTest(unittest.TestCase):
    def test_readonly_and_private_fields(self):
        test_root = Path(__file__).resolve().parents[2] / '.runtime/pages-export-tests'
        test_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='export-', dir=test_root) as directory:
            check_export(Path(directory))


if __name__ == '__main__':
    unittest.main()
