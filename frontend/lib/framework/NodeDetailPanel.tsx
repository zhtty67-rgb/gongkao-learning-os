'use client';

import { useEffect, useMemo, useState } from 'react';
import { NodeQuestionItem, listNotes, saveNote, deleteNote, UserNote } from '../api';
import { InteractiveReviewCard } from '../InteractiveReviewCard';
import { FormattedExplanation } from '../FormattedExplanation';
import {
  FrameworkNode,
  NODE_TYPE_LABEL,
  STATUS_LABEL,
  nodeStatus,
  isAuxiliaryNode,
  parseAliases,
  percentLabel,
} from './model';
import { useNodeQuestions } from './useNodeQuestions';
import { useNodeEvidence, NodeEvidenceItem } from './useNodeEvidence';
import NodeTeacherChat from './NodeTeacherChat';

type QuestionFilter = 'all' | 'error' | 'unpracticed';

const FILTERS: Array<{ key: QuestionFilter; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'error', label: '只看错题' },
  { key: 'unpracticed', label: '只看未刷' },
];

interface NodeDetailPanelProps {
  node: FrameworkNode;
  path: FrameworkNode[];
  subtreeQuestionCount: number | null;
  starting: boolean;
  practiceError: string | null;
  onStartPractice: (nodeId: string) => void;
  onFocusBranch: (nodeId: string) => void;
  onClose: () => void;
  onNavigate: (nodeId: string) => void;
  relatedKnowledge?: { name: string; onNavigate: () => void };
  relatedSupport?: () => void;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('zh-CN');
}

