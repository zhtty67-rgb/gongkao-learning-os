"""教师语料脱敏导出：只发提炼层（规则/案例/纠偏），剔除全部课堂原话引用，
并把教师真名替换为代号。

原则：
- 提炼层（policies 的 name/trigger/rule/reasoning/示例、question_cases 的题干与解析、
  critique_cases 的诊断与纠偏）保留——这是方法知识的再表达，不是原话。
- 剔除层：任何 `quote` / `source_quote` / `source` 中指向逐字稿的引用、逐字稿本体。
- 教师身份：真名 → 代号（T1..T10），机构名同步替换。
- 题库 source（如「花生逻辑判断600题」）是公开练习册溯源，**不改**——改名会破坏
  「按原书找题」功能。

用法：
  python scripts/sanitize_teacher_corpus.py --out release/teachers_refined
  python scripts/sanitize_teacher_corpus.py --verify release/teachers_refined
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 真名 → 代号（按模块固定，便于使用者理解分工）
NAME_MAP = {
    '花生十三': 'L 老师',
    '龙飞': 'G 老师',
    '江牧云': 'W 老师',
    '阿里木江': 'A 老师',
    '冯泽': 'P 老师',
    '拾伊': 'S 老师',
    '碎碎': 'X 老师',
    '四海': '协作组',
}
TEACHER_ID_MAP = {
    'teacher_logic': 'T1',
    'teacher_definition': 'T2',
    'teacher_quant': 'T3',
    'teacher_data': 'T4',
    'teacher_longfei': 'T5',
    'teacher_jiangmuyun': 'T6',
    'teacher_alimujiang': 'T7',
    'teacher_huasheng_verbal': 'T8',
    'teacher_fengze_politics': 'T9',
    'teacher_fengze_common_sense': 'T10',
}
# 文件名里的真名（如 teacher_fengze_*/library 内文件）也一并处理
# 指向逐字稿的定位字段：文件+行号+字符区间，即使不含原话文本也可回溯原文，
# 必须整体剔除（否则等于给了「去原文第 1659–1704 字符取原话」的地址）
TRANSCRIPT_KEYS = {'quote', 'source_quote', 'source_quotes', 'transcript', 'transcripts',
                   'raw_quote', 'original_quote'}
# 引用对象内一旦出现这些定位字段，整个引用项丢弃
LOCATOR_KEYS = {'file', 'line_start', 'line_end', 'char_start', 'char_end',
                'quote_type', 'course'}
DROP_DIRS = {'transcripts', 'cleaned_transcripts', 'quarantine', 'reference', 'out'}
# 逐字稿切片库：文件名即表明内容为课堂原文切片，整体不导出
DROP_FILES = {'transcript_chunks.json', 'transcript_index.json', 'raw_transcript.json'}


def scrub_text(text: str) -> str:
    for real, alias in NAME_MAP.items():
        text = text.replace(real, alias)
    return text


def scrub_value(value, key=None):
    """递归清洗：丢弃原话引用字段，其余值做名字替换。"""
    if key in TRANSCRIPT_KEYS:
        return None
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, list):
        out = [scrub_value(v) for v in value]
        # 引用列表：丢弃所有指向逐字稿定位的项（哪怕只剩定位也不要）
        out = [v for v in out if v is not None]
        out = [v for v in out if not (isinstance(v, dict) and LOCATOR_KEYS & set(v))]
        return out
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in TRANSCRIPT_KEYS:
                continue
            # 键也可能带真名（如 teachers_distribution 的对象键），一并替换
            new_key = scrub_text(k) if isinstance(k, str) else k
            cleaned = scrub_value(v, k)
            if cleaned is not None:
                out[new_key] = cleaned
        return out
    return value


def sanitize_policy(item):
    """政策条目：保留方法规则，删除任何指向逐字稿的引用与定位。"""
    cleaned = scrub_value(item)
    cleaned.pop('source', None)   # source 即逐字稿定位数组，整体剔除
    return cleaned


def iter_json_items(doc):
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict):
        for key in ('policies', 'cases', 'items', 'entries'):
            if isinstance(doc.get(key), list):
                return doc[key]
        # 兜底：取第一个 list 值
        for value in doc.values():
            if isinstance(value, list):
                return value
    return []


def rebuild_doc(original, cleaned_items):
    if isinstance(original, list):
        return cleaned_items
    if isinstance(original, dict):
        for key in ('policies', 'cases', 'items', 'entries'):
            if isinstance(original.get(key), list):
                doc = dict(original)
                doc[key] = cleaned_items
                return doc
        for key, value in list(original.items()):
            if isinstance(value, list):
                doc = dict(original)
                doc[key] = cleaned_items
                return doc
    return cleaned_items


def _write_json_scrubbed(src_file: Path, dst: Path, stats: dict, label: str):
    try:
        doc = json.loads(src_file.read_text(encoding='utf-8'))
    except (ValueError, OSError) as exc:
        stats['skipped'].append(f'{label}: {exc}')
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(scrub_value(doc), ensure_ascii=False, indent=1),
                   encoding='utf-8')
    return True


def export_teacher(src: Path, dst: Path, stats: dict):
    library = src / 'library'
    if not library.is_dir():
        return False
    dst_lib = dst / 'library'
    dst_lib.mkdir(parents=True, exist_ok=True)
    for jf in library.glob('*.json'):
        if jf.name in DROP_FILES:
            stats['skipped'].append(f'{src.name}/{jf.name}: 逐字稿切片库，整体排除')
            continue
        try:
            doc = json.loads(jf.read_text(encoding='utf-8'))
        except (ValueError, OSError) as exc:
            stats['skipped'].append(f'{src.name}/{jf.name}: {exc}')
            continue
        items = iter_json_items(doc)
        cleaner = sanitize_policy if 'polic' in jf.name.lower() else scrub_value
        cleaned = [cleaner(item) for item in items if isinstance(item, dict)]
        out = rebuild_doc(doc, cleaned)
        # 文档级字段（非条目列表）也要清洗
        out = scrub_value(out) if not isinstance(out, list) else out
        (dst_lib / jf.name).write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
        stats['files'] += 1
        stats['items'] += len(cleaned)
    # 画像与运行时（不含语料原文）：JSON 走清洗，脚本原样复制
    for sub in ('profile', 'runtime'):
        s = src / sub
        if not s.is_dir():
            continue
        for f in s.rglob('*'):
            if not f.is_file() or '__pycache__' in f.parts or f.suffix == '.pyc':
                continue
            rel = f.relative_to(s)
            target = dst / sub / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if f.suffix == '.json':
                try:
                    doc = json.loads(f.read_text(encoding='utf-8'))
                except (ValueError, OSError) as exc:
                    stats['skipped'].append(f'{src.name}/{sub}/{rel}: {exc}')
                    continue
                target.write_text(
                    json.dumps(scrub_value(doc), ensure_ascii=False, indent=1),
                    encoding='utf-8')
            elif f.suffix in ('.py', '.md', '.txt'):
                target.write_text(scrub_text(f.read_text(encoding='utf-8')), encoding='utf-8')
            else:
                shutil.copy2(f, target)
    # README / EXTRACTION_SPEC 等说明保留但做名字替换
    for md in src.glob('*.md'):
        (dst / md.name).write_text(scrub_text(md.read_text(encoding='utf-8')), encoding='utf-8')
    return True


def sanitize_config(src_cfg: Path, dst_cfg: Path, stats: dict):
    """教师配置：全量递归清洗（含嵌套别名列表），base_dir 指向包内。"""
    doc = json.loads(src_cfg.read_text(encoding='utf-8'))
    teachers = doc.get('teachers') or {}
    for tid, t in teachers.items():
        t['base_dir'] = f'teachers/{tid}'
    doc = scrub_value(doc)
    dst_cfg.parent.mkdir(parents=True, exist_ok=True)
    dst_cfg.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding='utf-8')
    stats['config'] = True


def verify(root: Path) -> int:
    """核验：无原话字段、无真名、无逐字稿目录。"""
    problems = []
    real_names = list(NAME_MAP)
    for jf in root.rglob('*.json'):
        text = jf.read_text(encoding='utf-8')
        for name in real_names:
            if name in text:
                problems.append(f'{jf.relative_to(root)}: 含真名 {name}')
        try:
            doc = json.loads(text)
        except ValueError:
            problems.append(f'{jf.relative_to(root)}: JSON 损坏')
            continue
        blob = json.dumps(doc, ensure_ascii=False)
        for key in ('"quote"', '"source_quote"', '"char_start"', '"line_start"', '"transcripts/'):
            if key in blob:
                problems.append(f'{jf.relative_to(root)}: 含原话/定位残留 {key}')
    for jf in root.rglob('*.md'):
        text = jf.read_text(encoding='utf-8')
        for name in real_names:
            if name in text:
                problems.append(f'{jf.relative_to(root)}: 含真名 {name}')
    for bad in DROP_DIRS:
        if (root / bad).exists():
            problems.append(f'{bad}/ 目录不应存在')
    if problems:
        print(f'核验失败：{len(problems)} 项')
        for p in problems[:25]:
            print('  ✗', p)
        return 1
    print(f'核验通过：{root}（无真名、无原话引用、无逐字稿）')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None, help='输出目录')
    ap.add_argument('--verify', default=None, help='核验已有目录')
    args = ap.parse_args(argv)
    if args.verify:
        return verify(Path(args.verify))

    cfg = json.loads((ROOT / 'backend/app/config/module_teachers.json').read_text(encoding='utf-8'))
    teachers = cfg.get('teachers') or {}
    out = Path(args.out or ROOT / 'release/teachers_refined')
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    stats = {'files': 0, 'items': 0, 'skipped': [], 'config': False}
    exported = []
    for tid, t in teachers.items():
        src = Path(t.get('base_dir', ''))
        if not src.is_absolute():
            src = ROOT / src
        if not src.is_dir():
            stats['skipped'].append(f'{tid}: 源目录不存在 {src}')
            continue
        if export_teacher(src, out / tid, stats):
            exported.append(tid)

    # 配置副本（不覆盖本机配置，只写发布版）
    sanitize_config(ROOT / 'backend/app/config/module_teachers.json',
                    out / 'module_teachers.json', stats)

    print(f'导出教师: {len(exported)} 个 -> {out}')
    print(f'JSON 文件: {stats["files"]} 个，条目: {stats["items"]}')
    for s in stats['skipped']:
        print('  ! 跳过:', s)
    return verify(out)


if __name__ == '__main__':
    sys.exit(main())
