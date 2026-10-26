"""独立启动入口：客户端无需设置 PYTHONPATH/cwd，直接指向本脚本即可。

    <python> <repo>/scripts/gongkao_mcp_server.py
    <python> <repo>/scripts/gongkao_mcp_server.py --show-tools

Windows venv:  D:\\gong\\gongkao-learning-os\\.venv\\Scripts\\python.exe
POSIX venv:    <repo>/.venv/bin/python3
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.gongkao_mcp.cli import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
