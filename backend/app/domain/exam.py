"""Exam Mode engine: 403 hard lock during active exams, paper submission, and scoring."""
from datetime import datetime, timezone
import json
from uuid import uuid4
from fastapi import HTTPException

from .mastery import rebuild_mastery
from .review import rebuild_reviews


def require_ai_allowed(db, session_id: str | None = None, attempt_id: str | None = None):
    """Unified Exam AI Access Policy.
    
    If the attempt or session belongs to an active EXAM session,
    blocks AI/Tutor/Assessor assistance with HTTP 403 EXAM_MODE_LOCKED.
    All current and future AI endpoints MUST pass through this guard.
    """
    target_sid = session_id
    if target_sid is None and attempt_id is not None:
        row = db.execute('SELECT session_id FROM attempts WHERE id=?', (attempt_id,)).fetchone()
        if row:
            target_sid = row['session_id']

    if target_sid is not None:
        sess = db.execute('SELECT mode, status FROM sessions WHERE id=?', (target_sid,)).fetchone()
        if sess and sess['mode'] == 'EXAM' and sess['status'] == 'active':
            raise HTTPException(403, 'EXAM_MODE_LOCKED: 考试进行中，严禁获取提示、错因诊断或知识库检索')


check_exam_lock = require_ai_allowed

STANDARD_MODULE_SPEC = [
    {"module": "政治理论", "ratio": 0.075, "min_count": 1},
    {"module": "常识判断", "ratio": 0.075, "min_count": 1},
    {"module": "言语理解", "ratio": 0.26, "min_count": 2},
    {"module": "数量关系", "ratio": 0.11, "min_count": 1},
    {"module": "图形推理", "ratio": 0.10, "min_count": 1},
    {"module": "定义判断", "ratio": 0.05, "min_count": 0},
    {"module": "类比推理", "ratio": 0.08, "min_count": 1},
    {"module": "逻辑判断", "ratio": 0.10, "min_count": 1},
    {"module": "资料分析", "ratio": 0.15, "min_count": 1},
]


def _module_family(mod: str) -> list[str]:
    """Exam composition works on module families: 图形推理 includes 立体图推."""
    return MODULE_ALIAS_MAP.get(mod, [mod])


def compose_real_exam_questions(db, total_count: int = 50) -> list[str]:
    """Select questions strictly according to real exam module order and proportions."""
    all_count = db.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    if all_count == 0:
        raise HTTPException(409, "题库为空，无法组卷")

    total_count = max(1, min(all_count, total_count))

    # Calculate target quotas per module
    quotas = {}
    current_sum = 0
    for spec in STANDARD_MODULE_SPEC:
        mod = spec["module"]
        c = max(spec["min_count"], round(total_count * spec["ratio"]))
        quotas[mod] = c
        current_sum += c

    diff = total_count - current_sum
    quotas["言语理解"] = max(1, quotas["言语理解"] + diff)

    final_ordered_qids: list[str] = []
    overflow_deficit = 0

    for spec in STANDARD_MODULE_SPEC:
        mod = spec["module"]
        family = _module_family(mod)
        fam_placeholders = ",".join(["?"] * len(family))
        target_count = quotas[mod] + (overflow_deficit if mod == "逻辑判断" else 0)
        overflow_deficit = 0

        if target_count <= 0:
            continue

        # Priority 1: Unpracticed questions
        unpracticed = db.execute(
            f"""
            SELECT q.id FROM questions q
            WHERE q.module IN ({fam_placeholders})
              AND q.is_verified = 1
              AND q.id NOT IN (SELECT DISTINCT question_id FROM attempts WHERE submitted_at IS NOT NULL)
            ORDER BY q.id
            LIMIT ?
            """,
            (*family, target_count)
        ).fetchall()
        mod_qids = [r["id"] for r in unpracticed]

        # Priority 2: Least recently practiced questions
        if len(mod_qids) < target_count:
            needed = target_count - len(mod_qids)
            placeholders = ",".join(["?"] * len(mod_qids)) if mod_qids else "''"
            params = (*family, *mod_qids, needed) if mod_qids else (*family, needed)
            more = db.execute(
                f"""
                SELECT q.id FROM questions q
                LEFT JOIN (
                    SELECT question_id, MAX(submitted_at) as last_sub
                    FROM attempts
                    WHERE submitted_at IS NOT NULL
                    GROUP BY question_id
                ) a ON a.question_id = q.id
                WHERE q.module IN ({fam_placeholders}) AND q.is_verified = 1 AND q.id NOT IN ({placeholders})
                ORDER BY a.last_sub ASC, q.id ASC
                LIMIT ?
                """,
                params
            ).fetchall()
            mod_qids.extend([r["id"] for r in more])

        if len(mod_qids) < target_count:
            overflow_deficit += (target_count - len(mod_qids))

        final_ordered_qids.extend(mod_qids)

    # In case of any remaining deficit, fill from any available questions
    if len(final_ordered_qids) < total_count:
        needed = total_count - len(final_ordered_qids)
        placeholders = ",".join(["?"] * len(final_ordered_qids)) if final_ordered_qids else "''"
        more = db.execute(
            f"""
            SELECT id FROM questions
            WHERE is_verified = 1 AND id NOT IN ({placeholders})
            ORDER BY id
            LIMIT ?
            """,
            (*final_ordered_qids, needed) if final_ordered_qids else (needed,)
        ).fetchall()
        final_ordered_qids.extend([r["id"] for r in more])

    return final_ordered_qids


