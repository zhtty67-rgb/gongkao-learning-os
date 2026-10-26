import json
from .db import connect, migrate
from .schemas import QuestionBank


def import_bank(path, payload):
    bank = QuestionBank.model_validate(payload)
    for values in (bank.questions, bank.knowledge_nodes):
        if len({x.id for x in values}) != len(values):
            raise ValueError('文件内 ID 重复')
    migrate(path)
    counts = {'inserted': 0, 'skipped': 0}
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('PRAGMA defer_foreign_keys=ON')
        for node in bank.knowledge_nodes:
            values = node.model_dump()
            old = db.execute('SELECT * FROM knowledge_nodes WHERE id=?', (node.id,)).fetchone()
            if old:
                old_dict = {k: old[k] for k in values}
                if old_dict != values:
                    raise ValueError(f'知识点 {node.id} 已存在且不同；拒绝覆盖')
            else:
                cols = ','.join(values.keys())
                placeholders = ','.join('?' for _ in values)
                db.execute(f'INSERT INTO knowledge_nodes ({cols}) VALUES ({placeholders})', tuple(values.values()))
        # Parent cycles are invalid even though foreign keys alone allow them.
        parents = dict(db.execute('SELECT id,parent_id FROM knowledge_nodes').fetchall())
        for node_id in parents:
            seen = set()
            current = node_id
            while current is not None:
                if current in seen:
                    raise ValueError('知识点父级存在循环')
                seen.add(current)
                if current not in parents:
                    raise ValueError('知识点父级不存在')
                current = parents[current]
        for question in bank.questions:
            values = question.model_dump(exclude={'knowledge', 'options'})
            values['options_json'] = json.dumps(question.options, ensure_ascii=False, sort_keys=True)
            old = db.execute('SELECT * FROM questions WHERE id=?', (question.id,)).fetchone()
            maps = sorted((x.knowledge_node_id, x.weight) for x in question.knowledge)
            if old:
                old_maps = [tuple(r) for r in db.execute('SELECT knowledge_node_id,weight FROM question_knowledge_map WHERE question_id=? ORDER BY knowledge_node_id', (question.id,))]
                old_dict = {k: old[k] for k in values}
                if old_dict != values or old_maps != maps:
                    raise ValueError(f'题目 {question.id} 已存在且不同；拒绝覆盖')
                counts['skipped'] += 1
                continue
            columns = ','.join(values)
            placeholders = ','.join('?' for _ in values)
            db.execute(f'INSERT INTO questions ({columns}) VALUES ({placeholders})', tuple(values.values()))
            for node_id, weight in maps:
                if node_id not in parents:
                    raise ValueError(f'未知知识点：{node_id}')
                db.execute('INSERT INTO question_knowledge_map VALUES (?,?,?)', (question.id, node_id, weight))
            counts['inserted'] += 1
    return counts
