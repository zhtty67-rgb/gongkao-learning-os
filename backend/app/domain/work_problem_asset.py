"""
backend/app/domain/work_problem_asset.py

Provides structured, curated knowledge assets for Engineering Problems (工程问题).
Read-only, persistent, and grounded in official curriculum without runtime hallucination.
"""

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
ASSET_PATH = ROOT / "data" / "knowledge_assets" / "work_problem_knowledge_asset.json"

_CACHED_ASSET = None


def get_work_problem_asset() -> dict[str, Any]:
    """Retrieve the parsed engineering problem knowledge asset."""
    global _CACHED_ASSET
    if _CACHED_ASSET is None:
        target_path = ASSET_PATH
        if not target_path.exists():
            alt_path = ROOT / "docs" / "audits" / "work_problem_knowledge_asset.json"
            if alt_path.exists():
                target_path = alt_path
            else:
                raise FileNotFoundError(f"工程问题知识资产文件不存在: {ASSET_PATH}")
        _CACHED_ASSET = json.loads(target_path.read_text(encoding="utf-8"))
    return _CACHED_ASSET


def format_work_asset_for_prompt() -> str:
    """Format engineering knowledge assets as concrete prompt reference for Assessor/Tutor."""
    asset = get_work_problem_asset()
    lines = [
        "【工程问题专业知识资产（已核验基准）】",
        f"核心考点：{asset['name']} (Skill: {asset['skill_id']})",
        "1. 细考点与解题标准步骤：",
    ]
    for sub in asset.get("sub_skills", []):
        lines.append(f"  - [{sub['code']}] {sub['name']}: {sub['preconditions']}")
        for step in sub.get("standard_steps", []):
            lines.append(f"    * {step}")

    lines.append("2. 常见误区与辨别线索：")
    for m in asset.get("common_misconceptions", []):
        lines.append(f"  - [{m['code']}] {m['label']}: {m['description']}")
        lines.append(f"    * 针对性指导: {m['remedy']}")

    return "\n".join(lines)


def get_misconception_by_code(code: str) -> dict[str, Any] | None:
    """Get specific misconception details by code."""
    asset = get_work_problem_asset()
    for m in asset.get("common_misconceptions", []):
        if m["code"] == code:
            return m
    return None
