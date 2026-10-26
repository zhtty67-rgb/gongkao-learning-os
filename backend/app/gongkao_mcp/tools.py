"""工具面：9 个只读工具的 schema 与分发。"""
from . import queries, teacher
from .protocol import SERVER_NAME, SERVER_VERSION

_LIMIT = {'type': 'integer', 'minimum': 1, 'maximum': 100}
_MODULE = {'type': 'string', 'description': '模块名过滤，如 判断推理/言语理解与表达/数量关系/资料分析/常识判断/申论'}


def tool_schemas():
    return [
        {
            'name': 'gk_overview',
            'description': '学习概览：总览指标（作答数/正确率/掌握度）、各模块掌握度卷积、到期复习数、今日目标与最薄弱点。',
            'inputSchema': {'type': 'object', 'properties': {}},
        },
        {
            'name': 'gk_mastery',
            'description': '掌握度明细：按模块过滤或定位单节点（Beta 后验掌握分、正负证据、近期正确率、提示依赖）。',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'module': _MODULE,
                    'node': {'type': 'string', 'description': '节点定位：knowledge_node_code、code 或 id'},
                    'limit': _LIMIT,
                },
            },
        },
        {
            'name': 'gk_due_reviews',
            'description': 'FSRS 到期复习卡片列表（默认保留0.9，含稳定度/难度/历史轮次）。',
            'inputSchema': {'type': 'object', 'properties': {'limit': _LIMIT}},
        },
        {
            'name': 'gk_wrong_book',
            'description': '错题本：全局错因分布（十维错因体系）+ 最近错题事件，可按模块过滤。',
            'inputSchema': {
                'type': 'object',
                'properties': {'module': _MODULE, 'limit': _LIMIT},
            },
        },
        {
            'name': 'gk_knowledge_tree',
            'description': '知识树骨架（~660+ 节点，自根向下到指定深度，附各节点掌握度）。',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'module': _MODULE,
                    'depth': {'type': 'integer', 'minimum': 1, 'maximum': 6},
                },
            },
        },
        {
            'name': 'gk_node_detail',
            'description': '单知识节点深览：完整资料、掌握度、绑题数、错因分布、最近作答。',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'node': {'type': 'string', 'description': '节点定位：knowledge_node_code、code 或 id'},
                },
                'required': ['node'],
            },
        },
        {
            'name': 'gk_recent_attempts',
            'description': '最近作答流：含信心档位、提示层级、耗时与正误，可按模块/会话过滤。',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'limit': _LIMIT,
                    'session_id': {'type': 'string'},
                    'module': _MODULE,
                    'only_wrong': {'type': 'boolean', 'description': '只看错题'},
                },
            },
        },
        {
            'name': 'gk_notes',
            'description': '个人笔记检索（user_notes）：按节点/题目/模块过滤，只读。',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'node': {'type': 'string', 'description': '知识节点 code 或 id'},
                    'question_id': {'type': 'string'},
                    'module': _MODULE,
                    'limit': _LIMIT,
                },
            },
        },
        {
            'name': 'gk_ask_teacher',
            'description': (
                '名师讲题。默认返回该模块独立教师模型的方法参考（纯本地检索，零成本，'
                '自带越界门禁）；use_llm=true 时经运行中的后端做完整 LLM 讲题（有成本）。'
            ),
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'question_id': {'type': 'string', 'description': '题目 ID（与二选一）'},
                    'stem': {'type': 'string', 'description': '题面文本（与 question_id 二选一）'},
                    'module': _MODULE,
                    'use_llm': {'type': 'boolean', 'description': '显式开启 LLM 讲题（有外部成本）'},
                },
            },
        },
    ]


def _clamp_limit(args, default=20):
    raw = args.get('limit', default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(100, value))


def call_tool(name, args):
    """分发工具调用；每个调用独立只读连接。"""
    if name == 'gk_overview':
        with queries.ro_connect() as db:
            return queries.overall(db)
    if name == 'gk_mastery':
        with queries.ro_connect() as db:
            return queries.mastery_detail(
                db, module=args.get('module'), node=args.get('node'),
                limit=_clamp_limit(args, 50),
            )
    if name == 'gk_due_reviews':
        with queries.ro_connect() as db:
            return queries.due_list(db, limit=_clamp_limit(args))
    if name == 'gk_wrong_book':
        with queries.ro_connect() as db:
            return queries.wrong_book(db, module=args.get('module'), limit=_clamp_limit(args))
    if name == 'gk_knowledge_tree':
        try:
            depth = int(args.get('depth', 2))
        except (TypeError, ValueError):
            depth = 2
        depth = max(1, min(6, depth))
        with queries.ro_connect() as db:
            return queries.knowledge_tree(db, module=args.get('module'), depth=depth)
    if name == 'gk_node_detail':
        node = args.get('node')
        if not node:
            raise ValueError("gk_node_detail 需要 node 参数（knowledge_node_code/code/id）")
        with queries.ro_connect() as db:
            return queries.node_detail(db, node)
    if name == 'gk_recent_attempts':
        with queries.ro_connect() as db:
            return queries.recent_attempts(
                db, limit=_clamp_limit(args), session_id=args.get('session_id'),
                module=args.get('module'), only_wrong=bool(args.get('only_wrong')),
            )
    if name == 'gk_notes':
        with queries.ro_connect() as db:
            return queries.notes(
                db, node=args.get('node'), question_id=args.get('question_id'),
                module=args.get('module'), limit=_clamp_limit(args),
            )
    if name == 'gk_ask_teacher':
        return teacher.ask_teacher(
            question_id=args.get('question_id'), stem=args.get('stem'),
            module=args.get('module'), use_llm=bool(args.get('use_llm')),
        )
    raise KeyError(f'未知工具: {name!r}；请传入 tools/list 返回的工具名')


def server_meta():
    return {'name': SERVER_NAME, 'version': SERVER_VERSION}
