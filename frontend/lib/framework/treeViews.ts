import { MasteryNode } from '../api';
import { buildForest, isAuxiliaryNode } from './model';

export type TreeView = 'knowledge' | 'support';
type SupportRole = 'method' | 'strategy' | 'case' | 'reference';
const LABELS: Record<SupportRole, string> = {
  method: '技巧与方法', strategy: '备考与考场策略', case: '案例与示范', reference: '辅助资料',
};

export function isTreeFolder(node: MasteryNode): boolean {
  return node.id.startsWith('__framework_support__:');
}

/** Two display trees share original IDs. Canonical parents and API bindings stay intact. */
export function buildTreeViews(nodes: MasteryNode[]) {
  const canonical = buildForest(nodes);
  const roles = new Map<string, SupportRole>();
  const resolve = (node: MasteryNode): SupportRole | undefined => {
    if (roles.has(node.id)) return roles.get(node.id);
    let role: SupportRole | undefined;
    if (node.node_type in LABELS) role = node.node_type as SupportRole;
    else if (/案例示范|典型案例/.test(node.name)) role = 'case';
    else if (/考场策略|备考策略/.test(node.name)) role = 'strategy';
    else if (/技巧|解题方法|法应用|法验证|尾数法|造句/.test(node.name)) role = 'method';
    else if (isAuxiliaryNode(node)) role = 'reference';
    const parent = node.parent_id ? canonical.nodeById.get(node.parent_id) : undefined;
    const inherited = parent ? resolve(parent) : undefined;
    // Explicit case/strategy sections override a broader methods section.
    role = role || inherited;
    if (role) roles.set(node.id, role);
    return role;
  };
  nodes.forEach(resolve);

  const primaryNodes = nodes.filter(n => !roles.has(n.id)).map(n => ({ ...n }));
  const supportNodes: MasteryNode[] = [];
  const groups = new Set<string>();
  const folder = (module: string, role?: SupportRole): string => `__framework_support__:${module}:${role || 'root'}`;
  const makeFolder = (sample: MasteryNode, role?: SupportRole): MasteryNode => ({
    ...sample, id: folder(sample.module, role), parent_id: role ? folder(sample.module) : null,
    name: role ? LABELS[role] : `${sample.module} · 技巧策略案例`, node_type: 'reference',
    knowledge_node_code: null, description: '按模块集中查找技巧、策略和案例；具体条目保留原有资料与笔记。',
    metadata_json: JSON.stringify({ mastery_eligible: false, virtual_folder: true }),
    attempt_count: 0, mastery_score: 0.5, evidence_positive: 0, evidence_negative: 0,
    recent_accuracy: null, timed_accuracy: null, avg_time_ratio: null, hint_dependency: 0,
    last_practiced_at: null, direct_question_count: 0, practiced_question_count: 0, error_question_count: 0,
    subtree_question_count: 0,
  } as MasteryNode);
  for (const n of nodes) {
    const role = roles.get(n.id);
    if (!role) continue;
    const root = folder(n.module);
    const group = folder(n.module, role);
    if (!groups.has(root)) { supportNodes.push(makeFolder(n)); groups.add(root); }
    if (!groups.has(group)) { supportNodes.push(makeFolder(n, role)); groups.add(group); }
    const parentRole = n.parent_id ? roles.get(n.parent_id) : undefined;
    const parent = n.parent_id ? canonical.nodeById.get(n.parent_id) : undefined;
    supportNodes.push({ ...n, node_type: role,
      parent_id: parentRole === role && parent?.module === n.module ? n.parent_id : group,
      metadata_json: JSON.stringify({ ...JSON.parse(n.metadata_json || '{}'), mastery_eligible: false }),
    });
  }
  return { canonical, roles, knowledge: buildForest(primaryNodes), support: buildForest(supportNodes) };
}

export function relatedKnowledgeId(id: string, views: ReturnType<typeof buildTreeViews>): string | null {
  let node = views.canonical.nodeById.get(id)?.parent;
  while (node && views.roles.has(node.id)) node = node.parent;
  return node?.id || null;
}
