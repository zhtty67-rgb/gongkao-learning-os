import { MasteryNode } from '../api';

// ---------------------------------------------------------------------------
// 学习状态口径（沿用原知识框架页阈值，未新增规则）：
// - 掌握度 mastery_score 由后端从 attempts 重建（拉普拉斯平滑 (1+正)/(2+正+负)）。
// - 未练习（attempt_count=0）时 mastery_score 恒为默认值 0.5，不得展示为“掌握一半”。
// - 较熟练：已练习且 mastery_score >= 0.75；待巩固：已练习且 < 0.75。
// - knowledge_nodes.mastery_threshold(=0.8) 当前无任何后端逻辑消费，不作为展示阈值。
// ---------------------------------------------------------------------------
export const SKILLED_THRESHOLD = 0.75;

export type NodeStatus = 'unpracticed' | 'weak' | 'skilled';

export function nodeStatus(n: Pick<MasteryNode, 'attempt_count' | 'mastery_score'>): NodeStatus {
  if (!n.attempt_count || n.attempt_count <= 0) return 'unpracticed';
  return n.mastery_score >= SKILLED_THRESHOLD ? 'skilled' : 'weak';
}

export const STATUS_LABEL: Record<NodeStatus, string> = {
  unpracticed: '未练习',
  weak: '待巩固',
  skilled: '较熟练',
};

export const NODE_TYPE_LABEL: Record<string, string> = {
  module: '模块',
  topic: '主题',
  concept: '概念',
  skill: '考点',
  method: '方法',
  reference: '辅助资料',
  strategy: '策略',
  case: '案例',
};

export function isAuxiliaryNode(n: Pick<MasteryNode, 'metadata_json'>): boolean {
  try {
    return JSON.parse(n.metadata_json || '{}').mastery_eligible === false;
  } catch {
    return false;
  }
}

export interface FrameworkNode extends MasteryNode {
  children: FrameworkNode[];
  parent: FrameworkNode | null;
  depth: number;
  descendantCount: number;
  /** 后端按题目去重的子树题量（旧后端无此字段时为 null） */
  subtreeQuestionCount: number | null;
}

export interface FrameworkForest {
  nodeById: Map<string, FrameworkNode>;
  rootsByModule: Record<string, FrameworkNode[]>;
  modules: string[];
  allNodes: FrameworkNode[];
}

const MODULE_ORDER = ['图形推理', '立体图推', '定义判断', '类比推理', '逻辑判断', '资料分析', '言语理解', '数量关系', '政治理论', '常识判断', '申论'];

export function buildForest(nodes: MasteryNode[]): FrameworkForest {
  const nodeById = new Map<string, FrameworkNode>();
  for (const n of nodes) {
    const subtree = (n as MasteryNode & { subtree_question_count?: unknown }).subtree_question_count;
    nodeById.set(n.id, {
      ...n,
      children: [],
      parent: null,
      depth: 0,
      descendantCount: 0,
      subtreeQuestionCount: typeof subtree === 'number' ? subtree : null,
    });
  }
  const rootsByModule: Record<string, FrameworkNode[]> = {};
  for (const node of nodeById.values()) {
    const parent = node.parent_id ? nodeById.get(node.parent_id) : undefined;
    if (parent) {
      node.parent = parent;
      parent.children.push(node);
    } else {
      (rootsByModule[node.module] ||= []).push(node);
    }
  }
  const measure = (n: FrameworkNode, depth: number): number => {
    n.depth = depth;
    // 与原列表一致：同层按名称排序（后端同父节点亦按 name 排序）
    n.children.sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN'));
    let count = 0;
    for (const child of n.children) count += 1 + measure(child, depth + 1);
    n.descendantCount = count;
    return count;
  };
  for (const roots of Object.values(rootsByModule)) {
    for (const root of roots) measure(root, 0);
  }
  const present = Object.keys(rootsByModule);
  const modules = MODULE_ORDER.filter(m => present.includes(m)).concat(
    present.filter(m => !MODULE_ORDER.includes(m)).sort((a, b) => a.localeCompare(b, 'zh-Hans-CN')),
  );
  return { nodeById, rootsByModule, modules, allNodes: [...nodeById.values()] };
}

export function pathOf(forest: FrameworkForest, id: string): FrameworkNode[] {
  const out: FrameworkNode[] = [];
  let cur: FrameworkNode | null | undefined = forest.nodeById.get(id);
  while (cur) {
    out.unshift(cur);
    cur = cur.parent;
  }
  return out;
}

