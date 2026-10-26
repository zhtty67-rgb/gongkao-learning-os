'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, MasteryData, MasteryNode } from '../../lib/api';
import FrameworkToolbar from '../../lib/framework/FrameworkToolbar';
import FrameworkListView from '../../lib/framework/FrameworkListView';
import KnowledgeMap, { LocateRequest } from '../../lib/framework/KnowledgeMap';
import NodeDetailPanel from '../../lib/framework/NodeDetailPanel';
import { buildTreeViews, isTreeFolder, relatedKnowledgeId, TreeView } from '../../lib/framework/treeViews';
import {
  ExpandedMap,
  FrameworkPersist,
  FrameworkNode,
  ModuleMapState,
  SearchHit,
  Viewport,
  buildForest,
  emptyModuleState,
  layoutForest,
  loadPersist,
  pathOf,
  sanitizeModuleState,
  savePersist,
  searchNodes,
  visibleSetForWeak,
  weakTargetIds,
} from '../../lib/framework/model';

export default function KnowledgeFrameworkPage() {
  const router = useRouter();

  // ------------------------------------------------------------------ 数据
  const [nodes, setNodes] = useState<MasteryNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reloadNonce, setReloadNonce] = useState(0);
  const [aiFocusNonce, setAiFocusNonce] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    api<MasteryData>('/mastery')
      .then(res => {
        if (active) {
          setNodes(res.nodes);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof Error ? err.message : '无法加载知识框架数据，请确认后端已正常启动。');
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [reloadNonce]);

  // ------------------------------------------------------------------ 持久化 UI 状态
  const [persist, setPersist] = useState<FrameworkPersist>({ version: 1, viewMode: 'map', activeModule: null, modules: {} });
  useEffect(() => {
    setPersist(loadPersist());
  }, []);

  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => savePersist(persist), 250);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [persist]);

  const treeViews = useMemo(() => buildTreeViews(nodes), [nodes]);
  const activeTree: TreeView = persist.activeTree || 'knowledge';
  const forest = treeViews[activeTree];

  const activeModule = useMemo(() => {
    if (persist.activeModule && treeViews.canonical.modules.includes(persist.activeModule)) return persist.activeModule;
    return treeViews.canonical.modules[0] || '';
  }, [persist.activeModule, treeViews]);

  const stateKey = activeTree === 'support' ? `support::${activeModule}` : activeModule;
  const modState: ModuleMapState = useMemo(
    () => sanitizeModuleState(persist.modules[stateKey], forest),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [persist.modules, stateKey, forest],
  );

  const updateModuleState = useCallback(
    (patch: Partial<ModuleMapState> | ((prev: ModuleMapState) => Partial<ModuleMapState>)) => {
      setPersist(p => {
        const prev = sanitizeModuleState(p.modules[stateKey], forest);
        const delta = typeof patch === 'function' ? patch(prev) : patch;
        return {
          ...p,
          activeModule,
          modules: { ...p.modules, [stateKey]: { ...prev, ...delta } },
        };
      });
    },
    [activeModule, stateKey, forest],
  );

  const setActiveModule = useCallback((m: string) => {
    setPersist(p => ({ ...p, activeModule: m }));
  }, []);

  const setViewMode = useCallback((mode: 'map' | 'list') => {
    setPersist(p => ({ ...p, viewMode: mode }));
  }, []);

  const setActiveTree = useCallback((tree: TreeView) => {
    setPersist(p => ({ ...p, activeTree: tree }));
    setSearchText('');
  }, []);

  // ------------------------------------------------------------------ 派生结构
  const focusNode = modState.focusId ? forest.nodeById.get(modState.focusId) || null : null;
  const displayRoots: FrameworkNode[] = focusNode ? [focusNode] : forest.rootsByModule[activeModule] || [];

  const onlyWeak = activeTree === 'knowledge' && modState.onlyWeak === true;
  const weakIds = useMemo(() => (onlyWeak ? weakTargetIds(displayRoots) : null), [onlyWeak, displayRoots]);
  const visibleSet = useMemo(
    () => (weakIds && weakIds.size > 0 ? visibleSetForWeak(forest.nodeById, weakIds) : null),
    [weakIds, forest],
  );

  const layout = useMemo(
    () => layoutForest(displayRoots, { expanded: modState.expanded, visible: visibleSet }),
    [displayRoots, modState.expanded, visibleSet],
  );

  const selectedNode = modState.selectedId ? forest.nodeById.get(modState.selectedId) || null : null;
  useEffect(() => {
    if (!aiFocusNonce || !selectedNode) return;
    const section = document.getElementById(`node-ai-${selectedNode.id}`);
    section?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    section?.querySelector('textarea')?.focus({ preventScroll: true });
  }, [aiFocusNonce, selectedNode, persist.viewMode]);
  const selectedPath = useMemo(
    () => (selectedNode ? pathOf(forest, selectedNode.id) : []),
    [selectedNode, forest],
  );

  const [searchText, setSearchText] = useState('');
  const searchHits = useMemo(() => (searchText.trim() ? searchNodes(treeViews.canonical, searchText).map(hit => ({
    ...hit, node: treeViews.support.nodeById.get(hit.node.id) || treeViews.knowledge.nodeById.get(hit.node.id) || hit.node,
  })) : null), [searchText, treeViews]);

  const weakCount = useMemo(() => weakTargetIds(displayRoots).size, [displayRoots]);

  const [locateRequest, setLocateRequest] = useState<LocateRequest | null>(null);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const locateNonce = useRef(0);

  const locateNode = useCallback(
    (hit: SearchHit) => {
      const targetTree: TreeView = treeViews.support.nodeById.has(hit.node.id) ? 'support' : 'knowledge';
      const targetForest = treeViews[targetTree];
      const target = targetForest.nodeById.get(hit.node.id);
      if (!target) return;
      const path = pathOf(targetForest, target.id);
      const targetStateKey = targetTree === 'support' ? `support::${target.module}` : target.module;
      // 若目标在当前聚焦分支之外，先退出聚焦；薄弱点筛选可能隐藏目标，同样关闭
      const focusStillContains = !focusNode || path.some(n => n.id === focusNode.id);
      const patch: Partial<ModuleMapState> = {
        selectedId: target.id,
        focusId: focusStillContains ? modState.focusId : null,
      };
      if (modState.onlyWeak) patch.onlyWeak = false;
      setPersist(p => {
        const prev = sanitizeModuleState(p.modules[targetStateKey], targetForest);
        const expanded: ExpandedMap = { ...prev.expanded };
        for (const ancestor of path.slice(0, -1)) expanded[ancestor.id] = true;
        return {
          ...p,
          activeModule: target.module,
          activeTree: targetTree,
          modules: {
            ...p.modules,
            [targetStateKey]: { ...prev, ...patch, expanded },
          },
        };
      });
      locateNonce.current += 1;
      setLocateRequest({ id: target.id, nonce: locateNonce.current });
      setHighlightId(target.id);
      if (highlightTimer.current) clearTimeout(highlightTimer.current);
      highlightTimer.current = setTimeout(() => setHighlightId(null), 2600);
      // 列表视图：滚动到目标行
      requestAnimationFrame(() => {
        document.querySelector(`[data-list-node-id="${CSS.escape(target.id)}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      });
    },
    [treeViews, focusNode, modState.focusId, modState.onlyWeak],
  );

  // ------------------------------------------------------------------ 专项训练
  const [starting, setStarting] = useState(false);
  const [practiceError, setPracticeError] = useState<string | null>(null);

  const startPractice = useCallback(
    async (nodeId: string) => {
      if (starting) return;
      setStarting(true);
      setPracticeError(null);
      try {
        const res = await api<{ id: string; total: number }>('/quiz/session', { node_id: nodeId });
        localStorage.setItem('gongkao_session_id', res.id);
        router.push(`/quiz?session=${encodeURIComponent(res.id)}`);
      } catch (err: unknown) {
        setPracticeError(err instanceof Error ? err.message : '发起专项训练失败');
        setStarting(false);
      }
    },
    [starting, router],
  );

  // ------------------------------------------------------------------ 全屏
  const stageRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', handler);
    return () => document.removeEventListener('fullscreenchange', handler);
  }, []);
  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) {
      void document.exitFullscreen();
    } else {
      stageRef.current?.requestFullscreen?.().catch(() => {
        // 浏览器拒绝（如未授权）时静默忽略，按钮状态保持
      });
    }
  }, []);

  // ------------------------------------------------------------------ 键盘
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !document.fullscreenElement && modState.selectedId) {
        updateModuleState({ selectedId: null });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [modState.selectedId, updateModuleState]);

  // ------------------------------------------------------------------ 列表展开辅助
  const expandAllInModule = useCallback(() => {
    const expanded: ExpandedMap = {};
    const walk = (n: FrameworkNode) => {
      expanded[n.id] = true;
      n.children.forEach(walk);
    };
    displayRoots.forEach(walk);
    updateModuleState({ expanded });
  }, [displayRoots, updateModuleState]);

  const collapseAllInModule = useCallback(() => {
    updateModuleState({ expanded: {} });
  }, [updateModuleState]);

  const toolbarModules = useMemo(
    () => treeViews.canonical.modules.map(m => ({ name: m, nodeCount: forest.allNodes.filter(n => n.module === m && !isTreeFolder(n)).length })),
    [forest, treeViews],
  );

  const viewportKey = `${activeTree}|${activeModule}|${focusNode?.id || ''}`;

  // ------------------------------------------------------------------ 渲染
  return (
    <main>
      <header>
        <Link href="/dashboard" className="brand">
          <span className="brand-icon">学</span>公考 Learning OS
        </Link>
        <nav>
          <Link href="/dashboard">学习概览</Link>
          <Link href="/framework" className="active">
            知识框架
          </Link>
          <Link href="/quiz">行测训练</Link>
          <Link href="/review">到期复习</Link>
          <Link href="/exam">全真模考</Link>
          <Link href="/shenlun">申论工作台</Link>
          <Link href="/importer">题库导入</Link>
        <Link href="/settings">设置</Link></nav>
        <span className="local">● 本地学习空间</span>
      </header>

      <div className="intro dashboard-intro">
        <span className="eyebrow">KNOWLEDGE FRAMEWORK / 知识框架</span>
        <h1>知识地图：看得清，找得到，点得动。</h1>
        <p>点击考点查看学习情况，向 AI 提问、检查理解，或用费曼学习法把知识点讲清楚。</p>
      </div>

      {error && (
        <div role="alert" className="error">
          {error}
          <button type="button" onClick={() => setReloadNonce(n => n + 1)}>
            重试
          </button>
        </div>
      )}
      {loading && <p role="status">正在载入知识框架体系树…</p>}

      {!loading && !error && treeViews.canonical.modules.length === 0 && (
        <div className="fw-empty">暂无知识框架节点。请先导入题库或运行知识框架初始化。</div>
      )}

      {!loading && !error && treeViews.canonical.modules.length > 0 && (
        <div ref={stageRef} className={`fw-stage${isFullscreen ? ' fw-full' : ''}`}>
          <section aria-label="AI学习入口" style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 10, padding: 14, marginBottom: 12, background: '#eef5f0', borderRadius: 10 }}>
            <strong>AI 知识点学习</strong>
            <label htmlFor="map-ai-node">学习考点</label>
            <select id="map-ai-node" value={modState.selectedId || ''} onChange={e => updateModuleState({ selectedId: e.target.value || null })} style={{ maxWidth: '100%', flex: '1 1 220px', minWidth: 0, padding: 8 }}>
              <option value="">选择考点，或直接点击地图节点</option>
              {forest.allNodes.filter(n => n.module === activeModule && !isTreeFolder(n)).map(n => <option key={n.id} value={n.id}>{pathOf(forest, n.id).map(p => p.name).join(' / ')}</option>)}
            </select>
            <button type="button" className="fw-mini fw-mini-strong" disabled={!selectedNode || isTreeFolder(selectedNode)} onClick={() => { setViewMode('map'); setAiFocusNonce(n => n + 1); }}>打开 AI 答疑 / 自查 / 费曼</button>
          </section>
          <FrameworkToolbar
            activeTree={activeTree}
            onTreeChange={setActiveTree}
            modules={toolbarModules}
            activeModule={activeModule}
            onModuleChange={m => {
              setActiveModule(m);
              setSearchText('');
            }}
            search={searchText}
            onSearchChange={setSearchText}
            searchHits={searchHits || []}
            onLocate={locateNode}
            onlyWeak={onlyWeak}
            onToggleWeak={() => updateModuleState(s => ({ onlyWeak: !s.onlyWeak }))}
            weakCount={weakCount}
            viewMode={persist.viewMode}
            onViewModeChange={setViewMode}
            isFullscreen={isFullscreen}
            onToggleFullscreen={toggleFullscreen}
          />

          <div className={`fw-layout${selectedNode ? ' has-detail' : ''}`}>
            <div className="fw-mapcol">
              {persist.viewMode === 'map' ? (
                <div className="fw-mapcard">
                  {displayRoots.length === 0 ? (
                    <div className="fw-empty">{activeTree === 'support' ? '该模块暂无技巧、策略或案例条目，可切回知识与题型树。' : '该模块暂无知识大纲节点。'}</div>
                  ) : onlyWeak && layout.visibleCount === 0 ? (
                    <div className="fw-empty">
                      当前模块没有“待巩固”的考点。
                      <button type="button" className="fw-mini fw-mini-strong" onClick={() => updateModuleState({ onlyWeak: false })}>
                        关闭薄弱点筛选
                      </button>
                    </div>
                  ) : (
                    <KnowledgeMap
                      layout={layout}
                      expanded={modState.expanded}
                      selectedId={modState.selectedId}
                      weakIds={visibleSet ? weakIds : null}
                      highlightId={highlightId}
                      locateRequest={locateRequest}
                      viewportKey={viewportKey}
                      initialViewport={modState.viewport}
                      focusNode={focusNode}
                      onViewportChange={(vp: Viewport) => updateModuleState({ viewport: vp })}
                      onSelect={id => updateModuleState({ selectedId: id })}
                      onToggle={(id, next) => updateModuleState(s => ({ expanded: { ...s.expanded, [id]: next } }))}
                      onClearFocus={() => updateModuleState({ focusId: null })}
                      onFocusParent={() => {
                        if (focusNode?.parent) updateModuleState({ focusId: focusNode.parent.id });
                      }}
                    />
                  )}
                </div>
              ) : (
                <FrameworkListView
                  roots={forest.rootsByModule[activeModule] || []}
                  expanded={modState.expanded}
                  onToggleExpand={id =>
                    updateModuleState(s => ({ expanded: { ...s.expanded, [id]: !(s.expanded[id] ?? false) } }))
                  }
                  onExpandAll={expandAllInModule}
                  onCollapseAll={collapseAllInModule}
                  searchHits={searchHits}
                  selectedId={modState.selectedId}
                  starting={starting}
                  onStartPractice={startPractice}
                  onLocate={locateNode}
                />
              )}
            </div>

            {persist.viewMode === 'map' && selectedNode && isTreeFolder(selectedNode) && (
              <aside className="fw-detail" aria-label="辅助树目录">
                <button type="button" className="fw-mini" onClick={() => updateModuleState({selectedId:null})}>关闭目录</button>
                <h2 className="fw-detail-title">{selectedNode.name}</h2>
                <p>这是分类目录。展开分支或选择下方条目，即可查看原有资料和笔记。</p>
                {selectedNode.children.map(child => <p key={child.id}><button type="button" className="fw-mini" onClick={() => locateNode({node:child,path:[],matchedAlias:null})}>{child.name}</button></p>)}
              </aside>
            )}
            {persist.viewMode === 'map' && selectedNode && !isTreeFolder(selectedNode) && (
              <NodeDetailPanel
                node={selectedNode}
                path={selectedPath}
                subtreeQuestionCount={selectedNode.subtreeQuestionCount}
                starting={starting}
                practiceError={practiceError}
                onStartPractice={startPractice}
                onFocusBranch={id => updateModuleState({ focusId: id })}
                onClose={() => updateModuleState({ selectedId: null })}
                relatedKnowledge={activeTree === 'support' ? (() => {
                  const id = relatedKnowledgeId(selectedNode.id, treeViews);
                  const target = id ? treeViews.knowledge.nodeById.get(id) : null;
                  return target ? {name:target.name, onNavigate:() => locateNode({node:target,path:[],matchedAlias:null})} : undefined;
                })() : undefined}
                relatedSupport={activeTree === 'knowledge' && treeViews.support.rootsByModule[activeModule]?.length ? () => {
                  const target = treeViews.support.rootsByModule[activeModule][0];
                  locateNode({node:target,path:[],matchedAlias:null});
                } : undefined}
                onNavigate={id => {
                  const node = forest.nodeById.get(id);
                  if (node) locateNode({ node, path: pathOf(forest, id).map(n => n.name), matchedAlias: null });
                }}
              />
            )}
          </div>
        </div>
      )}

      <footer style={{ marginTop: 40 }}>
        知识框架 · 交互式知识地图
        <span>{activeTree === 'support' ? '技巧·策略·案例树' : '知识与题型树'} · {forest.allNodes.filter(n => !isTreeFolder(n)).length} 个条目</span>
      </footer>
    </main>
  );
}
