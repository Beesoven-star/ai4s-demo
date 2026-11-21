from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src.ic_observations import classify_for_observation, daily_observations, load_catalog, save_daily_edition


class ObservationTests(unittest.TestCase):
    @patch('src.ic_observations.today_in_shanghai', return_value='2026-11-21')
    def test_published_report_freezes_classification_and_rejects_overwrite(self, _today):
        item = {'id': 'one', 'title': 'New AI power delivery networks', 'source': 'Example',
                'url': 'https://example.org/article', 'content_type': 'news', 'published_at': '2026-11-20'}
        draft = {'date': '2026-11-20', 'title': 'A daily observation', 'intro': 'Notes',
                 'entries': [{'source_id': item['id'], 'title': 'Delivery', 'summary': 'Short summary'}]}
        catalog = deepcopy(load_catalog())
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            original = save_daily_edition(draft, {item['id']: item}, directory, catalog=catalog)
            prior_topic = original['entries'][0]['classification']['topics'][0]
            self.assertEqual(prior_topic['status'], 'active')
            topic = next(row for row in catalog['topics'] if row['id'] == prior_topic['id'])
            topic.update(name='New topic name', status='paused')
            self.assertEqual(classify_for_observation(item, catalog=catalog)['topics'][0]['status'], 'paused')
            self.assertEqual(daily_observations('2026-11-20', directory)['report'], original)
            self.assertIsNone(daily_observations(directory=directory)['report'])
            with self.assertRaises(FileExistsError):
                save_daily_edition(draft, {item['id']: item}, directory, catalog=catalog)
            self.assertEqual(daily_observations('2026-11-20', directory)['report'], original)

    def test_topics_can_merge_and_material_can_remain_pending(self):
        catalog = deepcopy(load_catalog())
        topic = next(row for row in catalog['topics'] if row['id'] == 'power-thermal')
        topic.update(status='merged', merged_into='chiplet')
        item = {'title': 'Power delivery networks', 'content_type': 'news'}
        self.assertEqual(classify_for_observation(item, catalog=catalog)['topics'][0]['id'], 'chiplet')
        self.assertEqual(classify_for_observation({'title': 'Unspecified update', 'content_type': 'news'})['basis'], 'pending')
