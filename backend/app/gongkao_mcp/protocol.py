"""MCP stdio 协议层：行分隔 JSON-RPC 2.0，零第三方依赖。

生命周期遵循 MCP 官方规范（modelcontextprotocol/specification，basic/lifecycle）：
- 版本协商：请求版本在支持集内则**原样回显**，否则回服务端支持的最新版，
  由客户端裁决是否继续；
- 初始化门禁：initialize 之前收到其他带 id 请求 → -32002（Server not
  initialized），ping 例外（规范允许任意时刻）；
- 错误分级对齐 md_cg/mcp_server.py（灵枢脑服务端）：非对象请求 → id=null 的
  -32600 且进程继续服务；tools/call 的 params 非 dict → -32602 且不进工具；
  工具异常 → isError=true 的结果（而非协议错误）；未知方法带 id → -32601。

本层只承载协议，不含业务：工具 schema 与分发由 tools.py 提供。
"""
import json
import sys

# 官方已发布规范版本；本服务工具面（tools/call, text content）在四个版本间无破坏性差异
SUPPORTED_PROTOCOL_VERSIONS = (
    '2024-11-05',
    '2025-03-26',
    '2025-06-18',
    '2025-11-25',
)
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[-1]
SERVER_NAME = 'gongkao-learning-os'
SERVER_VERSION = '0.2.0'

SERVER_INSTRUCTIONS = (
    '公考学习系统只读网关：查询掌握度/FSRS到期复习/错题本/知识树/个人笔记，'
    'gk_ask_teacher 默认本地教师检索（零成本），use_llm=true 才产生 LLM 成本。'
)

ERR_PARSE = -32700
ERR_INVALID_REQUEST = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL = -32603
ERR_NOT_INITIALIZED = -32002


def force_utf8_stdio():
    """stdio 三流强制 UTF-8（Windows 默认 GBK 会打碎中文工具面）。"""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass


def negotiate_protocol_version(requested):
    """规范 lifecycle：支持则回显请求版本，否则回最新支持版（客户端裁决）。"""
    if requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return LATEST_PROTOCOL_VERSION


def _write(obj, stdout=None):
    out = stdout or sys.stdout
    out.write(json.dumps(obj, ensure_ascii=False) + '\n')
    out.flush()


def reply(rid, result=None, error=None, stdout=None):
    msg = {'jsonrpc': '2.0', 'id': rid}
    if error is not None:
        msg['error'] = error
    else:
        msg['result'] = result if result is not None else {}
    _write(msg, stdout)


def tool_result(payload, is_error=False, stdout=None):
    """包装 tools/call 结果：JSON 文本落进 content[0].text。"""
    result = {
        'content': [{'type': 'text',
                     'text': json.dumps(payload, ensure_ascii=False)}],
        'isError': is_error,
    }
    return result


class StdioServer:
    """单请求串行的 MCP stdio 服务循环。

    ``tool_schemas`` 返回 tools/list 的工具描述列表；``invoke(name, args)``
    执行工具并返回可 JSON 序列化的 dict。单连接进程，initialized 状态随连接
    存续。
    """

    def __init__(self, tool_schemas, invoke):
        self._schemas = tool_schemas
        self._invoke = invoke
        self._initialized = False

    def serve_line(self, msg, stdout=None):
        """处理一条已解析消息；返回 True 表示请求进程下线。"""
        if not isinstance(msg, dict):
            reply(None, error={'code': ERR_INVALID_REQUEST,
                               'message': 'Invalid Request：请求体必须为 JSON 对象'
                                          f'（收到 {type(msg).__name__}）'},
                  stdout=stdout)
            return False
        rid = msg.get('id')
        method = msg.get('method')
        try:
            if method == 'initialize':
                requested = (msg.get('params') or {}).get('protocolVersion') \
                    if isinstance(msg.get('params'), dict) else None
                reply(rid, {
                    'protocolVersion': negotiate_protocol_version(requested),
                    'capabilities': {'tools': {}},
                    'serverInfo': {'name': SERVER_NAME, 'version': SERVER_VERSION},
                    'instructions': SERVER_INSTRUCTIONS,
                }, stdout=stdout)
            elif method in ('notifications/initialized', 'initialized'):
                self._initialized = True  # 通知不应答
            elif method == 'ping':
                reply(rid, {}, stdout=stdout)  # 规范允许任意时刻
            elif method == 'shutdown':
                reply(rid, {}, stdout=stdout)
                return True
            elif not self._initialized:
                if rid is not None:
                    reply(rid, error={'code': ERR_NOT_INITIALIZED,
                                      'message': 'Server not initialized：'
                                                 '请先完成 initialize 握手'},
                          stdout=stdout)
            elif method == 'tools/list':
                reply(rid, {'tools': self._schemas()}, stdout=stdout)
            elif method == 'tools/call':
                params = msg.get('params')
                if params is not None and not isinstance(params, dict):
                    reply(rid, error={'code': ERR_INVALID_PARAMS,
                                      'message': f'Invalid params：params 必须为 object（收到 {type(params).__name__}）'},
                          stdout=stdout)
                    return False
                params = params or {}
                name = params.get('name')
                args = params.get('arguments') or {}
                if not isinstance(name, str) or not name:
                    reply(rid, error={'code': ERR_INVALID_PARAMS,
                                      'message': 'Invalid params：name 必须为非空 string；'
                                                 '请传入 tools/list 返回的工具名'},
                          stdout=stdout)
                    return False
                if not isinstance(args, dict):
                    reply(rid, error={'code': ERR_INVALID_PARAMS,
                                      'message': f'Invalid params：arguments 必须为 object（收到 {type(args).__name__}）'},
                          stdout=stdout)
                    return False
                try:
                    out = self._invoke(name, args)
                    reply(rid, tool_result(out), stdout=stdout)
                except Exception as exc:  # noqa: BLE001 —— 工具错误以 MCP 结果返回
                    payload = {'error': f'{type(exc).__name__}: {exc}'}
                    hint = getattr(exc, 'hint', None)
                    if hint:
                        payload['hint'] = hint
                    reply(rid, tool_result(payload, is_error=True), stdout=stdout)
            elif rid is not None:
                reply(rid, error={'code': ERR_METHOD_NOT_FOUND,
                                  'message': f'method not found: {method}'},
                      stdout=stdout)
        except Exception as exc:  # noqa: BLE001 —— 入口兜底不崩 server
            sys.stderr.write(f'[gongkao-mcp] 主循环兜底（继续服务）: {exc!r}\n')
            reply(rid, error={'code': ERR_INTERNAL,
                              'message': f'internal error: {type(exc).__name__}'},
                  stdout=stdout)
        return False

    def serve(self, stdin=None, stdout=None):
        stream = stdin or sys.stdin
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError as exc:
                reply(None, error={'code': ERR_PARSE, 'message': f'Parse error: {exc}'},
                      stdout=stdout)
                continue
            if self.serve_line(msg, stdout=stdout):
                return 0
        return 0
