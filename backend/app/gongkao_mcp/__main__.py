"""stdio 入口：``python -m backend.app.gongkao_mcp``（需仓库根在 sys.path）。"""
import sys

from .cli import main

if __name__ == '__main__':
    sys.exit(main())
