# -*- coding: utf-8 -*-
"""打包公考 Learning OS 发布包（脱敏）。

产物：release/package-<时间戳>/ 目录与同名 zip。
脱敏范围：
1. model_config.toml：清除全部 api_key；本机反代 base_url(127.0.0.1:8045) 置空。
2. 数据库：完整保留题库/知识树/教师资料等产品数据，清空全部个人学习记录
   （作答、复习、笔记、掌握度、导入工作数据等 31 张表），并 VACUUM。
3. 教师模型：module_teachers.json 的绝对路径改写为包内相对路径 teachers/，
   教师目录整体拷入包内。
4. 排除：.venv、node_modules、.next*、测试与修复产物、data/backups、日志等。
5. 自检：包内任何文本文件不得出现源 toml 中出现过的真实 api_key；
   包内库的个人表必须为空。

用法：.venv\\Scripts\\python.exe scripts/package_release.py [--no-zip]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = time.strftime('%Y%m%d-%H%M')
PACKAGE_DIR = ROOT / 'release' / f'package-{STAMP}'
ZIP_PATH = ROOT / 'release' / f'gongkao-learning-os-{STAMP}.zip'

# 打包时从 backend/app/config/module_teachers.json 读取教师目录清单
# 个人学习数据表（清空行，保留表结构）；不在清单内的表原样保留
PERSONAL_TABLES = [
    # 依赖顺序：先删子表
    'attempt_followups', 'attempts', 'session_question_selections',
    'session_question_sources', 'session_questions', 'sessions',
    'review_events', 'review_cards',
    'mastery_evidence', 'mastery_state',
    'exposure_logs', 'daily_plans',
    'error_skill_bindings', 'error_overlay', 'error_events',
    'exam_records', 'interactive_diagnoses',
    'adaptive_teaching_events', 'adaptive_teaching_sessions',
    'question_import_drafts', 'question_import_jobs',
    'shenlun_point_reports', 'shenlun_target_revisions', 'shenlun_guidance',
    'shenlun_teacher_followups', 'shenlun_teacher_diagnoses',
    'shenlun_assessments', 'shenlun_mastery_state', 'shenlun_sessions',
    # 2026-10 学习闭环新增（migration 048/049）：学习任务与教学对话均为个人数据
    'study_tasks', 'study_task_sets',
    'node_teaching_turns', 'node_teaching_sessions',
    'user_notes', 'user_review_preferences',
]

FRONTEND_EXCLUDE_DIRS = {
    'node_modules', 'test-results', 'test-results-adaptive-map', 'test-results-group',
    'test-results-teaching', 'playwright-report', 'pytest-of-86155',
}
FRONTEND_EXCLUDE_PREFIXES = ('.next',)
FRONTEND_EXCLUDE_FILES = {
    'next_server.log', 'prod-3000.log', 'tsconfig.tsbuildinfo', 'package-lock.json.bak',
    'playwright.config.ts', 'playwright.adaptive-map.config.ts', 'playwright.group.config.ts',
    'playwright.map.config.ts', 'playwright.mobile.config.ts', 'playwright.review.config.ts',
    'playwright.teaching.config.ts', 'playwright.tree-views.config.ts',
}
FRONTEND_TEST_DIRS = {'tests', 'tests-map', 'tests-review', 'tests-tree-views'}

BACKEND_EXCLUDE_DIRS = {'__pycache__', 'data'}
BACKEND_EXCLUDE_FILES = {'gongkao.db'}

DATA_KEEP = {'gongkao.db', 'assets'}  # data/ 下仅这两项进包


def log(msg: str) -> None:
    print(f'[package] {msg}', flush=True)


def sanitize_model_config() -> str:
    """读取源 model_config.toml，清除 api_key 与本机反代 base_url。"""
    src = ROOT / 'model_config.toml'
    text = src.read_text(encoding='utf-8')
    key_values = re.findall(r'api_key\s*=\s*"([^"]+)"', text)
    text = re.sub(r'api_key\s*=\s*"[^"]*"', 'api_key = ""', text)
    text = re.sub(r'base_url\s*=\s*"http://127\.0\.0\.1:8045[^"]*"', 'base_url = ""', text)
    assert 'api_key = ""' in text and '127.0.0.1:8045' not in text
    PACKAGE_DIR.joinpath('model_config.toml').write_text(text, encoding='utf-8')
    return '\n'.join(v for v in key_values if v)


def sanitize_database(dest: Path) -> None:
    """复制主库（合并 WAL），清空个人表，再 VACUUM INTO 压缩后原子替换。

    Windows 上部分目录对 sqlite 就地 VACUUM 会报 unable to open database file，
    因此统一走 VACUUM INTO 生成压缩副本后替换。
    """
    src = ROOT / 'data' / 'gongkao.db'
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(src)
    dst_conn = sqlite3.connect(dest)
    src_conn.backup(dst_conn)
    src_conn.close()

    tables = {row[0] for row in dst_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing = [t for t in PERSONAL_TABLES if t not in tables]
    if missing:
        raise RuntimeError(f'库中缺少预期的个人数据表: {missing}')
    before = {}
    for table in PERSONAL_TABLES:
        before[table] = dst_conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        dst_conn.execute(f'DELETE FROM "{table}"')
    dst_conn.commit()
    product_counts = {
        t: dst_conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        for t in ('questions', 'knowledge_nodes', 'question_skill_bindings',
                  'shenlun_materials', 'learning_skills')
    }
    dst_conn.close()
    compacted = dest.with_suffix('.db.compact')
    if compacted.exists():
        compacted.unlink()
    vacuum_src = sqlite3.connect(dest)
    try:
        vacuum_src.execute(f"VACUUM INTO '{compacted.as_posix()}'")
    finally:
        vacuum_src.close()
    dest.unlink()
    compacted.replace(dest)
    cleared_rows = sum(before.values())
    log(f'数据库脱敏完成：清空 {len(PERSONAL_TABLES)} 张个人表共 {cleared_rows} 行；'
        f'压缩后 {dest.stat().st_size / 1024 / 1024:.0f} MB；'
        f'产品数据保留 {product_counts}')


def copy_teachers() -> list[str]:
    """拷贝启用中的教师模型目录入包，并把配置改写为包内相对路径。"""
    config_path = ROOT / 'backend' / 'app' / 'config' / 'module_teachers.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    teachers = config.get('teachers', {})
    copied: dict[str, str] = {}
    for tid, tcfg in teachers.items():
        if not tcfg.get('enabled', True):
            continue
        raw = tcfg.get('base_dir')
        if not raw:
            continue
        src = Path(raw)
        if not src.is_absolute():
            src = ROOT / raw
        if not src.is_dir():
            raise RuntimeError(f'教师目录不存在: {tid} -> {src}')
        rel = f'teachers/{src.name}'
        dest = PACKAGE_DIR / rel
        if src.name not in copied:
            shutil.copytree(src, dest,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache'))
            copied[src.name] = rel
            log(f'教师目录已内置: {src.name} ({tid})')
        tcfg['base_dir'] = rel
    out = PACKAGE_DIR / 'backend' / 'app' / 'config' / 'module_teachers.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return sorted(copied)


def copytree_filtered(src: Path, dest: Path, exclude_dirs: set[str],
                      exclude_prefixes: tuple = (), exclude_files: set[str] = set(),
                      exclude_suffixes: tuple = ()) -> None:
    def ignore(_dir: str, names: list[str]) -> list[str]:
        skipped = []
        for name in names:
            if name in exclude_dirs or name in exclude_files:
                skipped.append(name)
            elif any(name.startswith(p) for p in exclude_prefixes):
                skipped.append(name)
            elif any(name.endswith(s) for s in exclude_suffixes):
                skipped.append(name)
        return skipped
    shutil.copytree(src, dest, ignore=ignore)


def copy_tree() -> None:
    # backend：代码 + 迁移 + 依赖清单（.venv 与副本库不进包）
    copytree_filtered(ROOT / 'backend', PACKAGE_DIR / 'backend',
                      BACKEND_EXCLUDE_DIRS, ('__pycache__',),
                      BACKEND_EXCLUDE_FILES, ('.pyc',))

    # frontend：源码 + 构建 + 依赖配置（node_modules 与历史构建不进包）
    fe = ROOT / 'frontend'
    copytree_filtered(fe, PACKAGE_DIR / 'frontend',
                      FRONTEND_EXCLUDE_DIRS | FRONTEND_TEST_DIRS,
                      FRONTEND_EXCLUDE_PREFIXES, FRONTEND_EXCLUDE_FILES, ('.pyc',))
    # public/assets 是 2026-09 的陈旧副本，会遮蔽后端 data/assets（Next rewrite
    # 在 public 命中后不再转发）。包内统一由后端静态挂载提供题图。
    stale_public_assets = PACKAGE_DIR / 'frontend' / 'public' / 'assets'
    if stale_public_assets.exists():
        shutil.rmtree(stale_public_assets)
        log('已排除 frontend/public/assets 陈旧题图副本（统一由后端 data/assets 提供）')

    # data：脱敏后的主库 + 题图资产
    dest_data = PACKAGE_DIR / 'data'
    dest_data.mkdir(parents=True, exist_ok=True)
    sanitize_database(dest_data / 'gongkao.db')
    log('拷贝题图资产 data/assets（约300MB，稍候）…')
    copytree_filtered(ROOT / 'data' / 'assets', dest_data / 'assets', set(), (), set(), ())

    # scripts：仅启动脚本
    for name in ('start-backend.ps1', 'start-frontend.ps1'):
        shutil.copy2(ROOT / 'scripts' / name, PACKAGE_DIR / 'scripts' / name)

    # 2026-10 新增：DSH 插件壳、通用 MCP 片段、集成文档与独立启动器
    for rel in ('dsh-plugin', 'mcp', 'docs'):
        src_dir = ROOT / rel
        if src_dir.is_dir():
            copytree_filtered(src_dir, PACKAGE_DIR / rel, {'__pycache__'}, (),
                              set(), ('.pyc',))
    for name in ('gongkao_mcp_server.py', 'sync_lingshu_memory.py',
                 'compat_mcp_client_check.py'):
        if (ROOT / 'scripts' / name).is_file():
            shutil.copy2(ROOT / 'scripts' / name, PACKAGE_DIR / 'scripts' / name)
    if (ROOT / 'mcp').is_dir():
        log('已包含 DSH 插件壳 / MCP 片段 / 集成文档')

    # 根文件
    for name in ('.env.example', 'README.md'):
        if (ROOT / name).is_file():
            shutil.copy2(ROOT / name, PACKAGE_DIR / name)


LAUNCHER_BAT = r"""@echo off
setlocal EnableDelayedExpansion
title Gongkao Learning OS

