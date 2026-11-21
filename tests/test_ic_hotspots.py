from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src import discovery
from src.ic_hotspots import rolling_briefing


def article(host, slug, day, title, *, summary='', genre='署名报道'):
    return {'content_type': 'news', 'source': host, 'url': f'https://{host}/{slug}',
            'published_at': day, 'title': title, 'summary': summary, 'news_genre': genre}


def ranked(edition):
    events = {event['id']: event for event in edition['events']}
    return [events[identity] for identity in edition['event_attention_order']]


class HotspotTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db = Path(temporary.name) / 'discovery.sqlite'

    def collect(self, *records):
        return discovery.upsert_items(records, origin='collected', db_path=self.db)

    def test_persisted_news_rolls_both_windows_by_publication_date(self):
        self.collect(
            article('press.test', 'recent', '2027-01-14', 'Reliability results for fan-out packaging'),
            article('press.test', 'prior', '2026-12-22', 'Industry deploys a new reticle inspection tool'),
            article('press.test', 'future', '2027-01-21', 'Commercial chip announced for robotics'),
        )
        cutoff = date(2027, 1, 20)
        seven = rolling_briefing(7, self.db, as_of=cutoff)
        thirty = rolling_briefing(30, self.db, as_of=cutoff)
        self.assertEqual(seven['window'], {'days': 7, 'date_from': '2027-01-14', 'date_to': '2027-01-20'})
        self.assertEqual(thirty['window'], {'days': 30, 'date_from': '2026-12-22', 'date_to': '2027-01-20'})
        self.assertEqual(len(ranked(seven)), 1)
        self.assertEqual(len(ranked(thirty)), 2)

        self.collect(article('press.test', 'added', '2027-01-20', 'New method doubles wafer throughput'))
        cutoff = date(2027, 1, 21)
        seven = rolling_briefing(7, self.db, as_of=cutoff)
        thirty = rolling_briefing(30, self.db, as_of=cutoff)
        self.assertEqual(seven['window']['date_from'], '2027-01-15')
        self.assertEqual(thirty['window']['date_from'], '2026-12-23')
        self.assertEqual(seven['window']['date_to'], '2027-01-21')
        titles = ['Commercial chip announced for robotics', 'New method doubles wafer throughput']
        self.assertEqual([event['title'] for event in ranked(seven)], titles)
        self.assertEqual([event['title'] for event in ranked(thirty)], [*titles, 'Reliability results for fan-out packaging'])

    def test_collaboration_titles_share_event_and_reports_do_not_inflate_counts(self):
        long_excerpt = ('The reporters interviewed both engineering teams about moving compute closer to memory. '
                        'Independent tests examine the effect on cache latency and power under sustained loads.')
        primary = 'Aster and Boreal Collaborate to Design an Optical Memory Interface'
        related = 'Aster, Boreal Partner to Integrate Optical Memory Technologies'
        self.collect(
            article('first.test', 'report', '2027-01-15', primary, summary=long_excerpt),
            article('second.test', 'coverage', '2027-01-16', related,
                    summary='A separate interview describes a photonic memory interface for very large clusters.'),
            article('www.second.test', 'analysis', '2027-01-17', related,
                    summary='The author uses a new diagram to discuss upgrade options for installed systems.'),
            article('reprint.test', 'exact-copy', '2027-01-18', related, summary=long_excerpt),
            article('translated.test', 'reprint', '2027-01-19', related, summary='本文系转载，报道来自外部媒体。'),
            article('third.test', 'release', '2027-01-15', primary, genre='联合公告'),
            article('third.test', 'unrelated', '2027-01-17', 'Carmine, Helios Partner to Integrate Optical Memory'),
        )
        for days in (7, 30):
            with self.subTest(days=days):
                edition = rolling_briefing(days, self.db, as_of=date(2027, 1, 20))
                result = ranked(edition)
                self.assertEqual([event['attention_rank'] for event in result], [1, 2])
                self.assertEqual(result[0]['attention']['source_count'], 2)
                self.assertEqual(result[0]['attention']['latest_reported_at'], '2027-01-17')
                counted = [edition['sources'][key]['source'] for key in result[0]['attention']['source_ids']]
                self.assertCountEqual(counted, ['first.test', 'second.test', 'www.second.test'])
                self.assertEqual(len(result[0]['source_ids']), 6)

    def test_stored_reprint_or_unconfirmed_list_entry_cannot_start_ranked_event(self):
        self.collect(
            article('one.test', 'reprint', '2027-01-20', 'Follow-up to a package development', genre='同稿分发'),
            article('two.test', 'listing', '2027-01-20', 'Not enough information in this source',
                    summary='A plain headline and uncertain listing about optical interconnect products.',
                    genre='专业媒体报道（待核验）'),
        )
        self.assertFalse(ranked(rolling_briefing(7, self.db, as_of=date(2027, 1, 20))))

    def test_monthly_view_only_ranks_the_first_fifty_events(self):
        self.collect(*(article('press.test', str(i), '2027-01-20', f'Technical development for IC project {i}')
                       for i in range(55)))
        cutoff = date(2027, 1, 20)
        weekly = rolling_briefing(7, self.db, as_of=cutoff)
        monthly = rolling_briefing(30, self.db, as_of=cutoff)
        self.assertEqual(len(weekly['event_attention_order']), 55)
        self.assertEqual(monthly['event_attention_order'], weekly['event_attention_order'][:50])
        self.assertEqual([event['attention_rank'] for event in ranked(monthly)], list(range(1, 51)))


if __name__ == '__main__':
    unittest.main()
