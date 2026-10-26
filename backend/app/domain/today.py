# -*- coding: utf-8 -*-
"""统一每日学习入口聚合：把分散的 今日目标/到期复习/每日计划/学习任务/教学遗留
拼成一个视图。只聚合既有真实数据源，不另建统计口径——每项完成状态都有真源
（attempts 计数、review_cards due、study_tasks 行状态、教学轮次落库）。
"""
import json
from datetime import datetime, timezone

from .daily_goal import daily_goal as get_daily_goal
from . import planner


def today_view(db):
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    due_count = db.execute(
        'SELECT COUNT(*) FROM review_cards WHERE due<=?', (now_iso,)).fetchone()[0]
    active_review = db.execute(
        "SELECT id FROM sessions WHERE mode='REVIEW' AND status='active' LIMIT 1").fetchone()

    # 每日计划：幂等（当日已存在则复用，planner 语义）
    try:
        plan = planner.generate_daily_plan(db)
        plan_summary = {
            'exists': bool(plan),
            'allocation': plan.get('allocation') if plan else None,
            'question_count': len(plan.get('items') or []) if plan else 0,
        }
    except Exception:  # noqa: BLE001 —— 计划生成失败不拖垮今日入口
        plan_summary = {'exists': False, 'allocation': None, 'question_count': 0,
                        'error': 'daily plan unavailable'}

    study_pending = db.execute(
        """SELECT COUNT(*) FROM study_tasks t JOIN study_task_sets s ON s.id=t.set_id
           WHERE s.status='published' AND t.status='published'""").fetchone()[0]
    teaching_pending = db.execute(
        """SELECT COUNT(*) FROM study_tasks t JOIN study_task_sets s ON s.id=t.set_id
           WHERE s.status='published' AND t.status='published'
             AND json_extract(t.detail_json,'$.origin')='teaching_pending_question'"""
    ).fetchone()[0]
    active_teaching = db.execute(
        """SELECT COUNT(DISTINCT knowledge_node_id) FROM node_teaching_sessions
           WHERE status='active'""").fetchone()[0]

    return {
        'as_of': now_iso,
        'daily_goal': get_daily_goal(db),
        'due_reviews': {'count': due_count,
                        'active_session_id': active_review['id'] if active_review else None},
        'plan_today': plan_summary,
        'study_tasks': {'pending': study_pending, 'teaching_pending': teaching_pending},
        'teaching_sessions': {'active_nodes': active_teaching},
    }