set "PROJECT=%~dp0"
set "PROJECT=%PROJECT:~0,-1%"
set "BACKEND_SCRIPT=%PROJECT%\scripts\start-backend.ps1"
set "FRONTEND_SCRIPT=%PROJECT%\scripts\start-frontend.ps1"

if not exist "%PROJECT%\.venv\Scripts\python.exe" goto need_install
if not exist "%PROJECT%\frontend\node_modules" goto need_install
goto ready

:need_install
echo [!] First run: please double-click "1-Install.bat" first.
pause
exit /b 1

:ready
rem ---------- backend :8000 ----------
powershell.exe -NoLogo -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if errorlevel 1 (
    echo [1/2] Starting backend FastAPI :8000 ...
    start /min "Gongkao Backend" powershell.exe -NoLogo -NoExit -ExecutionPolicy Bypass -File "%BACKEND_SCRIPT%"
    timeout /t 3 >nul
) else (
    echo [1/2] Backend already running.
)

rem ---------- frontend :3000 ----------
powershell.exe -NoLogo -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if errorlevel 1 (
    echo [2/2] Starting frontend Next.js :3000 ...
    start /min "Gongkao Frontend" powershell.exe -NoLogo -NoExit -ExecutionPolicy Bypass -File "%FRONTEND_SCRIPT%"
    timeout /t 4 >nul
) else (
    echo [2/2] Frontend already running.
)

