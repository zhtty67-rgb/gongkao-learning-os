"""Local question image transport, without public URLs or arbitrary file reads."""
import base64
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

ASSETS_ROOT = Path(__file__).resolve().parents[3] / 'data' / 'assets'
MIMES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif'}
VISION_RULE = ('\n【图形输入】本轮附有题库原题及选项图片，图片按提供顺序标注。先核对每格图形的线条、位置、方向和选项，'
               '再检验规律是否覆盖所有已知格。学生描述与历史教师回复不替代图片事实。'
               '看不清的部分明确说明，不猜测细小线条；不得仅根据标准答案反编规律。'
               '解释要指出具体图格与变化，区分观察事实和规律假设。')


def question_image_input(db, question_id: str) -> tuple[list[str], str]:
    q = db.execute('SELECT stem_assets_json,option_assets_json FROM questions WHERE id=?', (question_id,)).fetchone()
    if not q:
        raise ValueError('题目不存在')
    items = [('原题图'+str(i+1), url) for i, url in enumerate(json.loads(q['stem_assets_json'] or '[]'))]
    for option, urls in json.loads(q['option_assets_json'] or '{}').items():
        items.extend(('选项'+option+'图'+str(i+1), url) for i, url in enumerate(urls))
    images, labels, seen = [], [], set()
    total = 0
    for label, url in items:
        if url in seen:
            continue
        seen.add(url)
        path = urlsplit(url)
        if path.scheme or path.netloc or not path.path.startswith('/assets/'):
            raise ValueError('题目图片须为本地题库资源')
        target = (ASSETS_ROOT / unquote(path.path[len('/assets/'):])).resolve()
        if not target.is_relative_to(ASSETS_ROOT.resolve()) or target.suffix.lower() not in MIMES:
            raise ValueError('题目图片路径或格式无效')
        size = target.stat().st_size
        total += size
        if size > 8 * 1024 * 1024 or total > 16 * 1024 * 1024 or len(images) >= 16:
            raise ValueError('题目图片超过单次输入限制')
        from PIL import Image
        with Image.open(target) as img:
            img.verify()
        data = base64.b64encode(target.read_bytes()).decode('ascii')
        images.append('data:' + MIMES[target.suffix.lower()] + ';base64,' + data)
        labels.append(f'第{len(images)}张：{label}')
    if not images:
        raise ValueError('该题尚未收录可用图片')
    return images, '\n'.join(labels)


def vision_availability(db, question_id: str) -> tuple[bool, str | None]:
    from ..ai import get_model_gateway
    gateway_config = getattr(get_model_gateway(), 'config', None)
    config = gateway_config.policies.get('BALANCED') if gateway_config else None
    if not config or not config.supports_vision:
        return False, '当前模型策略尚未配置图片读取能力，可查看题库解析。'
    try:
        question_image_input(db, question_id)
    except (OSError, ValueError) as exc:
        return False, str(exc) + '，可查看题库已有解析。'
    return True, None


def question_image_urls(db, question_id: str) -> list[dict]:
    """Display URLs (not model input) so the frontend can render the question's
    figures next to explanations that say 如下图所示."""
    q = db.execute('SELECT stem_assets_json,option_assets_json FROM questions WHERE id=?', (question_id,)).fetchone()
    if not q:
        return []
    items = [('原题图' + str(i + 1), url) for i, url in enumerate(json.loads(q['stem_assets_json'] or '[]'))]
    for option, urls in json.loads(q['option_assets_json'] or '{}').items():
        items.extend(('选项' + option + '图' + str(i + 1), url) for i, url in enumerate(urls))
    out, seen = [], set()
    for label, url in items:
        if not isinstance(url, str) or url in seen or not url.startswith('/assets/'):
            continue
        seen.add(url)
        out.append({'label': label, 'url': url})
    return out


def graphic_transfer_question(db, original_id: str, excluded: list[str]):
    rows = db.execute('''SELECT q.* FROM questions q
        JOIN question_knowledge_map peer ON peer.question_id=q.id
        JOIN question_knowledge_map original ON original.knowledge_node_id=peer.knowledge_node_id
        WHERE original.question_id=? AND q.id<>? AND q.module IN ('图形推理','立体图推')
          AND q.answer IN ('A','B','C','D') AND q.stem_assets_json<>'[]'
        GROUP BY q.id ORDER BY COUNT(DISTINCT peer.knowledge_node_id) DESC,
          EXISTS(SELECT 1 FROM attempts a WHERE a.question_id=q.id AND a.submitted_at IS NOT NULL), q.id LIMIT 30''',
        (original_id, original_id)).fetchall()
    for row in rows:
        if row['id'] in excluded:
            continue
        try:
            question_image_input(db, row['id'])
        except (OSError, ValueError):
            continue
        return dict(row)
    return None


def format_graphic_transfer(question: dict) -> str:
    # Existing bank diagrams provide a verifiable visual variant, without
    # asking a language model to draw arbitrary, ungraded graphical options.
    lines = ['### 同考点题库变式（非自编）', question['stem']]
    lines += [f'![题目图{i+1}]({url})' for i, url in enumerate(json.loads(question['stem_assets_json'] or '[]'))]
    option_images = json.loads(question['option_assets_json'] or '{}')
    for option, value in json.loads(question['options_json']).items():
        lines.append(f'**{option}.** {value if value != option else ""}')
        lines += [f'![选项{option}]({url})' for url in option_images.get(option, [])]
    lines.append('请独立选择选项并说明规律；暂不展示答案，原题成绩不变。')
    return '\n\n'.join(lines)
