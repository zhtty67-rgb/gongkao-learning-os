# -*- coding: utf-8 -*-
"""Effective-verdict helper for attempts.

Migration 028 adds non-destructive answer-key corrections to `attempts`
(`corrected_correct`, `correction_basis`, `answer_key_fingerprint`, `corrected_at`).
The historically judged `attempts.correct` column is never rewritten; statistics read
the effective verdict:

    COALESCE(attempts.corrected_correct, attempts.correct)

Uncorrected attempts keep their original judgment; corrected attempts use the verdict
under the current standard answer. Use `correct_expr` wherever a SQL query aggregates
`attempts.correct`, so error filtering, accuracy, mastery and projections share one
definition.
"""
from __future__ import annotations


REQUIRED_CORRECTION_COLUMNS = (
    "corrected_correct",
    "correction_basis",
    "answer_key_fingerprint",
    "corrected_at",
)


def has_correction_columns(db) -> bool:
    """Return True if attempts table exists and has all four correction columns."""
    try:
        cols = {r[1] for r in db.execute("PRAGMA table_info(attempts)").fetchall()}
        return all(c in cols for c in REQUIRED_CORRECTION_COLUMNS)
    except Exception:
        return False


def verify_migration_028_prerequisite(db) -> tuple[bool, str | None]:
    """Verify that migration 028 is applied and all correction columns exist.

    Database schema must be managed exclusively by explicit migrations in backend/migrations/.
    Repair scripts and tooling must never mutate table structure on the fly via ALTER TABLE.
    """
    try:
        has_mig = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if not has_mig:
            return (
                False,
                "schema_migrations 表不存在。请先运行 backend.app.db.migrate() 应用待执行迁移。",
            )
        has_028 = db.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 28"
        ).fetchone()
        if not has_028:
            return (
                False,
                "迁移 028 (backend/migrations/028_attempt_answer_corrections.sql) 尚未应用。"
                "根据已验证的发布顺序，必须先运行 backend.app.db.migrate() 应用待执行迁移，然后再执行修复引擎。",
            )
        cols = {r[1] for r in db.execute("PRAGMA table_info(attempts)").fetchall()}
        missing = [c for c in REQUIRED_CORRECTION_COLUMNS if c not in cols]
        if missing:
            return (
                False,
                f"attempts 表缺少纠错字段: {missing}。迁移 028 记录虽然存在，但表结构不完整，请复核数据库架构。",
            )
        return True, None
    except Exception as exc:
        return False, f"检查迁移 028 前置条件时出错: {exc}"


def correct_expr(db, alias: str = "a") -> str:
    """SQL expression for the effective verdict of `attempts` under `alias`."""
    if has_correction_columns(db):
        return f"COALESCE({alias}.corrected_correct, {alias}.correct)"
    return f"{alias}.correct"


def correction_note(original_correct, corrected_correct) -> str:
    """Short human-readable note distinguishing the historical judgment from the
    corrected verdict, for history/review responses."""

    def fmt(v):
        if v is None:
            return "未判定"
        return "正确" if int(v) == 1 else "错误"

    return f"标准答案已修正：当时判{fmt(original_correct)}，按修正后标准答案应为{fmt(corrected_correct)}"


def answer_key_fingerprint(question_id: str, standard_answer: str) -> str:
    """Stable short fingerprint of the standard answer a correction was computed against."""
    import hashlib

    return hashlib.sha256(f"{question_id}|{standard_answer}".encode("utf-8")).hexdigest()[:16]