MODULE_ALIAS_MAP: dict[str, list[str]] = {
    "政治理论": ["政治理论"],
    "政治": ["政治理论"],
    "常识判断": ["常识判断"],
    "常识": ["常识判断"],
    "言语理解": ["言语理解"],
    "言语": ["言语理解"],
    "言语理解与表达": ["言语理解"],
    "数量关系": ["数量关系"],
    "数量": ["数量关系"],
    "判断推理": ["判断推理", "图形推理", "立体图推", "定义判断", "类比推理", "逻辑判断"],
    "判断": ["判断推理", "图形推理", "立体图推", "定义判断", "类比推理", "逻辑判断"],
    "图形推理": ["图形推理", "立体图推"],
    "图推": ["图形推理", "立体图推"],
    "立体图推": ["立体图推"],
    "立体": ["立体图推"],
    "定义判断": ["定义判断"],
    "定义": ["定义判断"],
    "类比推理": ["类比推理"],
    "类比": ["类比推理"],
    "逻辑判断": ["逻辑判断"],
    "逻辑": ["逻辑判断"],
    "资料分析": ["资料分析"],
    "资料": ["资料分析"],
}


def resolve_modules(module: str | None = None) -> list[str] | None:
    if not module or not isinstance(module, str) or module.strip().upper() in ("ALL", "全部", "全部模块", "NONE", ""):
        return None
    m = module.strip()
    return MODULE_ALIAS_MAP.get(m, [m])


def compose_data_analysis_practice(db, total_count: int = 50) -> list[str]:
    """Select complete passages of 5 questions each for Data Analysis.

    In Data Analysis, questions belong to a material/passage and must be
    practiced as intact 5-question blocks rather than fragmented individual questions.
    Passages with fewer than 5 verified questions are skipped: a partial block
    would break the intact-passage invariant. Only when the bank has no intact
    passage at all do we degrade to loose verified questions.
    """
    passage_rows = db.execute('''
        SELECT p.id,
               count(q.id) as q_cnt,
               count(a.id) as attempt_cnt,
               max(a.submitted_at) as last_sub
        FROM question_passages p
        JOIN questions q ON q.passage_id = p.id
        LEFT JOIN attempts a ON a.question_id = q.id AND a.submitted_at IS NOT NULL
        WHERE q.module = '资料分析' AND q.is_verified = 1
        GROUP BY p.id
        HAVING q_cnt >= 5
        ORDER BY
            (attempt_cnt = 0) DESC,
            attempt_cnt ASC,
            (last_sub IS NULL) DESC,
            last_sub ASC,
            p.id ASC
    ''').fetchall()

    selected_qids = []
    for prow in passage_rows:
        pid = prow['id']
        q_rows = db.execute('''
            SELECT id FROM questions
            WHERE passage_id = ? AND is_verified = 1
            ORDER BY id ASC
            LIMIT 5
        ''', (pid,)).fetchall()
        for qr in q_rows:
            selected_qids.append(qr['id'])
        if len(selected_qids) >= total_count:
            break

    if not selected_qids:
        # Degraded mode: no intact passage exists in the bank at all.
        more = db.execute('''
            SELECT id FROM questions
            WHERE module = '资料分析' AND is_verified = 1
            ORDER BY id ASC
            LIMIT ?
        ''', (total_count,)).fetchall()
        selected_qids.extend([r['id'] for r in more])

    return selected_qids[:total_count]


