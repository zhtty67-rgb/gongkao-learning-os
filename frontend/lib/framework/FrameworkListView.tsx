'use client';

import { useState } from 'react';
import { api, NodeQuestionItem } from '../api';
import { FormattedExplanation } from '../FormattedExplanation';
import {
  FrameworkNode,
  NODE_TYPE_LABEL,
  SearchHit,
  STATUS_LABEL,
  ExpandedMap,
  nodeStatus,
  isAuxiliaryNode,
  parseAliases,
} from './model';

type QuestionFilter = 'all' | 'error' | 'unpracticed';

interface FrameworkListViewProps {
  roots: FrameworkNode[];
  expanded: ExpandedMap;
  onToggleExpand: (id: string) => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
  searchHits: SearchHit[] | null;
  selectedId: string | null;
  starting: boolean;
  onStartPractice: (nodeId: string) => void;
  onLocate: (hit: SearchHit) => void;
}

export default function FrameworkListView(props: FrameworkListViewProps) {
  const {
    roots,
    expanded,
    onToggleExpand,
    onExpandAll,
    onCollapseAll,
    searchHits,
    selectedId,
    starting,
    onStartPractice,
    onLocate,
  } = props;

  const [openedQuestionsNode, setOpenedQuestionsNode] = useState<string | null>(null);
  const [nodeQuestions, setNodeQuestions] = useState<Record<string, NodeQuestionItem[]>>({});
  const [questionErrors, setQuestionErrors] = useState<Record<string, string>>({});
  const [loadingQuestions, setLoadingQuestions] = useState(false);
  const [expandedExplanations, setExpandedExplanations] = useState<Record<string, boolean>>({});
  const [questionFilter, setQuestionFilter] = useState<QuestionFilter>('all');

  async function toggleNodeQuestions(nodeId: string) {
    if (openedQuestionsNode === nodeId) {
      setOpenedQuestionsNode(null);
      return;
    }
    setOpenedQuestionsNode(nodeId);
    if (nodeQuestions[nodeId]) return;
    setLoadingQuestions(true);
    try {
      const res = await api<{ node_id: string; total: number; questions: NodeQuestionItem[] }>(
        `/knowledge-nodes/${encodeURIComponent(nodeId)}/questions`,
      );
      setNodeQuestions(prev => ({ ...prev, [nodeId]: res.questions }));
      setQuestionErrors(prev => {
        const next = { ...prev };
        delete next[nodeId];
        return next;
      });
    } catch (err: unknown) {
      setQuestionErrors(prev => ({
        ...prev,
        [nodeId]: err instanceof Error ? err.message : '题目加载失败',
      }));
    } finally {
      setLoadingQuestions(false);
    }
  }

  function renderQuestions(nodeId: string) {
    const list = nodeQuestions[nodeId];
    const error = questionErrors[nodeId];
    const filtered = (list || []).filter(q => {
      if (questionFilter === 'error') return q.last_correct === false;
      if (questionFilter === 'unpracticed') return q.attempt_count === 0;
      return true;
    });
    return (
      <div className="fw-list-qdrawer">
        <div className="fw-list-qhead">
          <strong>考点题目定位与作答状态</strong>
          <div className="fw-qfilters" role="group" aria-label="题目筛选">
            {(['all', 'error', 'unpracticed'] as const).map(f => (
              <button
                key={f}
                type="button"
                aria-pressed={questionFilter === f}
                className={`fw-chip${questionFilter === f ? ' on' : ''}`}
                onClick={() => setQuestionFilter(f)}
              >
                {f === 'all' ? '全部' : f === 'error' ? '只看错题' : '只看未刷'}
              </button>
            ))}
            <span className="fw-qtotal">{filtered.length} 题</span>
          </div>
        </div>

        {loadingQuestions && !list && !error && <p className="fw-qstate">正在加载考点关联题目…</p>}
        {error && (
          <div className="fw-qstate fw-qerror" role="alert">
            <span>题目加载失败：{error}</span>
            <button type="button" className="fw-mini fw-mini-strong" onClick={() => toggleNodeQuestions(nodeId)}>
              重试
            </button>
          </div>
        )}
        {list && list.length === 0 && <p className="fw-qstate">该考点暂无关联题目。</p>}
        {list && list.length > 0 && filtered.length === 0 && <p className="fw-qstate">当前筛选下没有题目。</p>}

        {list &&
          filtered.map(q => {
            const isCorrect = q.last_correct === true;
            const isWrong = q.last_correct === false;
            const notPracticed = q.attempt_count === 0;
            const showExp = !!expandedExplanations[q.id];
            return (
              <article key={q.id} className={`fw-qitem${isWrong ? ' wrong' : ''}`}>
                <div className="fw-qitem-head">
                  <span className={`fw-qbadge${isCorrect ? ' ok' : ''}${isWrong ? ' bad' : ''}`}>
                    {isCorrect && '✓ 做对过'}
                    {isWrong && `✗ 曾做错 · 上次选 ${q.last_selected_answer}（标答 ${q.answer}）`}
                    {notPracticed && '○ 未练习'}
                  </span>
                  <button
                    type="button"
                    className="fw-mini"
                    aria-expanded={showExp}
                    onClick={() => setExpandedExplanations(prev => ({ ...prev, [q.id]: !prev[q.id] }))}
                  >
                    {showExp ? '收起解析' : '查看解析'}
                  </button>
                </div>
                <p className="fw-qstem">{q.stem}</p>
                {showExp && (
                  <div style={{ marginTop: 8, padding: '10px 12px', background: '#fafaf9', border: '1px solid #e7e5e4', borderRadius: 8 }}>
                    <FormattedExplanation text={q.explanation} standardAnswer={q.answer} module={q.module} />
                  </div>
                )}
              </article>
            );
          })}
      </div>
    );
  }

  function renderTreeNode(node: FrameworkNode, depth = 0) {
    const isExpanded = expanded[node.id] ?? depth < 2;
    const hasChildren = node.children.length > 0;
    const aliases = parseAliases(node.metadata_json);
    const status = nodeStatus(node);
    const masteryPercent = Math.round(node.mastery_score * 100);
    const subtreeCount = (node.subtreeQuestionCount ?? node.direct_question_count) || 0;
    const isSelected = selectedId === node.id;

    return (
      <div
        key={node.id}
        className={`fw-list-node${isSelected ? ' selected' : ''}`}
        style={{ marginLeft: depth * 20 }}
        data-list-node-id={node.id}
      >
        <div className="fw-list-card">
          <div className="fw-list-head">
            <div className="fw-list-title">
              {hasChildren ? (
                <button
                  type="button"
                  className="fw-list-toggle"
                  aria-expanded={isExpanded}
                  onClick={() => onToggleExpand(node.id)}
                  title={isExpanded ? '折叠' : '展开'}
                >
                  {isExpanded ? '▼' : '▶'}
                </button>
              ) : (
                <span className="fw-list-leafdot" aria-hidden="true">
                  ●
                </span>
              )}
              <span className={`fw-list-name d${Math.min(depth, 2)}`}>{node.name}</span>
              <span className="pill">{NODE_TYPE_LABEL[node.node_type] || node.node_type}</span>
              <span className={`fw-status-chip st-${status}`}>
                <i className="fw-dot" aria-hidden="true" />
                {isAuxiliaryNode(node) ? '辅助学习' : STATUS_LABEL[status]}
                {!isAuxiliaryNode(node) && status !== 'unpracticed' && ` ${masteryPercent}%`}
              </span>
              {subtreeCount > 0 ? (
                <span className="fw-list-count">{subtreeCount} 题（去重）</span>
              ) : (
                <span className="fw-list-count zero">0 题</span>
              )}
              {(node.error_question_count || 0) > 0 && (
                <span className="fw-list-errbadge">⚠ {node.error_question_count} 错题待攻克</span>
              )}
            </div>

            <div className="fw-list-actions">
              {subtreeCount > 0 && (
                <button type="button" className="fw-mini" onClick={() => toggleNodeQuestions(node.id)}>
                  {openedQuestionsNode === node.id ? '▲ 收起' : '📑 查漏补缺'}
                </button>
              )}
              {subtreeCount > 0 && !isAuxiliaryNode(node) && (
                <button type="button" className="fw-mini fw-mini-strong" disabled={starting} onClick={() => onStartPractice(node.id)}>
                  🎯 专项练
                </button>
              )}
            </div>
          </div>

          {node.description && (
            <div className="fw-list-desc">
              <strong>💡 核心法则 / 公式：</strong>
              {node.description}
            </div>
          )}

          {aliases.length > 0 && (
            <div className="fw-detail-aliases">
              <span className="fw-detail-label">别名</span>
              <div className="fw-alias-chips">
                {aliases.map(a => (
                  <span key={a} className="fw-alias">
                    {a}
                  </span>
                ))}
              </div>
            </div>
          )}

          {openedQuestionsNode === node.id && renderQuestions(node.id)}
        </div>

        {hasChildren && isExpanded && (
          <div className="fw-list-children">{node.children.map(child => renderTreeNode(child, depth + 1))}</div>
        )}
      </div>
    );
  }

  if (searchHits) {
    return (
      <div className="card fw-listcard">
        <div className="fw-list-toolbar">
          <span className="muted">
            搜索到 <strong>{searchHits.length}</strong> 个相关考点，点击结果在列表中定位并选中。
          </span>
        </div>
        {searchHits.length === 0 ? (
          <div className="fw-empty">未找到匹配的知识考点、别名或说明。</div>
        ) : (
          searchHits.map(hit => (
            <div key={hit.node.id} className="fw-list-card">
              <div className="fw-list-head">
                <div className="fw-list-title">
                  <span className="fw-list-name d1">{hit.node.name}</span>
                  <span className="pill">{hit.node.module}</span>
                  <span className="fw-searchdrop-path">{hit.path.slice(0, -1).join(' / ') || '根节点'}</span>
                </div>
                <div className="fw-list-actions">
                  <button type="button" className="fw-mini" onClick={() => onLocate(hit)}>
                    在列表中定位
                  </button>
                  {((hit.node.subtreeQuestionCount ?? hit.node.direct_question_count) || 0) > 0 && (
                    <button type="button" className="fw-mini fw-mini-strong" disabled={starting} onClick={() => onStartPractice(hit.node.id)}>
                      🎯 专项练
                    </button>
                  )}
                </div>
              </div>
              {hit.node.description && (
                <div className="fw-list-desc">
                  <strong>💡</strong> {hit.node.description}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    );
  }

  return (
    <div className="card fw-listcard">
      <div className="fw-list-toolbar">
        <button type="button" className="fw-mini" onClick={onExpandAll}>
          全部展开
        </button>
        <button type="button" className="fw-mini" onClick={onCollapseAll}>
          全部折叠
        </button>
      </div>
      {roots.length === 0 ? (
        <div className="fw-empty">该模块暂无知识大纲节点。</div>
      ) : (
        roots.map(rootNode => renderTreeNode(rootNode, 0))
      )}
    </div>
  );
}