export default function NodeDetailPanel(props: NodeDetailPanelProps) {
  const { node, path, subtreeQuestionCount, starting, practiceError } = props;
  const [questionFilter, setQuestionFilter] = useState<QuestionFilter>('all');
  const [expandedExplanations, setExpandedExplanations] = useState<Record<string, boolean>>({});
  const [expandedReviews, setExpandedReviews] = useState<Record<string, boolean>>({});

  // Node Notes
  const [nodeNotes, setNodeNotes] = useState<UserNote[]>([]);
  const [showAddNote, setShowAddNote] = useState(false);
  const [noteContent, setNoteContent] = useState('');
  const [noteTitle, setNoteTitle] = useState('');
  const [noteSaving, setNoteSaving] = useState(false);
  const [noteError, setNoteError] = useState('');

  const loadNodeNotes = async () => {
    try {
      const res = await listNotes({ knowledge_node_id: node.id, limit: 50 });
      setNodeNotes(res.items || []);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    loadNodeNotes();
  }, [node.id]);

  const handleSaveNodeNote = async () => {
    if (!noteContent.trim()) {
      setNoteError('笔记内容不能为空');
      return;
    }
    setNoteSaving(true);
    setNoteError('');
    try {
      await saveNote({
        note_type: 'knowledge_node',
        title: noteTitle.trim() || undefined,
        content: noteContent.trim(),
        knowledge_node_id: node.id,
        knowledge_node_code: node.knowledge_node_code || undefined,
        module: node.module,
        source_type: 'manual',
      });
      setNoteContent('');
      setNoteTitle('');
      setShowAddNote(false);
      await loadNodeNotes();
    } catch (err: any) {
      setNoteError(err?.message || '保存失败');
    } finally {
      setNoteSaving(false);
    }
  };

  const handleDeleteNodeNote = async (id: string) => {
    if (!window.confirm('确定删除这条考点笔记吗？')) return;
    try {
      await deleteNote(id);
      await loadNodeNotes();
    } catch (err: any) {
      alert(err?.message || '删除失败');
    }
  };

  const questions = useNodeQuestions(node.id);
  const evidence = useNodeEvidence(node.id);

  // 严格身份校验：只有当 hook 状态的 nodeId 确实属于当前展示的 node 时才显示该节点数据，
  // 杜绝快速切换时标题是 A 但资料或题目闪现 B 的错配。
  const isEvidenceCurrent = evidence.state.nodeId === node.id;
  const isQuestionsCurrent = questions.nodeId === node.id;

  const status = nodeStatus(node);
  const auxiliary = isAuxiliaryNode(node);
  const aliases = useMemo(() => parseAliases(node.metadata_json), [node.metadata_json]);
  const directCount = node.direct_question_count || 0;
  const hasPracticeTarget = !auxiliary && ((subtreeQuestionCount ?? directCount) > 0 || directCount > 0);

  const currentQuestions = isQuestionsCurrent ? questions.questions || [] : [];
  const filteredQuestions = useMemo(() => {
    if (questionFilter === 'error') return currentQuestions.filter(q => q.last_correct === false);
    if (questionFilter === 'unpracticed') return currentQuestions.filter(q => q.attempt_count === 0);
    return currentQuestions;
  }, [currentQuestions, questionFilter]);

  return (
    <aside className="fw-detail" aria-label={`考点详情：${node.name}`}>
      <div className="fw-detail-top">
        <nav className="fw-crumb" aria-label="层级路径">
          {path.map((p, i) => (
            <span key={p.id} className="fw-crumb-item">
              {i > 0 && <span aria-hidden="true"> / </span>}
              {i < path.length - 1 ? (
                <button type="button" className="fw-crumb-link" onClick={() => props.onNavigate(p.id)}>
                  {p.name}
                </button>
              ) : (
                <strong aria-current="location">{p.name}</strong>
              )}
            </span>
          ))}
        </nav>
        <button type="button" className="fw-mini" aria-label="关闭详情" title="关闭详情 (Esc)" onClick={props.onClose}>
          ✕
        </button>
      </div>

      <h2 className="fw-detail-title">{node.name}</h2>
      {props.relatedKnowledge && <p><button type="button" className="fw-mini fw-mini-strong" onClick={props.relatedKnowledge.onNavigate}>返回知识树：{props.relatedKnowledge.name}</button></p>}
      {props.relatedSupport && <p><button type="button" className="fw-mini fw-mini-strong" onClick={props.relatedSupport}>查看本模块技巧·策略·案例</button></p>}
      <div className="fw-detail-badges">
        <button type="button" className="fw-mini fw-mini-strong" onClick={() => {
          const section = document.getElementById(`node-ai-${node.id}`);
          section?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          section?.querySelector('textarea')?.focus({ preventScroll: true });
        }}>AI 答疑 / 自查 / 费曼</button>
        <span className="pill">{NODE_TYPE_LABEL[node.node_type] || node.node_type}</span>
        <span className={`fw-status-chip st-${status}`}>
          <i className="fw-dot" aria-hidden="true" />
          {auxiliary ? '辅助学习' : STATUS_LABEL[status]}
        </span>
        {node.children.length > 0 && (
          <button
            type="button"
            className="fw-mini fw-mini-strong"
            title="地图只显示该分支及其子级，可随时返回整体"
            onClick={() => props.onFocusBranch(node.id)}
          >
            ⌖ 聚焦此分支
          </button>
        )}
      </div>

      {node.description && (
        <div className="fw-detail-desc">
          <strong>核心法则 / 公式</strong>
          <p>{node.description}</p>
        </div>
      )}

      <NodeTeacherChat key={node.id} nodeId={node.id} nodeName={node.name} />

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

      {auxiliary ? <section className="fw-detail-section">
        <h3>辅助学习</h3>
        <p>此条目用于阅读方法、策略或案例，不单独计算掌握度。练习请从所属题型或模块进入。</p>
      </section> : <section className="fw-detail-section">
        <h3>学习情况</h3>
        <dl className="fw-stats">
          <div>
            <dt>掌握度</dt>
            <dd>
              {status === 'unpracticed' ? (
                <span className="fw-muted-strong">未练习</span>
              ) : (
                <>
                  {Math.round(node.mastery_score * 100)}%
                  <span className="fw-muted">（{STATUS_LABEL[status]}）</span>
                </>
              )}
            </dd>
          </div>
          <div>
            <dt>练习次数</dt>
            <dd>{node.attempt_count}</dd>
          </div>
          <div>
            <dt>近期正确率</dt>
            <dd>{node.attempt_count > 0 ? percentLabel(node.recent_accuracy) : '—'}</dd>
          </div>
          <div>
            <dt>关联错题</dt>
            <dd className={(node.error_question_count || 0) > 0 ? 'fw-error-num' : ''}>
              {node.error_question_count || 0}
            </dd>
          </div>
          <div>
            <dt>最近练习</dt>
            <dd>{formatDate(node.last_practiced_at)}</dd>
          </div>
        </dl>
        <details className="fw-note" style={{ marginTop: 6 }}>
          <summary style={{ cursor: 'pointer' }}>统计口径说明</summary>
          <p style={{ marginTop: 4 }}>掌握度由作答记录自动重建（较熟练 ≥ 75%）；未练习的考点不显示百分比，避免把“没练过”误读成“掌握低”。</p>
          <p>同一道题可能关联多个考点，子级题量已按题目去重。</p>
          <p>资料绑定与题目关联相互独立：有题目关联不代表有教材依据。</p>
        </details>
      </section>}

      <section className="fw-detail-section">
        <h3>题量</h3>
        <p className="fw-line">
          本考点 <strong>{directCount}</strong> 题
          {typeof subtreeQuestionCount === 'number' && subtreeQuestionCount !== directCount && (
            <>
              {' '}
              · 含子级共 <strong>{subtreeQuestionCount}</strong> 题
            </>
          )}
        </p>
      </section>

      {/* 考点笔记与个人备忘 */}
      <section className="fw-detail-section" style={{ background: '#f8fafc', padding: '12px 14px', borderRadius: 8, border: '1px solid #e2e8f0', marginTop: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <h3 style={{ margin: 0, fontSize: 13, fontWeight: 700, color: '#1e293b', display: 'flex', alignItems: 'center', gap: 4 }}>
            <span>📝</span> 考点笔记（{nodeNotes.length}）
          </h3>
          <button
            type="button"
            className="fw-mini"
            onClick={() => setShowAddNote(!showAddNote)}
            style={{ background: '#fff7ed', borderColor: '#fdba74', color: '#ea580c', fontWeight: 600 }}
          >
            {showAddNote ? '收起' : '记一笔'}
          </button>
        </div>

        {showAddNote && (
          <div style={{ marginBottom: 10, padding: 8, background: '#fff', borderRadius: 6, border: '1px solid #cbd5e1' }}>
            <textarea
              rows={3}
              autoFocus
              placeholder="记录该考点的核心公式、易错陷阱、快速切入技巧..."
              value={noteContent}
              onChange={(e) => setNoteContent(e.target.value)}
              style={{ width: '100%', padding: '6px 8px', fontSize: 12, border: '1px solid #cbd5e1', borderRadius: 4, boxSizing: 'border-box', resize: 'vertical' }}
            />
            <input
              type="text"
              placeholder="主题（可选）"
              value={noteTitle}
              onChange={(e) => setNoteTitle(e.target.value)}
              style={{ width: '100%', padding: '5px 8px', fontSize: 12, border: '1px solid #e2e8f0', borderRadius: 4, marginTop: 6, boxSizing: 'border-box' }}
            />
            {noteError && <div style={{ fontSize: 11, color: '#dc2626', marginTop: 4 }}>⚠️ {noteError}</div>}
            <div style={{ marginTop: 6, display: 'flex', justifyContent: 'flex-end', gap: 6 }}>
              <button type="button" className="fw-mini" onClick={() => setShowAddNote(false)}>取消</button>
              <button
                type="button"
                className="fw-mini fw-mini-strong"
                disabled={noteSaving || !noteContent.trim()}
                onClick={handleSaveNodeNote}
                style={{ background: '#ea580c', color: '#fff', borderColor: '#ea580c' }}
              >
                {noteSaving ? '保存中…' : '保存'}
              </button>
            </div>
          </div>
        )}

        {nodeNotes.length === 0 ? (
          <p style={{ margin: 0, fontSize: 12, color: '#94a3b8' }}>还没有本考点的笔记，点“记一笔”写下第一条。</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {nodeNotes.map((n) => (
              <div key={n.id} style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 6, padding: '8px 10px', fontSize: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ fontSize: 10, padding: '1px 5px', background: '#e0f2fe', color: '#0369a1', borderRadius: 4, fontWeight: 600 }}>
                      {n.note_type === 'question' ? '题目关联' : '考点专属'}
                    </span>
                    {n.title && <strong style={{ color: '#0f172a' }}>{n.title}</strong>}
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDeleteNodeNote(n.id)}
                    style={{ background: 'none', border: 'none', color: '#ef4444', fontSize: 11, cursor: 'pointer' }}
                  >
                    删除
                  </button>
                </div>
                <div style={{ color: '#334155', whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{n.content}</div>
                {n.question_stem && (
                  <div style={{ marginTop: 4, fontSize: 11, color: '#64748b', background: '#f8fafc', padding: '3px 6px', borderRadius: 4 }}>
                    来源原题：{n.question_stem.slice(0, 60)}...
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="fw-detail-section">
        <h3>相关题目</h3>
        <div className="fw-qfilters" role="group" aria-label="题目筛选">
          {FILTERS.map(f => (
            <button
              key={f.key}
              type="button"
              aria-pressed={questionFilter === f.key}
              className={`fw-chip${questionFilter === f.key ? ' on' : ''}`}
              onClick={() => setQuestionFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
          <span className="fw-qtotal">{filteredQuestions.length} 题</span>
        </div>

        {(!isQuestionsCurrent || questions.loading) && <p className="fw-qstate">正在加载考点关联题目…</p>}
        {isQuestionsCurrent && questions.error && (
          <div className="fw-qstate fw-qerror" role="alert">
            <span>题目加载失败：{questions.error}</span>
            <button type="button" className="fw-mini fw-mini-strong" onClick={questions.retry}>
              重试
            </button>
          </div>
        )}
        {isQuestionsCurrent && !questions.loading && !questions.error && currentQuestions.length === 0 && (
          <p className="fw-qstate">该考点暂无关联题目。</p>
        )}
        {isQuestionsCurrent && !questions.loading && !questions.error && filteredQuestions.length === 0 && currentQuestions.length > 0 && (
          <p className="fw-qstate">当前筛选下没有题目。</p>
        )}

        <div className="fw-qlist">
          {filteredQuestions.map(q => {
            const isWrong = q.last_correct === false;
            const isCorrect = q.last_correct === true;
            const notPracticed = q.attempt_count === 0;
            const showExp = !!expandedExplanations[q.id];
            const showReview = !!expandedReviews[q.id];
            const reviewStatusLabel = q.review_is_user_confirmed
              ? '✓ 已确认卡点'
              : q.review_status === 'CORRECTED'
              ? '✎ 用户自述'
              : q.review_status === 'SKIPPED'
              ? '已跳过看解析'
              : 'AI 推测 · 待确认';

            return (
              <article key={q.id} className={`fw-qitem${isWrong ? ' wrong' : ''}`}>
                <div className="fw-qitem-head" style={{ flexWrap: 'wrap', gap: 6 }}>
                  <span className={`fw-qbadge${isCorrect ? ' ok' : ''}${isWrong ? ' bad' : ''}`}>
                    {isCorrect && '✓ 做对过'}
                    {isWrong && `✗ 曾做错 · 上次选 ${q.last_selected_answer}（标答 ${q.answer}）`}
                    {notPracticed && '○ 未练习'}
                  </span>
                  {q.last_submitted_at && (
                    <small style={{ color: '#94a3b8', fontSize: 11 }}>
                      {formatDate(q.last_submitted_at)}
                    </small>
                  )}
                  <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                    {q.last_attempt_id && (
                      <button
                        type="button"
                        className="fw-mini"
                        style={{
                          background: q.has_review ? '#fef3c7' : '#f1f5f9',
                          borderColor: q.has_review ? '#f59e0b' : '#cbd5e1',
                          color: q.has_review ? '#b45309' : '#475569',
                          fontWeight: 600,
                        }}
                        aria-expanded={showReview}
                        onClick={() => setExpandedReviews(prev => ({ ...prev, [q.id]: !prev[q.id] }))}
                      >
                        {showReview ? '收起复盘' : q.has_review ? '💬 查看/继续复盘' : '💬 发起复盘'}
                      </button>
                    )}
                    <button
                      type="button"
                      className="fw-mini"
                      aria-expanded={showExp}
                      onClick={() => setExpandedExplanations(prev => ({ ...prev, [q.id]: !prev[q.id] }))}
                    >
                      {showExp ? '收起解析' : '查看解析'}
                    </button>
                  </div>
                </div>

                <p className="fw-qstem">{q.stem}</p>

                {q.has_review && !showReview && (
                  <div style={{ margin: '6px 0', padding: '6px 10px', background: '#fafaf9', border: '1px solid #e7e5e4', borderRadius: 6, fontSize: 12 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                      <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: q.review_is_user_confirmed ? '#e2f0e6' : '#e0f2fe', color: q.review_is_user_confirmed ? '#166534' : '#0369a1', fontWeight: 600 }}>
                        {reviewStatusLabel}
                      </span>
                      <strong style={{ color: '#44403c' }}>复盘概要：</strong>
                    </div>
                    <span style={{ color: '#57534e' }}>{q.review_summary || q.review_user_self_report || '点击查看/继续对话'}</span>
                  </div>
                )}

                {showExp && (
                  <div style={{ marginTop: 8, padding: '10px 12px', background: '#fafaf9', border: '1px solid #e7e5e4', borderRadius: 8 }}>
                    <FormattedExplanation text={q.explanation} standardAnswer={q.answer} module={q.module} />
                  </div>
                )}

                {showReview && q.last_attempt_id && (
                  <div style={{ marginTop: 8 }}>
                    <InteractiveReviewCard
                      attemptId={q.last_attempt_id}
                      isCorrect={isCorrect}
                      stem={q.stem}
                      module={q.module}
                    />
                  </div>
                )}
              </article>
            );
          })}
        </div>
      </section>

      <section className="fw-detail-section">
        <h3>参考资料</h3>
        {(!isEvidenceCurrent || evidence.state.kind === 'loading' || evidence.state.kind === 'idle') && (
          <p className="fw-qstate">正在加载关联资料…</p>
        )}
        {isEvidenceCurrent && evidence.state.kind === 'ok' && evidence.state.count > 0 && (
          <>
            <p className="fw-note">
              共 <strong>{evidence.state.count}</strong> 段课程或教材摘录。
            </p>
            <div className="fw-evlist">
              {evidence.state.items.map((item: NodeEvidenceItem) => (
                <article key={item.binding_id} className="fw-evitem">
                  <div className="fw-evitem-header">
                    <strong className="fw-evtitle">
                      📄 {item.document_title}
                      {item.page !== null && item.page !== undefined ? ` · P${item.page}` : ''}
                    </strong>
                  </div>

                  {item.citation && <p className="fw-evcitation">{item.citation}</p>}

                  {item.text && (
                    <div className="fw-evtext">
                      <strong className="fw-evtext-label">课程或教材原文：</strong>
                      <p className="fw-evtext-body">{item.text}</p>
                    </div>
                  )}

                  <details className="fw-evdetails">
                    <summary className="fw-evdetails-summary">来源与绑定详情</summary>
                    <div className="fw-evdetails-body">
                      {item.confidence !== null && item.confidence !== undefined && (
                        <p className="fw-evdetail-row">
                          <span className="fw-evdetail-key">考点关联置信度：</span>
                          <strong>{Math.round(item.confidence * 100)}%</strong>
                          <small className="fw-muted">（系统判定的考点与片段关联度，非题目正确率或教材权威度）</small>
                        </p>
                      )}
                      {item.document_version_id && (
                        <p className="fw-evdetail-row">
                          <span className="fw-evdetail-key">文档版本：</span>
                          <span className="fw-monospace">{item.document_version_id}</span>
                        </p>
                      )}
                      {item.source_locator && (
                        <p className="fw-evdetail-row">
                          <span className="fw-evdetail-key">精确来源定位：</span>
                          <span className="fw-monospace" title={item.source_locator}>
                            {item.source_locator}
                          </span>
                        </p>
                      )}
                    </div>
                  </details>
                </article>
              ))}
            </div>
          </>
        )}
        {isEvidenceCurrent && evidence.state.kind === 'ok' && evidence.state.count === 0 && (
          <p className="fw-qstate">该考点暂无教材资料。</p>
        )}
        {isEvidenceCurrent && evidence.state.kind === 'unmapped' && (
          <p className="fw-qstate">该考点暂无教材资料。</p>
        )}
        {isEvidenceCurrent && evidence.state.kind === 'unavailable' && (
          <div className="fw-qstate fw-qerror" role="alert">
            <span>资料暂时无法加载：{evidence.state.message}</span>
            <button type="button" className="fw-mini fw-mini-strong" onClick={evidence.retry}>
              重试
            </button>
          </div>
        )}
      </section>

      <section className="fw-detail-section fw-detail-actions">
        <button
          type="button"
          className="primary"
          disabled={starting || !hasPracticeTarget}
          onClick={() => props.onStartPractice(node.id)}
        >
          {starting ? '正在创建训练…' : '开始专项训练'}
        </button>
        {practiceError && (
          <p className="fw-qerror" role="alert">
            {practiceError}
          </p>
        )}
        <p className="fw-note">专项训练覆盖该考点及其全部子级关联的题目。</p>
      </section>
    </aside>
  );
}

