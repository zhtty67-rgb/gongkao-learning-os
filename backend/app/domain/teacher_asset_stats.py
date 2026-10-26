"""按当前知识库和加载门槛计算资产数量；历史审计不参与当前统计。"""
import json
from pathlib import Path


def teacher_asset_stats(library_dir: Path, *, shenlun: bool = False,
                        transcript_cases: bool = False) -> dict:
    result = {"count_basis": "current_library_loading_rules", "assets": {}, "errors": []}
    for kind in ("policies", "question_cases", "critique_cases"):
        path = library_dir / f"{kind}_full.json"
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("资产必须为对象数组")
        except (OSError, ValueError) as exc:
            result["errors"].append({"file": str(path), "error": type(exc).__name__})
            result["assets"][kind] = {"total": None, "active": None,
                                     "quarantined": None, "unverified": None}
            continue
        quarantined = sum(row.get("verification_status") == "quarantined" for row in rows)
        usable = [row for row in rows if row.get("verification_status") != "quarantined"]
        if shenlun:
            active = len(usable)
        elif kind == "policies":
            active = len(usable)
        elif kind == "question_cases":
            required = "transcript_excerpt_verified" if transcript_cases else "source_text_verified"
            active = sum(row.get("verification_status") == required for row in usable)
        else:
            active = 0  # 行测纠错记录当前不用于学生诊断。
        result["assets"][kind] = {"total": len(rows), "active": active,
                                 "quarantined": quarantined,
                                 "unverified": len(rows) - quarantined - active}
    return result


def current_teacher_profile(profile: dict, stats: dict) -> dict:
    return {**profile, "active_policies_count": stats["assets"]["policies"]["active"],
            "active_cases_count": {kind: stats["assets"][kind]["active"]
                                   for kind in ("question_cases", "critique_cases")},
            "asset_statistics": stats}