start "" http://127.0.0.1:3000
echo.
echo Gongkao Learning OS: http://127.0.0.1:3000  (settings page: /settings)
timeout /t 8 >nul
"""

INSTALL_BAT = r"""@echo off
setlocal EnableDelayedExpansion
title Gongkao Learning OS - Install
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [!] Python not found. Please install Python 3.11+ first.
    echo     https://www.python.org/downloads/
    pause
    exit /b 1
)
where npm >nul 2>&1
if errorlevel 1 (
    echo [!] Node.js/npm not found. Please install Node.js 20+ first.
    echo     https://nodejs.org/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating Python venv ...
    python -m venv .venv
)
echo [2/3] Installing backend dependencies (requirements.lock.txt) ...
".venv\Scripts\python.exe" -m pip install -r backend\requirements.lock.txt -q
if errorlevel 1 (
    echo [!] Backend dependency install failed.
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo [3/3] Installing frontend dependencies (npm install) ...
    cd frontend
    call npm install
    if errorlevel 1 ( cd .. & pause & exit /b 1 )
    echo      Building frontend (npm run build) ...
    call npm run build
    cd ..
) else (
    echo [3/3] Frontend already installed.
)

echo.
echo Done! Double-click "2-Start.bat" to launch.
echo Configure your AI API key on the settings page: http://127.0.0.1:3000/settings
pause
"""


def write_launchers_and_guide(teacher_dirs: list[str]) -> None:
    (PACKAGE_DIR / '2-Start.bat').write_text(LAUNCHER_BAT, encoding='utf-8')
    (PACKAGE_DIR / '1-Install.bat').write_text(INSTALL_BAT, encoding='utf-8')

    teacher_list = '\n'.join(f'- {name}' for name in teacher_dirs)
    guide = f"""# 公考 Learning OS · 部署指南（脱敏发布包）