export function parseAliases(metadataJson: string | null | undefined): string[] {
  try {
    const meta = JSON.parse(metadataJson || '{}');
    return Array.isArray(meta.aliases) ? meta.aliases.filter((a: unknown): a is string => typeof a === 'string') : [];
  } catch {
    return [];
  }
}

export interface SearchHit {
  node: FrameworkNode;
  path: string[];
  matchedAlias: string | null;
}

export function searchNodes(forest: FrameworkForest, query: string): SearchHit[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const hits: SearchHit[] = [];
  for (const node of forest.allNodes) {
    let matchedAlias: string | null = null;
    const nameHit = node.name.toLowerCase().includes(q);
    const descHit = !!node.description && node.description.toLowerCase().includes(q);
    if (!nameHit && !descHit) {
      matchedAlias = parseAliases(node.metadata_json).find(a => a.toLowerCase().includes(q)) || null;
      if (!matchedAlias) continue;
    }
    hits.push({ node, path: pathOf(forest, node.id).map(n => n.name), matchedAlias });
  }
  hits.sort((a, b) => {
    const nameA = a.node.name.toLowerCase().startsWith(q) ? 0 : 1;
    const nameB = b.node.name.toLowerCase().startsWith(q) ? 0 : 1;
    return nameA - nameB || a.node.name.localeCompare(b.node.name, 'zh-Hans-CN');
  });
  return hits;
}

/** 当前模块内“待巩固”的节点（已练习且掌握度低于阈值）。 */
export function weakTargetIds(roots: FrameworkNode[]): Set<string> {
  const out = new Set<string>();
  const walk = (n: FrameworkNode) => {
    if (nodeStatus(n) === 'weak') out.add(n.id);
    n.children.forEach(walk);
  };
  roots.forEach(walk);
  return out;
}

/** 薄弱点筛选的可见集合：薄弱节点本身 + 通往它们的祖先路径，避免孤立节点。 */
export function visibleSetForWeak(nodeById: Map<string, FrameworkNode>, weakIds: Set<string>): Set<string> {
  const visible = new Set<string>();
  for (const id of weakIds) {
    let cur: FrameworkNode | null | undefined = nodeById.get(id);
    while (cur) {
      visible.add(cur.id);
      cur = cur.parent;
    }
  }
  return visible;
}

// ---------------------------------------------------------------------------
// 地图布局：自左向右的 tidy tree（叶行堆叠法）。
// 节点高度统一，可见叶子按顺序占行，父节点垂直居中于其可见子树跨度。
// 好处：同层互不重叠；展开/折叠时，被操作节点之前的兄弟位置保持不变。
// ---------------------------------------------------------------------------
export const MAP_METRICS = {
  colWidth: 250,
  rowHeight: 46,
  nodeWidth: 208,
  nodeHeight: 34,
  rootGapRows: 1.4,
  pad: 24,
} as const;

export type ExpandedMap = Record<string, boolean>;

export interface MapPosition {
  id: string;
  node: FrameworkNode;
  x: number;
  y: number;
  depth: number;
}

export interface MapLayout {
  positions: Map<string, MapPosition>;
  edges: Array<{ fromId: string; toId: string }>;
  width: number;
  height: number;
  visibleCount: number;
}

export function isNodeExpanded(n: FrameworkNode, layoutDepth: number, expanded: ExpandedMap): boolean {
  const explicit = expanded[n.id];
  if (typeof explicit === 'boolean') return explicit;
  // 默认只展开第一层：整图塞进屏幕会把文字缩到不可读（实测 36%）。
  // 更深层按需展开；“适应屏幕”保留为独立的查看全貌操作。
  return layoutDepth < 1;
}

