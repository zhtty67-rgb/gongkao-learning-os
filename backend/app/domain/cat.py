"""Computerized Adaptive Testing (CAT) based on 1PL Item Response Theory."""
import math
from typing import Any
from fastapi import HTTPException


def difficulty_to_b(difficulty: float) -> float:
    """Map [0.0, 1.0] difficulty to [-2.5, +2.5] IRT logit scale."""
    return (float(difficulty) - 0.5) * 5.0


def irt_prob(theta: float, b: float) -> float:
    """1PL logistic probability P(correct=1 | theta, b)."""
    exponent = -(theta - b)
    # Numerical stability clamping
    if exponent > 30.0:
        return 0.0
    if exponent < -30.0:
        return 1.0
    return 1.0 / (1.0 + math.exp(exponent))


def fisher_information(theta: float, b: float) -> float:
    """Fisher Information I(theta, b) = P * (1 - P)."""
    p = irt_prob(theta, b)
    return p * (1.0 - p)


def estimate_ability_theta(responses: list[tuple[float, int]], prior_var: float = 1.0) -> tuple[float, float]:
    """Estimate ability theta and standard error via Maximum A Posteriori (MAP / regularized estimator).
    
    Uses a standard normal prior theta ~ N(0, prior_var) to guarantee finite, well-behaved
    estimates even on all-correct or all-wrong response sequences.
    
    responses: list of (question_difficulty_0_to_1, is_correct_0_or_1)
    """
    if not responses:
        return 0.0, round(1.0 / math.sqrt(1.0 / prior_var), 4)

    theta = 0.0
    for _ in range(20):  # Newton-Raphson iterations
        dl = -(theta / prior_var)  # prior log derivative
        d2l = -(1.0 / prior_var)   # prior 2nd derivative

        for diff, y in responses:
            b = difficulty_to_b(diff)
            p = irt_prob(theta, b)
            dl += (y - p)
            d2l -= (p * (1.0 - p))

        step = dl / d2l
        theta -= step
        theta = max(-3.0, min(3.0, theta))  # Clamp to reasonable finite bounds [-3.0, +3.0]
        if abs(step) < 1e-4:
            break

    # Standard error SE = 1 / sqrt(-d2l)
    se = 1.0 / math.sqrt(max(1e-4, -d2l))
    return round(theta, 4), round(se, 4)


def select_cat_question(db, current_theta: float, excluded_ids: list[str]) -> dict[str, Any] | None:
    """Select the item that maximizes Fisher Information at current theta."""
    placeholders = ','.join('?' for _ in excluded_ids) if excluded_ids else "''"
    query = f'''SELECT id, module, stem, options_json, difficulty, estimated_seconds
               FROM questions
               WHERE is_verified = 1 AND id NOT IN ({placeholders})
               ORDER BY id'''
    rows = db.execute(query, tuple(excluded_ids)).fetchall()
    if not rows:
        return None

    # Maximize information = minimize |b - theta|
    best_item = None
    best_info = -1.0
    for row in rows:
        b = difficulty_to_b(row['difficulty'])
        info = fisher_information(current_theta, b)
        if info > best_info:
            best_info = info
            best_item = row

    if best_item:
        item = dict(best_item)
        item['b_difficulty'] = round(difficulty_to_b(item['difficulty']), 2)
        item['expected_info'] = round(best_info, 4)
        return item
    return None


def should_stop_cat(num_answered: int, standard_error: float, min_items: int = 3, max_items: int = 15, se_target: float = 0.35) -> bool:
    """Evaluate stopping rule for CAT."""
    if num_answered >= max_items:
        return True
    if num_answered >= min_items and standard_error <= se_target:
        return True
    return False


def theta_to_ability_band(theta: float) -> dict[str, Any]:
    """Convert theta into an assumed-distribution percentile and ability band.
    
    NOTE: In the absence of large-scale empirical Gongkao calibration norm data,
    this percentile is model-relative / assumed-distribution based on N(0, 1),
    not a verified empirical population norm.
    """
    z = max(-3.0, min(3.0, theta))
    p = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    assumed_percentile = max(1, min(99, int(round(p * 100))))

    if theta >= 1.2:
        band = '优秀卓越 (Advanced)'
    elif theta >= 0.4:
        band = '良好熟练 (Proficient)'
    elif theta >= -0.4:
        band = '稳步进阶 (Intermediate)'
    elif theta >= -1.2:
        band = '基础待夯实 (Basic)'
    else:
        band = '起步攻坚 (Novice)'

    return {
        'assumed_distribution_percentile': assumed_percentile,
        'ability_band': band,
        'normalized_score': round(50.0 + 15.0 * theta, 1),  # Standard T-score (mean 50, sd 15)
    }


def theta_to_percentile(theta: float) -> int:
    """Backward compatibility alias for assumed_distribution_percentile."""
    return theta_to_ability_band(theta)['assumed_distribution_percentile']