本包为脱敏发布版：**不包含任何 API 密钥与个人学习记录**。题库、知识树、
名师模型等教学资产完整保留。首次部署请按以下步骤操作。

## 环境要求

- Windows 10/11
- Python 3.11 及以上（开发验证版本 3.14）
- Node.js 20 及以上（含 npm）
- 无需 Docker；知识检索（Knowledge Hub）为可选组件，见下文“知识检索”。

## 部署步骤

1. 双击 `1-Install.bat`：创建 Python 虚拟环境、安装后端依赖、
   安装并构建前端（首次约几分钟）。
2. 双击 `2-Start.bat`：启动后端 (:8000) 与前端 (:3000)，并自动打开浏览器。
3. 打开 **系统设置** 页（导航栏最右侧“设置”，或直接访问
   <http://127.0.0.1:3000/settings>）：
   - 在 AI 模型网关下填入你的 OpenAI 兼容服务地址（base_url）、
     API 密钥与模型名，点击“测试连接”确认可用后“保存全部设置”。
   - 保存立即生效（热重载），并持久化到本机 `data/settings.json`，
     重启后依然生效；该文件不会随本包分发，属于你的私密配置。
4. 开始使用：<http://127.0.0.1:3000>

## 配置优先级说明

系统设置页保存的 `data/settings.json` > `model_config.toml` >
环境变量（AI_API_KEY / AI_BASE_URL 等）。未保存任何设置时行为与原版一致。

## 知识检索（可选）

教学讲解的证据检索默认连接本机 Knowledge Hub 服务
（KNOWLEDGE_HUB_BASE_URL，默认 127.0.0.1:8200）。本包不含 Hub；未部署时
相关讲解自动降级（诚实提示证据不可用），AI 讲题与教师模型不受影响。
如需启用，参照 universal-knowledge-hub 项目单独部署，或在系统设置页把
provider 切为 `disabled` 关闭检索提示。

## 本包内容

- `backend/` FastAPI 服务（含申论教师知识库，随包内置）
- `frontend/` Next.js 前端（含系统设置页）
- `data/gongkao.db` 题库主库（已清除个人学习数据）
- `data/assets/` 题目与解析配图
- `teachers/` 行测名师模型运行时（{', '.join(teacher_dirs)}）
- `model_config.toml` 模型策略骨架（api_key 已清空，请用设置页配置）
- `1-Install.bat` / `2-Start.bat` 一键安装与启动

