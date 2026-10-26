from .daily_goal import daily_goal as get_daily_goal
from .attempt_verdict import correct_expr
from .learning_framework import ERROR_TAXONOMY_LABELS

# Unified Phase LF1 / DEC-0003 Error Analysis Taxonomy
ERROR_LABELS = ERROR_TAXONOMY_LABELS


def latest_error_cte():
    return '''WITH ranked_errors AS (
      SELECT e.*,ROW_NUMBER() OVER (PARTITION BY attempt_id ORDER BY created_at DESC,id DESC) rn
      FROM error_events e
    )'''


def get_credibility_audit(db):
    """Calculate centralized, transparent credibility metrics and accounting rules."""
    cols = [c[1] for c in db.execute('PRAGMA table_info(attempts)').fetchall()]
    has_credibility_cols = 'valid_for_stats' in cols and 'timing_valid' in cols and 'source_type' in cols
    has_est_cols = 'is_time_estimated' in cols

    if not has_credibility_cols:
        total_sub = db.execute('SELECT COUNT(*) FROM attempts WHERE submitted_at IS NOT NULL').fetchone()[0]
        return {
            'total_submitted': total_sub,
            'valid_stats_count': total_sub,
            'excluded_test_count': 0,
            'unknown_source_count': total_sub,
            'real_study_count': 0,
            'first_time_count': total_sub,
            'repeat_count': 0,
            'valid_timing_count': total_sub,
            'invalid_timing_count': 0,
            'measured_timing_count': total_sub,
            'estimated_timing_count': 0,
            'assisted_count': 0,
            'unassisted_count': 0,
            'unknown_exposure_count': total_sub,
            'rules_explanation': [
                '尚未启用可信度扩展列，所有提交作答均按初始口径统计。'
            ]
        }

    # 1. 首次 vs 重复作答 (仅统计 valid_for_stats=1)
    first_vs_repeat = db.execute('''
        WITH ranked_attempts AS (
            SELECT a.id, a.question_id, a.submitted_at,
                   ROW_NUMBER() OVER (PARTITION BY a.question_id ORDER BY a.submitted_at ASC, a.id ASC) as rn
            FROM attempts a
            WHERE a.submitted_at IS NOT NULL AND a.valid_for_stats = 1
        )
        SELECT 
            COUNT(*) as total_valid,
            COALESCE(SUM(CASE WHEN rn = 1 THEN 1 ELSE 0 END), 0) as first_time_count,
            COALESCE(SUM(CASE WHEN rn > 1 THEN 1 ELSE 0 END), 0) as repeat_count
        FROM ranked_attempts
    ''').fetchone()

    # 2. 来源、资格、辅助与计时
    est_clause = "COALESCE(SUM(CASE WHEN valid_for_stats = 1 AND is_time_estimated = 1 THEN 1 ELSE 0 END), 0) as estimated_timing_count, COALESCE(SUM(CASE WHEN valid_for_stats = 1 AND COALESCE(is_time_estimated, 0) = 0 THEN 1 ELSE 0 END), 0) as measured_timing_count," if has_est_cols else "0 as estimated_timing_count, COUNT(*) as measured_timing_count,"

    cred = db.execute(f'''
        SELECT 
            COUNT(*) as total_submitted,
            COALESCE(SUM(CASE WHEN valid_for_stats = 1 THEN 1 ELSE 0 END), 0) as valid_stats_count,
            COALESCE(SUM(CASE WHEN valid_for_stats = 0 THEN 1 ELSE 0 END), 0) as excluded_test_count,
            COALESCE(SUM(CASE WHEN valid_for_stats = 1 AND source_type = 'UNKNOWN' THEN 1 ELSE 0 END), 0) as unknown_source_count,
            COALESCE(SUM(CASE WHEN valid_for_stats = 1 AND source_type = 'REAL_STUDY' THEN 1 ELSE 0 END), 0) as real_study_count,
            COALESCE(SUM(CASE WHEN valid_for_stats = 1 AND timing_valid = 1 THEN 1 ELSE 0 END), 0) as valid_timing_count,
            COALESCE(SUM(CASE WHEN valid_for_stats = 1 AND timing_valid = 0 THEN 1 ELSE 0 END), 0) as invalid_timing_count,
            {est_clause}
            COALESCE(SUM(CASE WHEN valid_for_stats = 1 AND exposure_state = 'ASSISTED' THEN 1 ELSE 0 END), 0) as assisted_count,
            COALESCE(SUM(CASE WHEN valid_for_stats = 1 AND exposure_state = 'NO_ASSISTANCE' THEN 1 ELSE 0 END), 0) as unassisted_count,
            COALESCE(SUM(CASE WHEN valid_for_stats = 1 AND exposure_state = 'UNKNOWN' THEN 1 ELSE 0 END), 0) as unknown_exposure_count
        FROM attempts
        WHERE submitted_at IS NOT NULL
    ''').fetchone()

    return {
        'total_submitted': cred['total_submitted'],
        'valid_stats_count': cred['valid_stats_count'],
        'excluded_test_count': cred['excluded_test_count'],
        'unknown_source_count': cred['unknown_source_count'],
        'real_study_count': cred['real_study_count'],
        'first_time_count': first_vs_repeat['first_time_count'] if first_vs_repeat else 0,
        'repeat_count': first_vs_repeat['repeat_count'] if first_vs_repeat else 0,
        'valid_timing_count': cred['valid_timing_count'],
        'invalid_timing_count': cred['invalid_timing_count'],
        'measured_timing_count': cred['measured_timing_count'],
        'estimated_timing_count': cred['estimated_timing_count'],
        'assisted_count': cred['assisted_count'],
        'unassisted_count': cred['unassisted_count'],
        'unknown_exposure_count': cred['unknown_exposure_count'],
        'rules_explanation': [
            '已确认的自动化测试作答（AUTO_TEST）已完全排除出正式学习统计、掌握度演进与复习安排。',
            '历史未标注来源的作答诚实标记为 UNKNOWN 并单独列出，绝不伪造为真实自主学习。',
            '耗时在 1 秒至 4 小时之间仅作为当前粗筛异常规则，不代表其余记录均为真实思考时间；异常耗时仅从速度分析中剔除，正误记录真实保留。',
            '材料组题量均分耗时已明确标识为估算值，单题平均耗时仅基于可用单题实测样本计算。',
            '历史缺少辅助日志的作答保留为 UNKNOWN；本次作答未记录系统辅助仅代表无内置提示，不代表用户未从外部看过该题或人生首次见题。',
            '未练习考点展示为未练习，不解释为能力差；样本不足时不作过度能力推断。'
        ]
    }