export function layoutForest(
  roots: FrameworkNode[],
  opts: { expanded: ExpandedMap; visible?: Set<string> | null },
): MapLayout {
  const positions = new Map<string, MapPosition>();
  const edges: Array<{ fromId: string; toId: string }> = [];
  let row = 0;
  let maxRight = 0;
  let visibleCount = 0;

  const place = (n: FrameworkNode, layoutDepth: number, y: number) => {
    positions.set(n.id, { id: n.id, node: n, x: layoutDepth * MAP_METRICS.colWidth, y, depth: layoutDepth });
    maxRight = Math.max(maxRight, layoutDepth * MAP_METRICS.colWidth + MAP_METRICS.nodeWidth);
    visibleCount += 1;
  };

  const walk = (n: FrameworkNode, layoutDepth: number): { first: number; last: number } => {
    const expanded = isNodeExpanded(n, layoutDepth, opts.expanded);
    const kids = expanded
      ? opts.visible
        ? n.children.filter(c => opts.visible!.has(c.id))
        : n.children
      : [];
    if (kids.length === 0) {
      const y = row * MAP_METRICS.rowHeight;
      row += 1;
      place(n, layoutDepth, y);
      return { first: y, last: y };
    }
    let first = Infinity;
    let last = -Infinity;
    for (const kid of kids) {
      const span = walk(kid, layoutDepth + 1);
      first = Math.min(first, span.first);
      last = Math.max(last, span.last);
      edges.push({ fromId: n.id, toId: kid.id });
    }
    const y = (first + last) / 2;
    place(n, layoutDepth, y);
    return { first, last };
  };

  roots.forEach((root, i) => {
    if (i > 0) row += MAP_METRICS.rootGapRows;
    walk(root, 0);
  });

  const height = Math.max(row, 1) * MAP_METRICS.rowHeight + MAP_METRICS.pad * 2;
  const width = maxRight + MAP_METRICS.pad * 2;
  return { positions, edges, width, height, visibleCount };
}

// ---------------------------------------------------------------------------
// 持久化：按模块记住展开状态、选中节点、聚焦分支与视口。
// 恢复时会对照当前节点集合裁剪，数据变化后失效 id 会被安全丢弃。
// ---------------------------------------------------------------------------
export type Viewport = { x: number; y: number; k: number };

export interface ModuleMapState {
  expanded: ExpandedMap;
  selectedId: string | null;
  focusId: string | null;
  viewport: Viewport | null;
  onlyWeak?: boolean;
}

export interface FrameworkPersist {
  version: 1;
  viewMode: 'map' | 'list';
  activeModule: string | null;
  modules: Record<string, ModuleMapState>;
  activeTree?: 'knowledge' | 'support';
}

const STORAGE_KEY = 'gongkao.framework.map.v1';

export function emptyModuleState(): ModuleMapState {
  return { expanded: {}, selectedId: null, focusId: null, viewport: null };
}

export function loadPersist(): FrameworkPersist {
  const fallback: FrameworkPersist = { version: 1, viewMode: 'map', activeModule: null, modules: {} };
  try {
    const raw = typeof window === 'undefined' ? null : window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return fallback;
    const value = JSON.parse(raw);
    if (!value || value.version !== 1) return fallback;
    return {
      version: 1,
      viewMode: value.viewMode === 'list' ? 'list' : 'map',
      activeModule: typeof value.activeModule === 'string' ? value.activeModule : null,
      modules: value.modules && typeof value.modules === 'object' ? value.modules : {},
      activeTree: value.activeTree === 'support' ? 'support' : 'knowledge',
    };
  } catch {
    return fallback;
  }
}

export function savePersist(p: FrameworkPersist) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
  } catch {
    // 隐私模式等场景下不可用，忽略即可（页面行为不受影响）
  }
}

export function sanitizeModuleState(state: ModuleMapState | undefined, forest: FrameworkForest): ModuleMapState {
  const base = state ? { ...emptyModuleState(), ...state } : emptyModuleState();
  const exists = (id: unknown): id is string => typeof id === 'string' && forest.nodeById.has(id);
  const expanded: ExpandedMap = {};
  for (const [id, v] of Object.entries(base.expanded || {})) {
    if (exists(id) && typeof v === 'boolean') expanded[id] = v;
  }
  const viewport =
    base.viewport &&
    Number.isFinite(base.viewport.x) &&
    Number.isFinite(base.viewport.y) &&
    Number.isFinite(base.viewport.k) &&
    base.viewport.k > 0.05 &&
    base.viewport.k < 8
      ? { x: base.viewport.x, y: base.viewport.y, k: base.viewport.k }
      : null;
  return {
    expanded,
    selectedId: exists(base.selectedId) ? base.selectedId : null,
    focusId: exists(base.focusId) ? base.focusId : null,
    viewport,
    onlyWeak: base.onlyWeak === true,
  };
}

export function percentLabel(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`;
}
