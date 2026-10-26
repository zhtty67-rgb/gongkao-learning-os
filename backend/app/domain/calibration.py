"""Confidence Calibration and Brier Score tracking."""
from typing import Any

from .attempt_verdict import correct_expr


def calculate_calibration(db) -> dict[str, Any]:
    """Calculate Brier score, calibration bins, and high-confidence error analytics."""
    cols = [c[1] for c in db.execute('PRAGMA table_info(attempts)').fetchall()]
    valid_filter = "AND a.valid_for_stats = 1" if 'valid_for_stats' in cols else ""
    rows = db.execute(
        f'''SELECT a.id, a.question_id, a.confidence, {correct_expr(db)} AS correct, a.elapsed_ms, a.submitted_at,
                  q.stem, q.module
           FROM attempts a
           JOIN questions q ON q.id=a.question_id
           WHERE a.submitted_at IS NOT NULL AND a.confidence IS NOT NULL {valid_filter}
           ORDER BY a.submitted_at DESC'''
    ).fetchall()

    if not rows:
        return {
            'attempt_count': 0,
            'brier_score': None,
            'overconfidence_bias': 0.0,
            'calibration_bins': [],
            'high_confidence_errors': {
                'count': 0,
                'items': [],
            },
        }

    n = len(rows)
    squared_errors = []
    conf_sum = 0.0
    correct_sum = 0.0
    high_conf_errors = []

    # Bin containers
    bins_data: dict[float, list[int]] = {0.2: [], 0.4: [], 0.6: [], 0.8: [], 1.0: []}

    for row in rows:
        conf = float(row['confidence'])
        y = 1.0 if row['correct'] else 0.0
        squared_errors.append((conf - y) ** 2)
        conf_sum += conf
        correct_sum += y

        closest_bin = min(bins_data.keys(), key=lambda b: abs(b - conf))
        bins_data[closest_bin].append(int(row['correct']))

        if conf >= 0.8 and row['correct'] == 0:
            high_conf_errors.append({
                'attempt_id': row['id'],
                'question_id': row['question_id'],
                'stem': row['stem'],
                'module': row['module'],
                'confidence': conf,
                'elapsed_ms': row['elapsed_ms'],
                'submitted_at': row['submitted_at'],
            })

    brier = sum(squared_errors) / n
    bias = (conf_sum / n) - (correct_sum / n)

    bins_list = []
    for bin_level in sorted(bins_data.keys()):
        outcomes = bins_data[bin_level]
        bins_list.append({
            'bin_confidence': bin_level,
            'count': len(outcomes),
            'empirical_accuracy': (sum(outcomes) / len(outcomes)) if outcomes else None,
        })

    return {
        'attempt_count': n,
        'brier_score': round(brier, 4),
        'overconfidence_bias': round(bias, 4),
        'calibration_bins': bins_list,
        'high_confidence_errors': {
            'count': len(high_conf_errors),
            'items': high_conf_errors[:10],
        },
    }
