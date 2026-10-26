"""真实客户端兼容性验证：用官方 mcp SDK（python-sdk）作为第三方客户端，
对 gongkao MCP 服务做完整握手 → 列工具 → 调工具。

不写进 pytest：需要外部依赖 `mcp`（本机用 universal-knowledge-hub venv 的
mcp 1.6.0，或任意 pip install mcp 的解释器）。用法：

    <有mcp的python> scripts/compat_mcp_client_check.py \
        --server-python .venv/Scripts/python.exe

成功输出各步读数并退出 0；任何一步失败退出非 0。
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


async def run_check(server_python, server_script, db_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, 'PYTHONUTF8': '1'}
    if db_path:
        env['GONGKAO_DB_PATH'] = db_path
    params = StdioServerParameters(command=server_python, args=[server_script], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f'[1] initialize OK: 协商版本={init.protocolVersion} '
                  f'server={init.serverInfo.name} v{init.serverInfo.version}')
            assert init.protocolVersion, '未返回 protocolVersion'

            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print(f'[2] list_tools OK: {len(names)} 个 -> {", ".join(names)}')
            assert len(names) == 9 and all(n.startswith('gk_') for n in names), names

            overview = await session.call_tool('gk_overview', {})
            assert not overview.isError, overview.content
            payload = json.loads(overview.content[0].text)
            print(f"[3] gk_overview OK: 作答 {payload['metrics']['attempt_count']} 条, "
                  f"掌握度 {round(payload['metrics']['mastery'], 3)}, "
                  f"到期 {payload['due_review_count']}")

            due = await session.call_tool('gk_due_reviews', {'limit': 3})
            payload = json.loads(due.content[0].text)
            print(f"[4] gk_due_reviews OK: 返回 {payload['count']} 张到期卡")

            bad = await session.call_tool('gk_node_detail', {'node': 'no/such/node'})
            assert bad.isError, '不存在的节点应返回 isError 结果'
            print('[5] 错误面 OK: 未知节点返回 isError（非协议错误）')
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--server-python', default=str(REPO / '.venv' / 'Scripts' / 'python.exe'))
    ap.add_argument('--server-script', default=str(REPO / 'scripts' / 'gongkao_mcp_server.py'))
    ap.add_argument('--db', default=os.environ.get('GONGKAO_DB_PATH') or str(REPO / 'data' / 'gongkao.db'))
    args = ap.parse_args()
    ok = asyncio.run(run_check(args.server_python, args.server_script, args.db))
    print('兼容性验证 PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
