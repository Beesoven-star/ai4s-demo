from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src import ic_topics
from src.ic_observations import classify_for_observation


class TechnologyTopicsTests(unittest.TestCase):
    excerpt = 'The engineers published results from temperature cycling tests.'

    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '.runtime' / 'test-tmp'
        root.mkdir(parents=True, exist_ok=True)
        temp = TemporaryDirectory(dir=root)
        self.addCleanup(temp.cleanup)
        self.database = Path(temp.name) / 'topics.sqlite'
        ic_topics.initialize(self.database)

    def source(self, identity, day, title, genre='独立报道'):
        return {'id': identity, 'title': title, 'source': 'Example',
                'url': f'https://example.org/{identity}', 'content_type': 'news',
                'published_at': day, 'news_genre': genre, 'excerpt': self.excerpt}

    def proposal(self, *events, topic_id='', name='低温封装互连', evidence=None):
        return ic_topics.Proposal.model_validate({
            'topic_id': topic_id, 'name': name, 'aliases': [],
            'category_id': 'packaging', 'overview': '使用低温材料连接裸片。',
            'question': '连接可靠性如何验证？', 'follow_up': '观察温循和湿热测试。',
            'scope_reason': '跟踪超导量子电路专用封装的低温导热和连接可靠性，与面向 AI 的芯粒封装问题不同。',
            'events': [{'title': title, 'summary': '摘要依据公开资料。', 'source_ids': ids,
                        'evidence_source_id': ids[0], 'evidence': self.excerpt if evidence is None else evidence}
                       for title, ids in events],
        })

    def test_distinct_topic_opens_immediately_cools_and_resumes(self):
        first = self.source('s1', '2026-10-02', 'Lab A announces a low-temperature process')
        found = ic_topics.apply_refresh(self.database, [self.proposal(('材料工艺验证', ['s1']))], {'s1': first}, date(2026, 10, 2))
        self.assertEqual(found[0]['status'], 'active')
        catalog = ic_topics.discovery_catalog(self.database)
        item = {'id': 's1', 'content_type': 'news', 'title': 'Laboratory progress'}
        self.assertEqual([row['id'] for row in classify_for_observation(item, catalog=catalog)['topics']],
                         [found[0]['id']])
        self.assertEqual(ic_topics.apply_refresh(
            self.database, [self.proposal(('重复记录', ['s1']), name='同一进展的不同专题名')],
            {'s1': first}, date(2026, 10, 2)), [])
        key = found[0]['id']
        repeat = self.source('s2', '2026-10-05', first['title'])
        changes = ic_topics.apply_refresh(self.database, [self.proposal(('材料工艺验证', ['s2']), topic_id=key)],
                                          {'s2': repeat}, date(2026, 10, 5))
        self.assertEqual(changes[0]['event_count'], 1)
        self.assertEqual(changes[0]['latest_progress'], '2026-10-02')
        second = self.source('s3', '2026-10-08', 'University B completes cycling tests', '论文')
        changes = ic_topics.apply_refresh(self.database, [self.proposal(('完成温循实验', ['s3']), topic_id=key)],
                                          {'s3': second}, date(2026, 10, 8))
        self.assertEqual(changes[0]['status'], 'active')
        self.assertEqual(ic_topics.apply_refresh(self.database, [self.proposal(('材料工艺验证', ['s1', 's3']), topic_id=key)],
                                                {'s1': first, 's3': second}, date(2026, 10, 8)), [])
        row = next(row for row in ic_topics.get_topics(self.database, date(2026, 11, 8)) if row['id'] == key)
        self.assertEqual(row['status'], 'history')
        later = self.source('s4', '2026-11-09', 'Packaging supplier reports customer validation')
        changes = ic_topics.apply_refresh(self.database, [self.proposal(('供应商发布客户验证', ['s4']), topic_id=key)],
                                          {'s4': later}, date(2026, 11, 9))
        self.assertEqual((changes[0]['id'], changes[0]['previous_status'], changes[0]['status']), (key, 'history', 'active'))
        self.assertEqual(changes[0]['event_count'], 3)
        index_row = next(row for row in ic_topics.topic_index(self.database) if row['id'] == key)
        self.assertEqual(index_row['latest_event']['title'], '供应商发布客户验证')
        self.assertEqual(index_row['latest_event']['sources'], ['Example'])

    def test_unknown_and_reprinted_sources_cannot_open_a_topic(self):
        reprint = self.source('s1', '2026-10-05', 'Retelling a launch', '二手编译')
        changes = ic_topics.apply_refresh(self.database, [self.proposal(
            ('转载', ['s1']), ('无出处', ['fabricated']))], {'s1': reprint}, date(2026, 10, 6))
        self.assertEqual(changes, [])



    def test_existing_parent_accepts_subtopic_progress_and_new_topic_requires_evidence(self):
        new = self.source('new', '2026-11-21', 'A lab verified a new circuit')
        material = {'new': new}
        ungrounded = self.proposal(('新工艺', ['new']), evidence='No such sentence in the source.')
        self.assertEqual(ic_topics.apply_refresh(self.database, [ungrounded], material, date(2026, 11, 21)), [])
        child = self.proposal(('配电设备测试', ['new']), topic_id='power-thermal', name='机柜高压配电')
        changes = ic_topics.apply_refresh(self.database, [child], material, date(2026, 11, 21))
        self.assertEqual([row['id'] for row in changes], ['power-thermal'])
        parent = ic_topics.topic_detail('power-thermal', self.database)
        self.assertEqual(parent['name'], 'AI芯片供电与散热')
        self.assertIn('各级转换损耗和温升', parent['question'])
        self.assertIn('new', {source['id'] for event in parent['events'] for source in event['sources']})