def compose_practice_questions(db, module: str | None = None, total_count: int = 50) -> list[str]:
    """Select questions for practice mode without fixed module proportions.

    If module is specified, questions are drawn exclusively from that module (or module group).
    If module is None or 'ALL', questions are drawn freely across all modules.
    Priority 1: Unpracticed verified questions.
    Priority 2: Least recently practiced verified questions.
    """
    all_count = db.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    if all_count == 0:
        raise HTTPException(409, "题库为空，无法组卷")

    target_modules = resolve_modules(module)

    if target_modules == ["资料分析"]:
        return compose_data_analysis_practice(db, total_count=total_count)

    if target_modules:
        mod_placeholders = ",".join(["?"] * len(target_modules))
        available_count = db.execute(
            f"SELECT COUNT(*) FROM questions WHERE module IN ({mod_placeholders}) AND is_verified = 1",
            target_modules,
        ).fetchone()[0]
        if available_count == 0:
            raise HTTPException(404, f"模块 [{module}] 暂无可用题目")
        total_count = max(1, min(available_count, total_count))
    else:
        verified_count = db.execute("SELECT COUNT(*) FROM questions WHERE is_verified = 1").fetchone()[0]
        if verified_count == 0:
            raise HTTPException(404, "暂无可用题目")
        total_count = max(1, min(verified_count, total_count))
        if verified_count <= 10:
            rows = db.execute("SELECT id FROM questions WHERE is_verified = 1 ORDER BY id LIMIT ?", (total_count,)).fetchall()
            return [r["id"] for r in rows]

    # Priority 1: Unpracticed questions
    if target_modules:
        mod_placeholders = ",".join(["?"] * len(target_modules))
        unpracticed = db.execute(
            f"""
            SELECT q.id FROM questions q
            WHERE q.module IN ({mod_placeholders})
              AND q.is_verified = 1
              AND q.id NOT IN (SELECT DISTINCT question_id FROM attempts WHERE submitted_at IS NOT NULL)
            ORDER BY q.id
            LIMIT ?
            """,
            (*target_modules, total_count),
        ).fetchall()
    else:
        unpracticed = db.execute(
            """
            SELECT q.id FROM questions q
            WHERE q.is_verified = 1
              AND q.id NOT IN (SELECT DISTINCT question_id FROM attempts WHERE submitted_at IS NOT NULL)
            ORDER BY q.id
            LIMIT ?
            """,
            (total_count,),
        ).fetchall()

    selected_qids = [r["id"] for r in unpracticed]

    # Priority 2: Least recently practiced questions if quota not met
    if len(selected_qids) < total_count:
        needed = total_count - len(selected_qids)
        placeholders = ",".join(["?"] * len(selected_qids)) if selected_qids else "''"

        if target_modules:
            mod_placeholders = ",".join(["?"] * len(target_modules))
            params = (*target_modules, *selected_qids, needed) if selected_qids else (*target_modules, needed)
            more = db.execute(
                f"""
                SELECT q.id FROM questions q
                LEFT JOIN (
                    SELECT question_id, MAX(submitted_at) as last_sub
                    FROM attempts
                    WHERE submitted_at IS NOT NULL
                    GROUP BY question_id
                ) a ON a.question_id = q.id
                WHERE q.module IN ({mod_placeholders})
                  AND q.is_verified = 1
                  AND q.id NOT IN ({placeholders})
                ORDER BY a.last_sub ASC, q.id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        else:
            params = (*selected_qids, needed) if selected_qids else (needed,)
            more = db.execute(
                f"""
                SELECT q.id FROM questions q
                LEFT JOIN (
                    SELECT question_id, MAX(submitted_at) as last_sub
                    FROM attempts
                    WHERE submitted_at IS NOT NULL
                    GROUP BY question_id
                ) a ON a.question_id = q.id
                WHERE q.is_verified = 1
                  AND q.id NOT IN ({placeholders})
                ORDER BY a.last_sub ASC, q.id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        selected_qids.extend([r["id"] for r in more])

    # Priority 3: Fallback from verified pool in case unpracticed/practiced quotas were partial
    if len(selected_qids) < total_count:
        needed = total_count - len(selected_qids)
        placeholders = ",".join(["?"] * len(selected_qids)) if selected_qids else "''"
        if target_modules:
            mod_placeholders = ",".join(["?"] * len(target_modules))
            params = (*target_modules, *selected_qids, needed) if selected_qids else (*target_modules, needed)
            more = db.execute(
                f"""
                SELECT id FROM questions
                WHERE module IN ({mod_placeholders}) AND is_verified = 1 AND id NOT IN ({placeholders})
                ORDER BY id
                LIMIT ?
                """,
                params,
            ).fetchall()
        else:
            params = (*selected_qids, needed) if selected_qids else (needed,)
            more = db.execute(
                f"""
                SELECT id FROM questions
                WHERE is_verified = 1 AND id NOT IN ({placeholders})
                ORDER BY id
                LIMIT ?
                """,
                params,
            ).fetchall()
        selected_qids.extend([r["id"] for r in more])

    return selected_qids


def start_mock_exam(db, time_limit_seconds: int = 7200, question_count: int | None = None) -> dict:
    """Create a new mock exam session in EXAM mode."""
    target_count = question_count or 130
    chosen = compose_real_exam_questions(db, total_count=target_count)
    sid = str(uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    db.execute('INSERT INTO sessions (id, mode, started_at, status) VALUES (?,?,?,?)', (sid, 'EXAM', now_iso, 'active'))
    db.executemany(
        'INSERT INTO session_questions (session_id, question_id, position) VALUES (?,?,?)',
        [(sid, qid, idx) for idx, qid in enumerate(chosen)],
    )
    max_score = float(len(chosen) * 10)  # 10 points per question
    db.execute(
        '''INSERT INTO exam_records
           (session_id, exam_type, time_limit_seconds, total_questions, max_score, created_at)
           VALUES (?,?,?,?,?,?)''',
        (sid, 'MOCK', time_limit_seconds, len(chosen), max_score, now_iso),
    )
    db.commit()

    return {
        'session_id': sid,
        'mode': 'EXAM',
        'exam_type': 'MOCK',
        'total_questions': len(chosen),
        'time_limit_seconds': time_limit_seconds,
        'started_at': now_iso,
    }


def submit_exam_paper(db, session_id: str) -> dict:
    """Grade complete exam, persist results, and unlock review mode."""
    sess = db.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
    if sess is None:
        raise HTTPException(404, '考试会话不存在')
    if sess['mode'] != 'EXAM':
        raise HTTPException(400, '该会话不是模考会话')
    if sess['status'] == 'completed':
        # Idempotent return existing record
        rec = db.execute('SELECT * FROM exam_records WHERE session_id=?', (session_id,)).fetchone()
        return dict(rec)

    now_iso = datetime.now(timezone.utc).isoformat()

    # Grade all attempts
    attempts = db.execute(
        '''SELECT a.*, q.answer, q.difficulty FROM attempts a
           JOIN questions q ON q.id=a.question_id
           WHERE a.session_id=?''',
        (session_id,),
    ).fetchall()

    correct_count = sum(1 for a in attempts if a['submitted_at'] is not None and a['correct'] == 1)
    answered_count = sum(1 for a in attempts if a['submitted_at'] is not None)
    total_q = db.execute('SELECT COUNT(*) FROM session_questions WHERE session_id=?', (session_id,)).fetchone()[0]

    earned_score = correct_count * 10.0
    max_score = total_q * 10.0

    db.execute(
        '''UPDATE exam_records
           SET earned_score=?, completed_at=?
           WHERE session_id=?''',
        (earned_score, now_iso, session_id),
    )
    db.execute(
        "UPDATE sessions SET status='completed', completed_at=? WHERE id=?",
        (now_iso, session_id),
    )

    rebuild_mastery(db)
    rebuild_reviews(db)
    db.commit()

    return {
        'session_id': session_id,
        'status': 'completed',
        'earned_score': earned_score,
        'max_score': max_score,
        'correct_count': correct_count,
        'total_questions': total_q,
        'accuracy': (correct_count / total_q) if total_q else 0.0,
        'completed_at': now_iso,
    }
