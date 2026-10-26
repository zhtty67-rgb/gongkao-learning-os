"""Narrow, verifiable checks of student work; never promote a claim to a fact."""
import re

STUDENT_WORK_RULE = (
    '\n【学生推导核验】学生中间值、错因自述和历史教师回复都是待核验主张，不能当作题目已知。'
    '先从原题条件独立核对公式、取数、单位及每一步计算，追溯到最早错误再教学。'
    '上游错误产生的差额、比率、结论必须重算，不能仅在错误值上做正确运算。'
    '历史教师说错时明确更正。来源不明的数值先问它由什么算式得到；无法核验时说明缺失条件。'
    '回复聚焦当前卡点，避免重复长篇解析。'
    '排版使用规范Markdown，列表逐行书写；数学公式用$...$行内或独占行的$$...$$块公式，百分号在公式中写\\%。'
)


def check_student_work(ctx: dict, student_text: str) -> list[dict]:
    """Check explicit equations and identifiable growth-distribution pairs.

    The pair check requires a growth-amount question, an unambiguous revenue
    amount/rate in the original explanation and a student-labelled assumption.
    It does not infer rates from arbitrary numeric mentions or assistant history.
    """
    from .review_context import verify_explanation_support
    checks = []
    equations = verify_explanation_support({'derivation_steps': [student_text]}, {'module': '数量关系'})
    for issue in equations.issues:
        checks.append({'issue': issue, 'correction': '先重算这一步，再检查依赖它的所有后续数值。'})
    if '资料' not in ctx.get('module', '') or not re.search(r'增长[额量]', ctx.get('stem', '')):
        return checks
    original = re.sub(r'\s+', '', ctx.get('authoritative_explanation', ''))
    facts = re.search(r'收入([0-9]+(?:\.[0-9]+)?)(万亿元|亿元|万元|元)[，,]?(?:比上年|同比)增长([0-9]+(?:\.[0-9]+)?)%', original)
    if not facts:
        return checks
    current, unit, rate = facts.groups()
    current, rate = float(current), float(rate) / 100
    pairs = list(re.finditer(r'(?:假设分配(?:法)?[，,：: ]*先分|先分|(?:假设|设)基期(?:为|是)?)[：: ]*([0-9]+(?:\.[0-9]+)?)(?:和|与|、|[，,](?:增量|增长量)(?:为|是)?)([0-9]+(?:\.[0-9]+)?)', student_text))
    if not pairs:
        return checks
    base, claimed = map(float, pairs[-1].groups())
    expected = base * rate
    if abs(expected - claimed) <= max(1e-8, abs(expected) * 0.001):
        return checks
    residual = base + expected - current
    fmt = lambda n: format(n, '.10g')
    checks.append({
        'issue': f'假设基期{fmt(base)}对应的增量{fmt(claimed)}计算错误',
        'wrong_value': fmt(claimed), 'correct_value': fmt(expected),
        'correction': f'先纠正第一步：{fmt(base)}×{fmt(rate * 100)}%={fmt(expected)}（{unit}）。'
                      f'两部分合计{fmt(base + expected)}，与材料现期{fmt(current)}的差额是{fmt(residual)}。'
                      '旧差额由错误增量产生，不能继续使用；之后才按同一增长率分配差额。',
    })
    return checks


def work_check_prompt(checks: list[dict]) -> str:
    if not checks:
        return STUDENT_WORK_RULE
    return STUDENT_WORK_RULE + '\n【已核验的学生上游错误，必须先处理】\n' + '\n'.join(c['issue'] + '：' + c['correction'] for c in checks)


def missed_work_correction(text: str, checks: list[dict]) -> bool:
    # An answer that merely continues with a wrong derived value is insufficient,
    # even if its local arithmetic is correct. Require the checked correction.
    return any(c.get('correct_value') and not re.search(
        rf'(?<![\d.]){re.escape(c["correct_value"])}(?![\d.])', text
    ) for c in checks)
