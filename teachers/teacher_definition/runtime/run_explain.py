# -*- coding: utf-8 -*-
"""定义判断讲题引擎 CLI 入口。"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from explain_engine import DefinitionExplainEngine

def main():
    parser = argparse.ArgumentParser(description="协作组定义判断讲题智能体")
    parser.add_argument("--input", required=True, help="输入问题 JSON 文件")
    parser.add_argument("--out", default=None, help="输出报告 Markdown 文件")
    parser.add_argument("--base-dir", default=None, help="教师知识库根目录（可选，默认本工程根目录）")
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"Error: input file {in_path} not found.")
        sys.exit(1)

    base_dir = Path(args.base_dir) if args.base_dir else Path(__file__).resolve().parent.parent
    q = json.loads(in_path.read_text(encoding="utf-8"))
    engine = DefinitionExplainEngine(base_dir)
    report = engine.generate_report(q)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"定义判断讲题报告已生成至: {out_path}")
    else:
        print(report)

if __name__ == "__main__":
    main()