## 数据库说明

`data/gongkao.db` 已清空 {len(PERSONAL_TABLES)} 张个人数据表
（作答、复习调度、笔记、掌握度、导入工作数据等），题目、知识树、
技能绑定与申论资料完整保留。应用启动时会自动执行 schema 迁移。

## 已知脱敏项清单

1. 所有模型 `api_key` 已从 `model_config.toml` 移除；
   本机反向代理地址（127.0.0.1:8045）已置空。
2. 个人学习数据全部清空（见上）。
3. 开发过程产物（测试、修复脚本、日志、备份库、构建缓存）未包含。
"""
    (PACKAGE_DIR / 'README-部署指南.md').write_text(guide, encoding='utf-8')


SECRET_SCAN_SKIP_SUFFIX = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.db', '.zip',
                           '.ico', '.woff', '.woff2', '.ttf')


def verify_no_secrets(real_keys: list[str]) -> int:
    """扫描包内全部文本文件：真实密钥必须零命中；通用 sk- 形态密钥一并拦截。"""
    generic = re.compile(r'sk-[A-Za-z0-9_-]{20,}')
    known = set(real_keys)
    hits: list[str] = []
    generic_hits: list[str] = []
    scanned = 0
    for path in PACKAGE_DIR.rglob('*'):
        if not path.is_file() or path.suffix.lower() in SECRET_SCAN_SKIP_SUFFIX:
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, PermissionError):
            continue
        scanned += 1
        for key in known:
            if key in text:
                hits.append(str(path))
        for match in generic.finditer(text):
            if match.group(0) not in known:
                generic_hits.append(f'{path}: {match.group(0)[:12]}...')
    if hits:
        raise RuntimeError(f'发现密钥泄漏！以下文件包含真实 api_key: {sorted(set(hits))}')
    if generic_hits:
        raise RuntimeError(f'发现疑似密钥（sk-…）残留: {sorted(set(generic_hits))[:20]}')
    log(f'密钥泄漏扫描通过（{scanned} 个文本文件 × {len(real_keys)} 个已知密钥 + 通用 sk- 形态扫描）')
    return scanned


def verify_personal_tables_empty() -> None:
    conn = sqlite3.connect(PACKAGE_DIR / 'data' / 'gongkao.db')
    try:
        for table in PERSONAL_TABLES:
            count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if count:
                raise RuntimeError(f'个人表未清空: {table} = {count}')
    finally:
        conn.close()
    log('个人数据表清空校验通过')


def make_zip() -> None:
    log(f'压缩 {ZIP_PATH.name} …')
    with zipfile.ZipFile(ZIP_PATH, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(PACKAGE_DIR.rglob('*')):
            if path.is_file():
                zf.write(path, path.relative_to(PACKAGE_DIR.parent))
    size_mb = ZIP_PATH.stat().st_size / 1024 / 1024
    log(f'zip 完成：{ZIP_PATH}（{size_mb:.0f} MB）')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-zip', action='store_true', help='只生成目录，不压缩')
    args = parser.parse_args()

    if PACKAGE_DIR.exists():
        shutil.rmtree(PACKAGE_DIR)
    PACKAGE_DIR.mkdir(parents=True)
    (PACKAGE_DIR / 'scripts').mkdir(parents=True, exist_ok=True)

    log(f'输出目录: {PACKAGE_DIR}')
    real_keys = []
    if (ROOT / 'model_config.toml').is_file():
        real_keys = [k for k in sanitize_model_config().splitlines() if k.strip()]
        log(f'model_config.toml 已脱敏（清除 {len(real_keys)} 个密钥值）')
    copy_tree()
    teacher_dirs = copy_teachers()
    write_launchers_and_guide(teacher_dirs)
    verify_personal_tables_empty()
    verify_no_secrets(real_keys)

    if not args.no_zip:
        make_zip()
    log('打包完成')
    return 0


if __name__ == '__main__':
    sys.exit(main())