def dashboard(db, overall):
    cols = [c[1] for c in db.execute('PRAGMA table_info(attempts)').fetchall()]
    has_credibility_cols = 'valid_for_stats' in cols and 'timing_valid' in cols
    has_est_cols = 'is_time_estimated' in cols

    if has_credibility_cols:
        est_filter = "AND COALESCE(is_time_estimated, 0) = 0" if has_est_cols else ""
        totals = db.execute(
            f'''SELECT COUNT(*) count,COALESCE(SUM({correct_expr(db)}),0) correct,
                      AVG(CASE WHEN timing_valid = 1 {est_filter} THEN elapsed_ms ELSE NULL END) avg_elapsed,
                      COALESCE(SUM(CASE WHEN {correct_expr(db)}=0 AND confidence>=0.8 THEN 1 ELSE 0 END),0) high_confidence_errors,
                      COALESCE(SUM(CASE WHEN timing_valid=1 {est_filter} AND elapsed_ms<=q.estimated_seconds*1000 THEN 1 ELSE 0 END),0) timed_count,
                      COALESCE(SUM(CASE WHEN timing_valid=1 {est_filter} AND elapsed_ms<=q.estimated_seconds*1000 AND {correct_expr(db)}=1 THEN 1 ELSE 0 END),0) timed_correct,
                      COALESCE(SUM(CASE WHEN hint_level>0 THEN 1 ELSE 0 END),0) hinted
               FROM attempts a JOIN questions q ON q.id=a.question_id 
               WHERE submitted_at IS NOT NULL AND valid_for_stats = 1'''
        ).fetchone()
    else:
        totals = db.execute(
            '''SELECT COUNT(*) count,COALESCE(SUM(correct),0) correct,
                      AVG(elapsed_ms) avg_elapsed,
                      COALESCE(SUM(CASE WHEN {correct_expr(db)}=0 AND confidence>=0.8 THEN 1 ELSE 0 END),0) high_confidence_errors,
                      COALESCE(SUM(CASE WHEN elapsed_ms<=q.estimated_seconds*1000 THEN 1 ELSE 0 END),0) timed_count,
                      COALESCE(SUM(CASE WHEN elapsed_ms<=q.estimated_seconds*1000 AND {correct_expr(db)}=1 THEN 1 ELSE 0 END),0) timed_correct,
                      COALESCE(SUM(CASE WHEN hint_level>0 THEN 1 ELSE 0 END),0) hinted
               FROM attempts a JOIN questions q ON q.id=a.question_id WHERE submitted_at IS NOT NULL'''
        ).fetchone()
    count = totals['count']
    nodes = [dict(row) for row in db.execute(
        '''SELECT kn.id,kn.name,kn.module,ms.mastery_score,ms.attempt_count,ms.recent_accuracy,ms.avg_time_ratio
           FROM knowledge_nodes kn JOIN mastery_state ms ON ms.knowledge_node_id=kn.id
           ORDER BY CASE WHEN ms.attempt_count>0 THEN 0 ELSE 1 END,ms.mastery_score,kn.exam_priority DESC,kn.name'''
    )]
    practiced = [node for node in nodes if node['attempt_count']]
    weakest = practiced[0] if practiced else None

    daily_goal = get_daily_goal(db)

    audit = get_credibility_audit(db)

    return {
        'metrics': {
            'attempt_count': count,
            'accuracy': totals['correct'] / count if count else None,
            'timed_accuracy': totals['timed_correct'] / totals['timed_count'] if totals['timed_count'] else None,
            'average_elapsed_ms': round(totals['avg_elapsed']) if totals['avg_elapsed'] is not None else None,
            'mastery': overall,
            'high_confidence_errors': totals['high_confidence_errors'],
            'hint_dependency': totals['hinted'] / count if count else 0,
        },
        'credibility_audit': audit,
        'daily_goal': daily_goal,
        'weakest': weakest,
        'recommendation': (
            f"优先练习“{weakest['name']}”：当前掌握度 {round(weakest['mastery_score'] * 100)}%，来自 {weakest['attempt_count']} 次作答。"
            if weakest else '完成首轮训练后，这里会根据真实作答给出建议。'
        ),
    }
