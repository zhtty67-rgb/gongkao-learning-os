"""Deterministic and explainable question selection for Adaptive Practice v0."""
from datetime import datetime, timezone

from .attempt_verdict import correct_expr
from .mastery import overall_mastery


POLICY_VERSION = 'gongkao-adaptive-v0.1'
WEIGHTS = {
    'coverage_gap': 0.30,
    'mastery_weakness': 0.25,
    'review_urgency': 0.20,
    'high_confidence_error': 0.10,
    'timeout': 0.05,
    'difficulty_fit': 0.05,
    'exam_importance': 0.05,
    'recent_exposure': -0.20,
}
REASON_LABELS = {
    'coverage_gap': '补足未覆盖模块',
    'mastery_weakness': '巩固薄弱知识点',
    'review_urgency': '复习已到期内容',
    'high_confidence_error': '纠正高信心错误',
    'timeout': '改善超时表现',
    'difficulty_fit': '匹配当前难度',
    'exam_importance': '优先考试重点',
}


def _review_urgency(due, as_of):
    if not due:
        return 0.0
    overdue = (as_of - datetime.fromisoformat(due).astimezone(timezone.utc)).total_seconds()
    if overdue < 0:
        return 0.0
    return min(1.0, 0.5 + overdue / (14 * 86400))


def _recent_exposure(submitted_at, as_of):
    if not submitted_at:
        return 0.0
    age = max(0.0, (as_of - datetime.fromisoformat(submitted_at).astimezone(timezone.utc)).total_seconds())
    return max(0.0, 1.0 - age / (7 * 86400))


def _reason(components, coverage_pool, module_guard):
    reasons = []
    if coverage_pool:
        reasons.append(REASON_LABELS['coverage_gap'])
    ranked = sorted(
        ((key, components[key] * WEIGHTS[key]) for key in REASON_LABELS if components[key] > 0),
        key=lambda item: (-item[1], item[0]),
    )
    for key, _ in ranked:
        label = REASON_LABELS[key]
        if label not in reasons:
            reasons.append(label)
        if len(reasons) == 2:
            break
    if module_guard and len(reasons) < 2:
        reasons.append('保持模块切换')
    return '；'.join(reasons or ['保持均衡训练'])


def select_questions(db, limit=10, as_of=None):
    """Return an ordered selection that can be replayed from the same state and time."""
    as_of = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cols = [c[1] for c in db.execute('PRAGMA table_info(attempts)').fetchall()]
    valid_filter = "AND a.valid_for_stats = 1" if 'valid_for_stats' in cols else ""
    practiced_modules = {
        row[0] for row in db.execute(
            f'''SELECT DISTINCT q.module FROM attempts a JOIN questions q ON q.id=a.question_id
               WHERE a.submitted_at IS NOT NULL {valid_filter}'''
        )
    }
    rows = db.execute(
        f'''WITH latest_attempt AS (
             SELECT a.*,ROW_NUMBER() OVER (
               PARTITION BY a.question_id ORDER BY a.submitted_at DESC,a.id DESC
             ) rn
             FROM attempts a WHERE a.submitted_at IS NOT NULL {valid_filter}
           )
           SELECT q.id,q.module,q.difficulty,q.estimated_seconds,rc.due,
                  {correct_expr(db, 'la')} AS last_correct,la.confidence last_confidence,
                  la.elapsed_ms last_elapsed_ms,la.submitted_at last_submitted_at,
                  COALESCE(AVG(ms.mastery_score),0.5) mastery_score,
                  AVG(kn.exam_priority) exam_priority
           FROM questions q
           JOIN question_knowledge_map qkm ON qkm.question_id=q.id
           JOIN knowledge_nodes kn ON kn.id=qkm.knowledge_node_id
           LEFT JOIN mastery_state ms ON ms.knowledge_node_id=kn.id
           LEFT JOIN latest_attempt la ON la.question_id=q.id AND la.rn=1
           LEFT JOIN review_cards rc ON rc.question_id=q.id
           WHERE q.is_verified = 1
           GROUP BY q.id
           ORDER BY q.id'''
    ).fetchall()
    if not rows:
        return []
    exam_max = max(float(row['exam_priority'] or 0) for row in rows) or 1.0
    target_difficulty = overall_mastery(db)
    candidates = []
    for row in rows:
        timeout = 0.0
        if row['last_elapsed_ms'] is not None:
            timeout = min(1.0, max(0.0, row['last_elapsed_ms'] / (row['estimated_seconds'] * 1000) - 1.0))
        components = {
            'coverage_gap': float(row['module'] not in practiced_modules),
            'mastery_weakness': 1.0 - float(row['mastery_score']),
            'review_urgency': _review_urgency(row['due'], as_of),
            'high_confidence_error': float(row['last_correct'] == 0 and (row['last_confidence'] or 0) >= 0.8),
            'timeout': timeout,
            'difficulty_fit': max(0.0, 1.0 - abs(float(row['difficulty']) - target_difficulty)),
            'exam_importance': float(row['exam_priority'] or 0) / exam_max,
            'recent_exposure': _recent_exposure(row['last_submitted_at'], as_of),
        }
        score = sum(components[key] * weight for key, weight in WEIGHTS.items())
        candidates.append({
            'question_id': row['id'], 'module': row['module'],
            'selection_score': round(score, 6), 'component_scores': components,
        })

    selected = []
    remaining = list(candidates)
    target = min(limit, len(remaining))
    selected_modules = set()
    while remaining and len(selected) < target:
        unseen = {candidate['module'] for candidate in remaining} - selected_modules
        pool = [candidate for candidate in remaining if candidate['module'] in unseen] if unseen else list(remaining)
        coverage_pool = bool(unseen)
        module_guard = False
        if len(selected) >= 2 and selected[-1]['module'] == selected[-2]['module']:
            alternatives = [candidate for candidate in pool if candidate['module'] != selected[-1]['module']]
            if alternatives:
                pool = alternatives
                module_guard = True
        chosen = sorted(pool, key=lambda candidate: (-candidate['selection_score'], candidate['question_id']))[0]
        chosen['position'] = len(selected)
        chosen['component_scores'] = {
            **chosen['component_scores'],
            'coverage_pool': float(coverage_pool),
            'module_guard': float(module_guard),
        }
        chosen['selection_reason'] = _reason(chosen['component_scores'], coverage_pool, module_guard)
        selected.append(chosen)
        selected_modules.add(chosen['module'])
        remaining.remove(chosen)

    # Sort selected items according to standard civil service exam module order
    module_priority = {
        "常识判断": 1,
        "言语理解": 2,
        "数量关系": 3,
        "图形推理": 4,
        "立体图推": 4,
        "定义判断": 5,
        "类比推理": 6,
        "逻辑判断": 7,
        "资料分析": 8,
    }
    selected.sort(key=lambda item: (module_priority.get(item['module'], 99), -item['selection_score']))
    for idx, item in enumerate(selected):
        item['position'] = idx

    return selected
