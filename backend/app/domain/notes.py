# -*- coding: utf-8 -*-
"""
backend/app/domain/notes.py

Domain service for User Notes & Reflections (我的笔记／感悟).
Supports:
  1. Question-level reflections (本题心得)
  2. Knowledge tree node notes (考点笔记)
  3. Review dialogue clippings (从复盘中收藏)
  4. Optimistic concurrency conflict protection (versioning)
  5. Safe tri-state field updates: preserves metadata/provenance on content edits,
     allows explicit clearing of title/knowledge_node, and merges metadata.
  6. Unified search and listing across modules (including non-duplicating Shenlun synthesis).
  7. Safe boundaries: purely user-owned, never overwrites official explanations,
     never alters correctness/mastery/review schedules.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

logger = logging.getLogger(__name__)

# Sentinel object to differentiate between 'field omitted' vs 'explicitly set to None/clear'
_UNSET = object()


class NoteVersionConflictError(Exception):
    """Raised when an update specifies an expected_version that does not match the database."""
    def __init__(self, note_id: str, expected_version: int, current_version: int, current_note: Dict[str, Any]):
        super().__init__(f"笔记 {note_id} 发生版本冲突：期望版本 {expected_version}，当前版本 {current_version}。已被其他页面更新。")
        self.note_id = note_id
        self.expected_version = expected_version
        self.current_version = current_version
        self.current_note = current_note


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_or_update_note(
    db: Any,
    user_id: str = "default_user",
    note_id: Optional[str] = None,
    expected_version: Optional[int] = None,
    note_type: str = "question",
    content: Optional[str] = None,
    title: Any = _UNSET,
    question_id: Optional[str] = None,
    attempt_id: Optional[str] = None,
    knowledge_node_id: Any = _UNSET,
    knowledge_node_code: Any = _UNSET,
    module: Any = _UNSET,
    source_type: str = "manual",
    source_message_id: Optional[str] = None,
    source_quote: Optional[str] = None,
    shenlun_session_id: Optional[str] = None,
    shenlun_dimension: Optional[str] = None,
    metadata: Any = _UNSET,
) -> Dict[str, Any]:
    """
    Create or update a personal user note with concurrency version protection.
    Tri-state semantics:
      - Field omitted (_UNSET): keep existing value in database untouched.
      - Field set to None or empty: explicit clear (e.g. title=None clears title).
      - Field set to new value: update field.
    """
    now = now_iso()

    # =========================================================================
    # Case 1: UPDATE existing note
    # =========================================================================
    if note_id:
        existing = db.execute("SELECT * FROM user_notes WHERE id=? AND user_id=?", (note_id, user_id)).fetchone()
        if not existing:
            raise ValueError(f"Note {note_id} not found")

        current_ver = int(existing["version"]) if "version" in existing.keys() and existing["version"] is not None else 1

        # 1. Version conflict check
        if expected_version is not None and expected_version != current_ver:
            current_note_data = get_note_by_id(db, note_id, user_id=user_id)
            raise NoteVersionConflictError(
                note_id=note_id,
                expected_version=expected_version,
                current_version=current_ver,
                current_note=current_note_data,
            )

        # 2. Content update
        if content is not None:
            cleaned_content = content.strip()
            if not cleaned_content:
                raise ValueError("笔记内容不能为空")
        else:
            cleaned_content = existing["content"]

        # 3. Title update (Tri-state)
        if title is _UNSET:
            new_title = existing["title"]
        elif title is None or (isinstance(title, str) and not title.strip()):
            new_title = None
        else:
            new_title = str(title).strip()

        # 4. Knowledge node update (Tri-state)
        if knowledge_node_id is _UNSET:
            new_kn_id = existing["knowledge_node_id"]
            new_kn_code = existing["knowledge_node_code"]
        elif knowledge_node_id is None or knowledge_node_id in ("", "CLEAR"):
            new_kn_id = None
            new_kn_code = None
        else:
            new_kn_id = str(knowledge_node_id)
            if knowledge_node_code is not _UNSET and knowledge_node_code:
                new_kn_code = str(knowledge_node_code)
            else:
                kn_row = db.execute("SELECT knowledge_node_code FROM knowledge_nodes WHERE id=?", (new_kn_id,)).fetchone()
                new_kn_code = kn_row["knowledge_node_code"] if kn_row else existing["knowledge_node_code"]

        # 5. Module update (Tri-state)
        if module is _UNSET:
            new_module = existing["module"]
        elif module is None:
            new_module = None
        else:
            new_module = str(module)

        # 6. Metadata merge (Never blindly clear previous source metadata)
        try:
            existing_meta = json.loads(existing["metadata_json"] or "{}")
        except Exception:
            existing_meta = {}

        if metadata is _UNSET or metadata is None:
            new_meta = existing_meta
        elif isinstance(metadata, dict):
            existing_meta.update(metadata)
            new_meta = existing_meta
        else:
            new_meta = existing_meta

        new_metadata_json = json.dumps(new_meta, ensure_ascii=False)

        # 7. Atomic update with version increment
        if expected_version is not None:
            cur = db.execute("""
                UPDATE user_notes
                SET content = ?,
                    title = ?,
                    knowledge_node_id = ?,
                    knowledge_node_code = ?,
                    module = ?,
                    metadata_json = ?,
                    version = version + 1,
                    updated_at = ?
                WHERE id = ? AND user_id = ? AND version = ?
            """, (
                cleaned_content,
                new_title,
                new_kn_id,
                new_kn_code,
                new_module,
                new_metadata_json,
                now,
                note_id,
                user_id,
                current_ver,
            ))
        else:
            cur = db.execute("""
                UPDATE user_notes
                SET content = ?,
                    title = ?,
                    knowledge_node_id = ?,
                    knowledge_node_code = ?,
                    module = ?,
                    metadata_json = ?,
                    version = version + 1,
                    updated_at = ?
                WHERE id = ? AND user_id = ?
            """, (
                cleaned_content,
                new_title,
                new_kn_id,
                new_kn_code,
                new_module,
                new_metadata_json,
                now,
                note_id,
                user_id,
            ))

        if cur.rowcount == 0:
            current_note_data = get_note_by_id(db, note_id, user_id=user_id)
            raise NoteVersionConflictError(
                note_id=note_id,
                expected_version=expected_version or current_ver,
                current_version=current_note_data.get("version", current_ver + 1),
                current_note=current_note_data,
            )

        db.commit()
        return get_note_by_id(db, note_id, user_id=user_id)

    # =========================================================================
    # Case 2: CREATE new note
    # =========================================================================
    if content is None or not content.strip():
        raise ValueError("笔记内容不能为空")
    cleaned_content = content.strip()

    # 1. Infer module and knowledge info if question_id is provided
    inferred_module = module if module is not _UNSET and module else None
    inferred_kn_id = knowledge_node_id if knowledge_node_id is not _UNSET and knowledge_node_id else None
    inferred_kn_code = knowledge_node_code if knowledge_node_code is not _UNSET and knowledge_node_code else None

    if question_id:
        q_row = db.execute("SELECT module FROM questions WHERE id=?", (question_id,)).fetchone()
        if q_row and not inferred_module:
            inferred_module = q_row["module"]

        if not inferred_kn_id and not inferred_kn_code:
            b_row = db.execute("""
                SELECT learning_skill_id, knowledge_node_code
                FROM question_skill_bindings
                WHERE question_id = ? AND role = 'primary'
                LIMIT 1
            """, (question_id,)).fetchone()
            if b_row:
                inferred_kn_code = b_row["knowledge_node_code"]
                clauses = ['id = ?', 'knowledge_node_code = ?']
                params = [b_row['learning_skill_id'], b_row['knowledge_node_code']]
                if 'code' in {r[1] for r in db.execute('PRAGMA table_info(knowledge_nodes)')}:
                    clauses.append('code = ?')
                    params.append(b_row['learning_skill_id'])
                kn_row = db.execute('SELECT id FROM knowledge_nodes WHERE ' + ' OR '.join(clauses), params).fetchone()
                if kn_row:
                    inferred_kn_id = kn_row["id"]

    # 2. Idempotent deduplication check for dialogue clippings
    if source_type in ("review_ai_message", "review_user_message") and attempt_id and source_message_id:
        existing = db.execute("""
            SELECT id FROM user_notes
            WHERE user_id = ? AND attempt_id = ? AND source_message_id = ?
            LIMIT 1
        """, (user_id, attempt_id, source_message_id)).fetchone()
        if existing:
            return get_note_by_id(db, existing["id"], user_id=user_id)

    init_title = title if title is not _UNSET and title else None
    init_meta = metadata if metadata is not _UNSET and isinstance(metadata, dict) else {}
    metadata_json = json.dumps(init_meta, ensure_ascii=False)

    new_id = f"note_{uuid.uuid4().hex[:12]}"
    db.execute("""
        INSERT INTO user_notes (
            id, user_id, note_type, content, title,
            question_id, attempt_id, knowledge_node_id, knowledge_node_code,
            module, source_type, source_message_id, source_quote,
            shenlun_session_id, shenlun_dimension, version, metadata_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
    """, (
        new_id,
        user_id,
        note_type,
        cleaned_content,
        init_title,
        question_id,
        attempt_id,
        inferred_kn_id,
        inferred_kn_code,
        inferred_module,
        source_type,
        source_message_id,
        source_quote,
        shenlun_session_id,
        shenlun_dimension,
        metadata_json,
        now,
        now,
    ))
    db.commit()
    return get_note_by_id(db, new_id, user_id=user_id)


def get_note_by_id(db: Any, note_id: str, user_id: str = "default_user") -> Dict[str, Any]:
    """Retrieve a single note with linked question, knowledge, and version details."""
    row = db.execute("""
        SELECT n.*,
               q.stem AS question_stem,
               q.answer AS question_answer,
               kn.name AS node_name
        FROM user_notes n
        LEFT JOIN questions q ON q.id = n.question_id
        LEFT JOIN knowledge_nodes kn ON kn.id = n.knowledge_node_id
        WHERE n.id = ? AND n.user_id = ?
    """, (note_id, user_id)).fetchone()

    if not row:
        raise ValueError(f"Note {note_id} not found")

    item = dict(row)
    item.setdefault("version", 1)
    try:
        item["metadata"] = json.loads(item.get("metadata_json") or "{}")
    except Exception:
        item["metadata"] = {}
    return item


def delete_note(db: Any, note_id: str, user_id: str = "default_user") -> bool:
    """Delete a user note cleanly."""
    cur = db.execute("DELETE FROM user_notes WHERE id=? AND user_id=?", (note_id, user_id))
    db.commit()
    return cur.rowcount > 0


def list_user_notes(
    db: Any,
    user_id: str = "default_user",
    question_id: Optional[str] = None,
    attempt_id: Optional[str] = None,
    knowledge_node_id: Optional[str] = None,
    knowledge_node_code: Optional[str] = None,
    module: Optional[str] = None,
    note_type: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    include_shenlun: bool = True,
) -> Dict[str, Any]:
    """
    Search and list notes across modules with optional filters.
    Includes optimistic concurrency version field in all note items.
    """
    where_clauses = ["n.user_id = ?"]
    params: List[Any] = [user_id]

    if question_id:
        where_clauses.append("n.question_id = ?")
        params.append(question_id)

    if attempt_id:
        where_clauses.append("n.attempt_id = ?")
        params.append(attempt_id)

    if knowledge_node_id:
        where_clauses.append("(n.knowledge_node_id = ? OR n.knowledge_node_code = ?)")
        params.append(knowledge_node_id)
        params.append(knowledge_node_id)
    elif knowledge_node_code:
        where_clauses.append("n.knowledge_node_code = ?")
        params.append(knowledge_node_code)

    if module:
        where_clauses.append("n.module = ?")
        params.append(module)

    if note_type:
        where_clauses.append("n.note_type = ?")
        params.append(note_type)

    if query and query.strip():
        q_clean = f"%{query.strip()}%"
        where_clauses.append("(n.content LIKE ? OR n.title LIKE ? OR n.source_quote LIKE ?)")
        params.extend([q_clean, q_clean, q_clean])

    where_sql = " AND ".join(where_clauses)

    count_sql = f"SELECT count(*) FROM user_notes n WHERE {where_sql}"
    total_count = db.execute(count_sql, params).fetchone()[0]

    select_sql = f"""
        SELECT n.*,
               q.stem AS question_stem,
               q.answer AS question_answer,
               kn.name AS node_name
        FROM user_notes n
        LEFT JOIN questions q ON q.id = n.question_id
        LEFT JOIN knowledge_nodes kn ON kn.id = n.knowledge_node_id
        WHERE {where_sql}
        ORDER BY n.updated_at DESC
        LIMIT ? OFFSET ?
    """
    items = []
    for r in db.execute(select_sql, params + [limit, offset]).fetchall():
        d = dict(r)
        d.setdefault("version", 1)
        try:
            d["metadata"] = json.loads(d.get("metadata_json") or "{}")
        except Exception:
            d["metadata"] = {}
        items.append(d)

    # Incorporate Shenlun session notes if Shenlun is included and no conflicting question_id filter
    shenlun_notes = []
    if include_shenlun and not question_id and not attempt_id and (not module or module == "申论"):
        try:
            s_rows = db.execute("""
                SELECT s.id, s.material_id, s.status, s.notes_json, s.started_at, m.title AS material_title
                FROM shenlun_sessions s
                LEFT JOIN shenlun_materials m ON m.id = s.material_id
                ORDER BY s.started_at DESC
            """).fetchall()

            dim_names = {
                "problem": "问题梳理",
                "cause": "原因分析",
                "measure": "对策措施",
                "example": "典型案例/论据",
            }

            for s in s_rows:
                s_notes = json.loads(s["notes_json"] or "{}")
                for dim_key, dim_val in s_notes.items():
                    if dim_val and isinstance(dim_val, str) and dim_val.strip():
                        if query and query.strip().lower() not in dim_val.lower() and query.strip().lower() not in (s["material_title"] or "").lower():
                            continue
                        shenlun_notes.append({
                            "id": f"sl_note_{s['id']}_{dim_key}",
                            "user_id": user_id,
                            "note_type": "shenlun_summary",
                            "content": dim_val.strip(),
                            "title": f"申论训练梳理 · {dim_names.get(dim_key, dim_key)}",
                            "question_id": None,
                            "attempt_id": None,
                            "knowledge_node_id": None,
                            "knowledge_node_code": f"gongkao.shenlun.{dim_key}",
                            "module": "申论",
                            "source_type": "shenlun_dimension",
                            "source_message_id": s["id"],
                            "source_quote": s["material_title"] or "申论给定资料",
                            "shenlun_session_id": s["id"],
                            "shenlun_dimension": dim_key,
                            "version": 1,
                            "metadata": {"material_id": s["material_id"]},
                            "created_at": s["started_at"],
                            "updated_at": s["started_at"],
                            "is_shenlun_live": True,
                        })
        except Exception as exc:
            logger.warning("Failed to aggregate shenlun session notes: %s", exc)

    return {
        "items": items,
        "total": total_count + len(shenlun_notes),
        "shenlun_notes": shenlun_notes,
    }


def get_notes_for_review_prompt(db: Any, question_id: str, user_id: str = "default_user") -> str:
    """
    Safely format user notes for downstream review prompt blocks.
    Strictly marked as '【考生历史个人感悟/心得（非教材客观依据）】'.
    """
    rows = db.execute("""
        SELECT content, title, source_type, created_at
        FROM user_notes
        WHERE question_id = ? AND user_id = ?
        ORDER BY updated_at DESC
        LIMIT 2
    """, (question_id, user_id)).fetchall()

    if not rows:
        return ""

    blocks = ["【考生个人既往心得/备忘（仅供了解考生思路，不得当作客观真理）】："]
    for r in rows:
        title_str = f"《{r['title']}》" if r["title"] else "心得"
        blocks.append(f"• [{title_str}]：{r['content']}")
    return "\n".join(blocks)
