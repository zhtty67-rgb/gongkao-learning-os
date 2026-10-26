import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def default_path():
    return Path(os.environ.get('GONGKAO_DB_PATH', ROOT / 'data' / 'gongkao.db'))


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()


class IncompatibleSchemaError(Exception):
    """Raised when an existing table column has an incompatible type definition."""


def _apply_migration_017(db: sqlite3.Connection) -> None:
    """Versioned migration 017: formalize knowledge_node_code and metadata_json on knowledge_nodes.

    Handles:
    - Fresh database (neither column exists yet): adds both with correct types & defaults.
    - Legacy database (both columns already exist): validates definitions and preserves data.
    - Partial database (only one column exists): adds the missing column and validates.
    - Incompatible column definitions: raises IncompatibleSchemaError, fails migration cleanly.
    - Foreign-key integrity: verified before recording migration success.
    - Writes (17, applied_at) to schema_migrations only upon verified success.
    """
    tbl = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_nodes'").fetchone()
    if not tbl:
        raise IncompatibleSchemaError("Table 'knowledge_nodes' does not exist; cannot apply migration 017")

    cols_info = {
        c[1]: {'type': (c[2] or '').upper(), 'notnull': c[3], 'dflt': c[4]}
        for c in db.execute('PRAGMA table_info(knowledge_nodes)').fetchall()
    }

    # 1. 检查或条件补齐 knowledge_node_code
    if 'knowledge_node_code' in cols_info:
        col_type = cols_info['knowledge_node_code']['type']
        if col_type and col_type not in ('TEXT', 'VARCHAR', 'CHAR', 'CLOB', ''):
            raise IncompatibleSchemaError(
                f"Existing column 'knowledge_node_code' has incompatible type: {col_type!r} (expected TEXT)"
            )
    else:
        db.execute('ALTER TABLE knowledge_nodes ADD COLUMN knowledge_node_code TEXT')

    # 2. 检查或条件补齐 metadata_json
    if 'metadata_json' in cols_info:
        col_type = cols_info['metadata_json']['type']
        if col_type and col_type not in ('TEXT', 'VARCHAR', 'CHAR', 'CLOB', ''):
            raise IncompatibleSchemaError(
                f"Existing column 'metadata_json' has incompatible type: {col_type!r} (expected TEXT)"
            )
    else:
        db.execute("ALTER TABLE knowledge_nodes ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")

    # 3. 校验最终列定义
    final_cols = {c[1]: {'type': (c[2] or '').upper()} for c in db.execute('PRAGMA table_info(knowledge_nodes)').fetchall()}
    if 'knowledge_node_code' not in final_cols or 'metadata_json' not in final_cols:
        raise IncompatibleSchemaError('Verification failed: columns missing after migration 017 application')

    # 4. 校验外键完整性
    fk_errors = db.execute('PRAGMA foreign_key_check').fetchall()
    if fk_errors:
        raise IncompatibleSchemaError(f'Foreign key integrity check failed after migration 017: {fk_errors}')

    # 5. 写入版本记录（仅在全部校验通过后写入）
    db.execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES (17, strftime('%Y-%m-%dT%H:%M:%fZ','now'))"
    )


def migrate(path, *, target_version: int | None = None):
    """Apply existing migrations; a cutoff is for isolated historical release rehearsals."""
    if target_version is not None and (type(target_version) is not int or target_version < 17):
        raise ValueError('target_version must be an integer >= 17')
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)')
        current_version = db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] or 0
        if target_version is not None and current_version > target_version:
            raise IncompatibleSchemaError('Historical migration cutoff cannot downgrade an existing database')
        for migration in sorted((ROOT / 'backend/migrations').glob('[0-9][0-9][0-9]_*.sql')):
            version = int(migration.name.split('_', 1)[0])
            if target_version is not None and version > target_version:
                break
            if db.execute('SELECT 1 FROM schema_migrations WHERE version=?', (version,)).fetchone() is None:
                if version == 17:
                    _apply_migration_017(db)
                elif version == 36:
                    # Legacy live DBs already have descriptions; fresh installs may
                    # have only the original knowledge-node columns plus migration 017.
                    cols = {r[1] for r in db.execute('PRAGMA table_info(knowledge_nodes)')}
                    if 'description' not in cols:
                        db.execute('ALTER TABLE knowledge_nodes ADD COLUMN description TEXT')
                    db.executescript(migration.read_text(encoding='utf-8'))
                else:
                    db.executescript(migration.read_text(encoding='utf-8'))
        cols = [c[1] for c in db.execute('PRAGMA table_info(questions)').fetchall()]
        if 'ai_explanation_json' not in cols:
            db.execute('ALTER TABLE questions ADD COLUMN ai_explanation_json TEXT')
        cols_un = [c[1] for c in db.execute('PRAGMA table_info(user_notes)').fetchall()]
        if cols_un and 'version' not in cols_un:
            db.execute('ALTER TABLE user_notes ADD COLUMN version INTEGER NOT NULL DEFAULT 1')
