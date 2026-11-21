"""Describe the material behind a claim, separately from the claim itself."""

import re
import unicodedata


READER_EVIDENCE_RULES = (
    '正文直接回答发生了什么、技术上为什么重要，以及材料支持到哪一步。'
    '新闻把结论归给实际报道或披露方，写清是标准预览、样片、厂商量产计划还是已有部署。'
    '论文将结果归给作者，有比较数字时保留基线、实验条件和单位。'
    '模组尺寸等指标保留原文的维度，线性尺寸变化不能写成面积或体积变化。'
    '按输入区分公开原文摘录、页面简介、作者摘要和题录。题录只支持文献信息，简介和摘要只支持各自涵盖的结论。'
    '只有摘录时，将未提及的范围限定为已读摘录。摘要明确给出的工艺节点、样本数等应随结果保留。'
    '尽量在正文顺手说明依据。需要单独说明时用 boundary 写清具体边界，例如只在仿真中比较、公开材料没有给出量产时间。'
    '不要用“待核验”“待复核”“待人工确认”替代事实说明，也不在正文描述提示词、生成过程或审稿流程。'
)


def stored_reading_basis(item):
    if item['content_type'] == 'paper':
        if (item.get('abstract_text') or '').strip():
            return 'abstract'
        return 'stored_abstract' if (item.get('summary') or '').strip() else 'bibliography'
    if item.get('verification_mode') == 'original_page_review' and item.get('summary_kind') == 'human':
        return 'original_summary'
    if item.get('verification_mode') == 'official_search_listing_manual':
        return 'listing'
    return 'excerpt' if (item.get('summary') or item.get('abstract_text') or '').strip() else 'headline'


DIGITS = re.compile(r'(?<![A-Za-z0-9])\d+(?:[.,]\d+)?')
NUMBER_WORDS = {word: str(number) for number, word in enumerate(
    ('zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'))}
HAN = re.compile(r'[\u3400-\u9fff]')


def _compact(value):
    return ' '.join(unicodedata.normalize('NFKC', value).split())


def reading_points(fields, note_fields, material, basis, *, optional=()):
    source = _compact(material)
    quote = _compact(fields.evidence).strip('“”"')
    if len(quote) < 8 or quote.casefold() not in source.casefold():
        raise ValueError(f'引文与{basis}不匹配')
    numbers = {number.replace(',', '') for number in DIGITS.findall(source)}
    numbers.update(NUMBER_WORDS[word] for word in re.findall(r'\b[a-z]+\b', source.casefold()) if word in NUMBER_WORDS)
    points = []
    for field, label in note_fields:
        text = getattr(fields, field).strip()
        if not text and field in optional:
            continue
        if not HAN.search(text) or re.search(r'待(?:人工)?(?:核验|复核|确认)', text):
            raise ValueError(f'需要依据{basis}写出具体的中文信息')
        if any(number.replace(',', '') not in numbers for number in DIGITS.findall(_compact(text))):
            raise ValueError(f'要点中的数值超出{basis}')
        points.append({'label': label, 'text': text})
    return points
