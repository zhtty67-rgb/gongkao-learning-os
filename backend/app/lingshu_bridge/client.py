"""脑侧 MCP stdio 客户端（最小实现，协议蓝本 lingshu/world/brain_store.py）。

单飞请求、逐行 JSON-RPC；stderr 只保留尾部用于诊断。超时或传输失败即关闭
连接，调用方须重新 connect——与 brain_store 的失败语义一致（迟到响应绝不
串入后续调用）。
"""
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path


class BrainError(Exception):
    pass


def dsh_memory_path():
    """dsh-memory 检出目录：env LINGSHU_DSH_MEMORY_PATH 必需（无默认本机路径）。

    也可放在仓库同级的 dsh-memory/ 目录下自动发现。
    """
    raw = os.environ.get('LINGSHU_DSH_MEMORY_PATH')
    candidates = [Path(raw)] if raw else []
    candidates.append(Path(__file__).resolve().parents[3].parent / 'dsh-memory')
    for path in candidates:
        if (path / 'md_cg' / 'mcp_server.py').is_file():
            return path
    raise BrainError(
        '未找到 dsh-memory 检出目录。请设置 LINGSHU_DSH_MEMORY_PATH 指向含 md_cg/ 的仓库检出'
        '（例如 git clone https://github.com/FuRongJun-1999/dsh-memory）。'
    )


def memory_root():
    """认知图真源目录：env LINGSHU_MEMORY_ROOT 优先；否则取 DSH 插件默认脑根
    （~/.dsh/.dsh-memory/data/mdcg，存在即真实在用）；最后回落 ~/.lingshu/memory。"""
    raw = os.environ.get('LINGSHU_MEMORY_ROOT')
    if raw:
        return str(Path(raw))
    dsh_default = Path.home() / '.dsh' / '.dsh-memory' / 'data' / 'mdcg'
    if dsh_default.is_dir():
        return str(dsh_default)
    return str(Path.home() / '.lingshu' / 'memory')


def token_file():
    """明文令牌文件：env LINGSHU_TOKEN_FILE（注意与脑端 MDCG_TOKEN_FILE 语义不同——
    脑端该变量指凭据库 _tokens.json，本侧指签发时捕获的明文）。"""
    raw = os.environ.get('LINGSHU_TOKEN_FILE')
    return raw if raw and Path(raw).is_file() else None


def _load_token():
    """明文 token：MDCG_TOKEN 直接生效；否则读明文令牌文件（脑端凭据库只存 hash，
    明文须由签发方自行保存）。"""
    raw = os.environ.get('MDCG_TOKEN')
    if raw and raw.strip():
        return raw.strip()
    path = token_file()
    if path:
        text = Path(path).read_text(encoding='utf-8').strip()
        if text.startswith('{'):
            try:
                doc = json.loads(text)
                text = doc.get('token') or next(
                    (t.get('token', '') for t in doc.get('tokens', {}).values()
                     if isinstance(t, dict) and t.get('token')), '')
            except ValueError:
                return ''
        return text.strip() or None
    return None


