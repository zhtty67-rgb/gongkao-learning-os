"""CLI 装配：诊断面与服务循环（__main__ 与独立启动器共用）。"""
import argparse
import json
import sys

from .protocol import StdioServer, force_utf8_stdio
from .tools import call_tool, server_meta, tool_schemas


def main(argv=None):
    force_utf8_stdio()
    parser = argparse.ArgumentParser(prog='gongkao-mcp')
    parser.add_argument('--show-tools', action='store_true',
                        help='打印工具清单 JSON 后退出（诊断面）')
    args = parser.parse_args(argv)
    if args.show_tools:
        meta = server_meta()
        print(json.dumps({'server': meta, 'tools': tool_schemas()},
                         ensure_ascii=False, indent=2))
        return 0
    server = StdioServer(tool_schemas, call_tool)
    return server.serve()


if __name__ == '__main__':
    sys.exit(main())
