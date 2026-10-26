"""原书/原卷题号索引；重复来源复用正式题目与学习历史。"""
import json
import re

from fastapi import HTTPException


def number_parts(reference_id):
    match = re.search(r'-(?:s|r)(\d+)-q(\d+)$', reference_id)
    if match:
        return int(match[1]), int(match[2])
    match = re.search(r'-q(\d+)$', reference_id)
    return None, int(match[1]) if match else None


def references(db):
    result = []
    for row in db.execute("SELECT id,source,year,module,stem,source_locator FROM questions WHERE source<>'TEST_EXAM'"):
        item = dict(row)
        set_number, question_number = number_parts(item['id'])
        locator = item['source_locator'] or item['id']
        if set_number is not None:
            locator = f'第{set_number}套 · 第{question_number}题'
        result.append(dict(reference_id=item['id'], question_id=item['id'], source=item['source'],
                           year=item['year'], module=item['module'], stem=item['stem'],
                           source_locator=locator, set_number=set_number, question_number=question_number,
                           shared=False, option_map={k: k for k in 'ABCD'}))
    for row in db.execute('''SELECT a.*,q.module,q.stem FROM question_source_aliases a
                            JOIN questions q ON q.id=a.question_id'''):
        item = dict(row)
        result.append(dict(reference_id=item['alias_id'], question_id=item['question_id'], source=item['source'],
                           year=item['year'], module=item['module'], stem=item['stem'],
                           source_locator=item['source_locator'], set_number=item['set_number'],
                           question_number=item['question_number'], shared=True,
                           option_map=json.loads(item['option_map_json'])))
    return sorted(result, key=lambda a: (a['source'], a['set_number'] or 0, a['question_number'] or 0, a['reference_id']))


def source_catalog(db):
    groups = {}
    for item in references(db):
        group = groups.setdefault(item['source'], dict(source=item['source'], reference_count=0, question_ids=set(), sets=set()))
        group['reference_count'] += 1
        group['question_ids'].add(item['question_id'])
        if item['set_number'] is not None:
            group['sets'].add(item['set_number'])
    return {'sources': [dict(source=g['source'], reference_count=g['reference_count'],
                             unique_question_count=len(g['question_ids']), sets=sorted(g['sets']))
                        for g in groups.values()]}


def find_references(db, source=None, set_number=None, question_number=None, search=''):
    query = search.strip().casefold()
    return [a for a in references(db)
            if (source is None or a['source'] == source)
            and (set_number is None or a['set_number'] == set_number)
            and (question_number is None or a['question_number'] == question_number)
            and (not query or query in (' '.join((a['reference_id'], a['source'], a['source_locator'], a['stem']))).casefold())]


def resolve_reference(db, reference_id):
    item = next((a for a in references(db) if a['reference_id'] == reference_id), None)
    if item is None:
        raise HTTPException(404, '未找到该原题号，请检查来源和编号')
    return item


def source_context(db, session_id, question_id):
    row = db.execute('SELECT reference_id,source,source_locator FROM session_question_sources WHERE session_id=? AND question_id=?',
                     (session_id, question_id)).fetchone()
    return dict(row) if row else None