class BrainClient:
    def __init__(self, request_timeout=180.0, root=None, memory_path=None):
        # 180s：md_cg 冷启动要做数据面迁移与 522 项延迟导入校验（实测 >30s）
        self._timeout = request_timeout
        self._id = 0
        self._lock = threading.Lock()          # 串行化请求（不可重入）
        self._close_lock = threading.Lock()    # close 与请求锁分离，超时路径不死锁
        self._closed = False
        self._stderr_tail = b''
        self.server_info = {}
        self._memory_path = str(memory_path or dsh_memory_path())
        self._root = str(root or memory_root())
        env = {
            **os.environ,
            'PYTHONPATH': self._memory_path,
            'MDCG_ROOT': self._root,
            'MDCG_MCP_SURFACE': os.environ.get('MDCG_MCP_SURFACE', 'kernel'),
            'MDCG_ACTOR': os.environ.get('LINGSHU_ACTOR', 'gongkao-sync'),
            'PYTHONUTF8': '1',
            'PYTHONIOENCODING': 'utf-8',
        }
        token = _load_token()
        if token:
            env['MDCG_TOKEN'] = token
            # 服务端校验凭据库 = <aux>/_tokens.json（md_cg.tokens 默认路径语义）；
            # aux 根被重定向时必须同步指过去，否则令牌校验失败、服务拒绝启动。
            if env.get('MDCG_AUX_ROOT') and not os.environ.get('MDCG_TOKEN_FILE'):
                env['MDCG_TOKEN_FILE'] = str(Path(env['MDCG_AUX_ROOT']) / '_tokens.json')
        self._p = subprocess.Popen(
            [os.environ.get('LINGSHU_BRAIN_PYTHON') or sys.executable,
             '-X', 'utf8', '-m', 'md_cg.mcp_server'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, text=True, encoding='utf-8', errors='replace', cwd=self._memory_path,
        )
        self._stderr_worker = threading.Thread(target=self._drain_stderr, daemon=True)
        try:
            self._stderr_worker.start()  # 必须早于握手：启动日志会填满管道
            init = self._exchange({
                'jsonrpc': '2.0', 'method': 'initialize',
                'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                           'clientInfo': {'name': 'gongkao-lingshu-bridge', 'version': '0.1'}},
            })
            self.server_info = (init.get('result') or {}).get('serverInfo') or {}
            if not self.server_info:
                raise BrainError(f'脑侧握手无 serverInfo：{init!r}')
            self._send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        except BaseException:
            self.close()
            raise

    # ---- 低层 ----
    def _send(self, obj):
        self._p.stdin.write(json.dumps(obj, ensure_ascii=False) + '\n')
        self._p.stdin.flush()

    def _drain_stderr(self):
        try:
            while True:
                chunk = self._p.stderr.buffer.read1(4096)
                if not chunk:
                    return
                self._stderr_tail = (self._stderr_tail + chunk)[-4096:]
        except (OSError, ValueError):
            return

    def _diagnostic(self):
        return self._stderr_tail.decode('utf-8', errors='replace')[-400:]

    def _read(self):
        while True:
            line = self._p.stdout.readline()
            if not line:
                raise BrainError('脑进程关闭：' + self._diagnostic())
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict) and ('result' in msg or 'error' in msg):
                return msg

    def _exchange(self, obj):
        with self._lock:
            if self._closed:
                raise BrainError('脑侧 MCP 连接已关闭；请重新连接')
            self._id += 1
            obj['id'] = self._id
            outcome = queue.Queue(maxsize=1)

            def run():
                try:
                    self._send(obj)
                    outcome.put((True, self._read()))
                except Exception as exc:  # noqa: BLE001 —— 经队列回主线程裁决
                    outcome.put((False, exc))

            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            try:
                ok, value = outcome.get(timeout=self._timeout)
            except queue.Empty as exc:
                self.close()
                raise BrainError(
                    f'脑侧 MCP {obj["method"]} 超时（{self._timeout} 秒）：{self._diagnostic()}'
                ) from exc
            worker.join()
            if not ok:
                self.close()
                raise BrainError(f'脑侧 MCP 传输失败：{value}') from value
            return value

    # ---- 调用面 ----
    def call(self, name, arguments):
        """tools/call → 解析 content[0].text（JSON）；isError 或协议错误抛 BrainError。"""
        msg = self._exchange({
            'jsonrpc': '2.0', 'method': 'tools/call',
            'params': {'name': name, 'arguments': arguments},
        })
        if msg.get('error'):
            raise BrainError(f'MCP error：{msg["error"]!r}')
        res = msg.get('result') or {}
        text = ((res.get('content') or [{}])[0]).get('text', '')
        if res.get('isError'):
            raise BrainError(f'工具 {name} 返回 isError：{text[:400]}')
        try:
            return json.loads(text) if text else {}
        except ValueError:
            return {'raw': text}

    def cg(self, op, **params):
        return self.call('cg', {'op': op, **params})

    def close(self):
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        try:
            if self._p.poll() is None:
                try:
                    self._send({'jsonrpc': '2.0', 'id': 10**9, 'method': 'shutdown'})
                except (OSError, ValueError):
                    pass
                try:
                    self._p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._p.kill()
        finally:
            for stream in (self._p.stdin, self._p.stdout, self._p.stderr):
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
