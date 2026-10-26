'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '../../lib/api';

type MasteryNode = { id: string; name: string; module: string | null; parent_id: string | null; mastery_score: number | null; attempt_count: number | null };

type StudyTask = {
  id: string;
  task_type: 'knowledge_card' | 'self_check';
  title: string | null;
  content: string;
  detail: { reference_answer?: string | null; rubric?: string | null; truncated?: boolean };
  source_kind: 'original_excerpt' | 'ai_summary' | 'ai_generated';
  source_kind_label: string;
  provenance: Record<string, any>;
  status: 'draft' | 'published' | 'done' | 'skipped';
  result: Record<string, any> | null;
  done_at: string | null;
};

type StudySet = {
  id: string;
  knowledge_node_id: string | null;
  knowledge_node_code: string | null;
  title: string;
  status: 'draft' | 'published' | 'archived';
  source_document_title: string | null;
  provenance: { evidence?: Array<Record<string, any>> };
  generation_status: string;
  generation_note: string | null;
  created_at: string;
  published_at: string | null;
  task_count: number;
  done_count: number;
  tasks?: StudyTask[];
};

const SOURCE_KIND_COLOR: Record<string, string> = {
  original_excerpt: '#8a6d3b',
  ai_summary: '#296044',
  ai_generated: '#5b5ea6',
};

function provenanceLine(p: Record<string, any>): string {
  if (!p || !Object.keys(p).length) return '无出处记录';
  if (p.source === 'local_course') return `本地课程《${p.file ?? '?'}》· ${p.locator ?? ''}${p.sha256 ? ` · sha256:${String(p.sha256).slice(0, 8)}` : ''}`;
  if (p.source === 'knowledge_hub') return `教材《${p.document_title ?? '?'}》${p.page ? ` 第${p.page}页` : ''}${p.citation ? ` · ${p.citation}` : ''}`;
  if (p.source === 'mixed') return '多片段综合（无单一出处）';
  return '出处见任务集证据清单';
}

export default function StudyTasksPage() {
  const [nodes, setNodes] = useState<MasteryNode[]>([]);
  const [moduleFilter, setModuleFilter] = useState('');
  const [search, setSearch] = useState('');
  const [selectedNode, setSelectedNode] = useState<MasteryNode | null>(null);
  const [sets, setSets] = useState<StudySet[]>([]);
  const [activeSet, setActiveSet] = useState<StudySet | null>(null);
  const [generating, setGenerating] = useState<'ai' | 'excerpt' | null>(null);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err' | 'info'; text: string } | null>(null);
  const [editing, setEditing] = useState<StudyTask | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busyTask, setBusyTask] = useState<string | null>(null);

  const loadSets = useCallback(async (nodeId?: string) => {
    try {
      const query = nodeId ? `?node_id=${encodeURIComponent(nodeId)}` : '';
      const data = await api<{ sets: StudySet[] }>(`/study/sets${query}`);
      setSets(data.sets);
    } catch (exc) {
      setMsg({ type: 'err', text: exc instanceof ApiError ? exc.message : '任务集读取失败。' });
    }
  }, []);

  const loadSetDetail = useCallback(async (setId: string) => {
    try {
      const doc = await api<StudySet>(`/study/sets/${setId}`);
      setActiveSet(doc);
    } catch (exc) {
      setMsg({ type: 'err', text: exc instanceof ApiError ? exc.message : '任务集读取失败。' });
    }
  }, []);

  useEffect(() => {
    api<{ mastery: { nodes: MasteryNode[] } }>('/mastery')
      .then(d => setNodes(d.mastery.nodes.filter(n => n.parent_id !== null)))
      .catch(() => setMsg({ type: 'err', text: '知识节点读取失败，请确认后端已启动。' }));
    loadSets();
  }, [loadSets]);

  const modules = useMemo(
    () => Array.from(new Set(nodes.map(n => n.module).filter(Boolean) as string[])),
    [nodes],
  );
  const filteredNodes = useMemo(() => {
    const kw = search.trim();
    return nodes
      .filter(n => !moduleFilter || n.module === moduleFilter)
      .filter(n => !kw || n.name.includes(kw))
      .slice(0, 200);
  }, [nodes, moduleFilter, search]);

  const generate = async (mode: 'ai' | 'excerpt') => {
    if (!selectedNode) return;
    setGenerating(mode);
    setMsg(null);
    try {
      const res = await api<{ status: string; message?: string; set_id?: string }>(
        '/study/sets/generate',
        { node_id: selectedNode.id, excerpt_only: mode === 'excerpt' },
      );
      if (res.status === 'ok' && res.set_id) {
        setMsg({ type: 'ok', text: '草稿已生成，请预览与修订后发布。' });
        await loadSets(selectedNode.id);
        await loadSetDetail(res.set_id);
      } else {
        setMsg({ type: 'info', text: res.message || '暂无法生成，请换一个考点或稍后重试。' });
      }
    } catch (exc) {
      setMsg({ type: 'err', text: exc instanceof ApiError ? exc.message : '生成失败，请稍后重试。' });
    } finally {
      setGenerating(null);
    }
  };

  const patchTask = async (task: StudyTask, body: Record<string, unknown>) => {
    setBusyTask(task.id);
    try {
      await fetch(`/api/study/tasks/${task.id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then(async r => {
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || '保存失败');
      });
      setEditing(null);
      if (activeSet) await loadSetDetail(activeSet.id);
    } catch (exc: any) {
      setMsg({ type: 'err', text: exc.message || '保存失败' });
    } finally {
      setBusyTask(null);
    }
  };

  const deleteTask = async (task: StudyTask) => {
    if (!window.confirm('删除该草稿条目？')) return;
    setBusyTask(task.id);
    try {
      await fetch(`/api/study/tasks/${task.id}`, { method: 'DELETE' }).then(async r => {
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || '删除失败');
      });
      if (activeSet) await loadSetDetail(activeSet.id);
    } catch (exc: any) {
      setMsg({ type: 'err', text: exc.message || '删除失败' });
    } finally {
      setBusyTask(null);
    }
  };

  const setAction = async (setId: string, action: 'publish' | 'archive') => {
    if (action === 'publish' && !window.confirm('发布后内容锁定（可作答/跳过，不可再编辑）。确认发布？')) return;
    try {
      await api(`/study/sets/${setId}/${action}`, {});
      await loadSets(selectedNode?.id);
      await loadSetDetail(setId);
      if (action === 'publish') setMsg({ type: 'ok', text: '已发布，可以开始自查了。' });
    } catch (exc) {
      setMsg({ type: 'err', text: exc instanceof ApiError ? exc.message : '操作失败' });
    }
  };

  const answerTask = async (task: StudyTask, understood?: boolean) => {
    const text = (answers[task.id] || '').trim();
    if (!text) { setMsg({ type: 'info', text: '先写下你的回答再提交。' }); return; }
    setBusyTask(task.id);
    try {
      await api(`/study/tasks/${task.id}/answer`, { answer: text, understood });
      setAnswers(prev => ({ ...prev, [task.id]: '' }));
      if (activeSet) await loadSetDetail(activeSet.id);
    } catch (exc) {
      setMsg({ type: 'err', text: exc instanceof ApiError ? exc.message : '提交失败' });
    } finally {
      setBusyTask(null);
    }
  };

  const skipTask = async (task: StudyTask) => {
    setBusyTask(task.id);
    try {
      await api(`/study/tasks/${task.id}/skip`, { reason: 'user_skip' });
      if (activeSet) await loadSetDetail(activeSet.id);
    } catch (exc) {
      setMsg({ type: 'err', text: exc instanceof ApiError ? exc.message : '操作失败' });
    } finally {
      setBusyTask(null);
    }
  };

  const statusLabel: Record<string, string> = { draft: '草稿', published: '进行中', archived: '已归档', done: '已完成', skipped: '已跳过' };

  return (
    <main>
      <header>
        <Link href="/dashboard" className="brand"><span className="brand-icon">学</span>公考 Learning OS</Link>
        <nav>
          <Link href="/dashboard">学习概览</Link><Link href="/framework">知识框架</Link><Link href="/study" className="active">学习任务</Link><Link href="/teaching">自适应教学</Link><Link href="/quiz">行测训练</Link><Link href="/review">到期复习</Link><Link href="/notes">我的笔记</Link><Link href="/settings">系统设置</Link>
        </nav>
        <span className="local">● 本地学习空间</span>
      </header>

      <section className="dashboard-section">
        <div className="section-heading"><h2>资料转学习任务</h2></div>
        <p className="intro">
          从考点已有资料（本地课程逐字稿 / Knowledge Hub 教材）生成<b>有出处的知识卡</b>与<b>自查题</b>：
          草稿可预览修订，确认后发布。三类内容明确标注——<span className="pill" style={{ color: SOURCE_KIND_COLOR.original_excerpt }}>原文摘录</span>
          <span className="pill" style={{ color: SOURCE_KIND_COLOR.ai_summary }}>AI 整理</span>
          <span className="pill" style={{ color: SOURCE_KIND_COLOR.ai_generated }}>AI 自编题</span>。学习任务不计入掌握度，理解以正式作答为准。
        </p>
        {msg && (
          <div className={msg.type === 'err' ? 'error' : 'feedback-card'} style={{ marginBottom: 12 }}>
            {msg.text}
          </div>
        )}

        <div className="card" style={{ padding: 14, marginBottom: 16 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <select value={moduleFilter} onChange={e => setModuleFilter(e.target.value)} style={{ padding: '6px 10px' }}>
              <option value="">全部模块</option>
              {modules.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
            <input placeholder="搜索考点名称…" value={search} onChange={e => setSearch(e.target.value)} style={{ padding: '6px 10px', minWidth: 200 }} />
            <span className="pill">{filteredNodes.length} 个考点</span>
            {selectedNode && <span className="pill">已选：{selectedNode.name}（{selectedNode.module}）</span>}
          </div>
          <div style={{ maxHeight: 180, overflowY: 'auto', marginTop: 10, border: '1px solid var(--line)', borderRadius: 8 }}>
            {filteredNodes.map(n => (
              <button key={n.id} onClick={() => { setSelectedNode(n); loadSets(n.id); }}
                className={selectedNode?.id === n.id ? 'primary' : ''} style={{ display: 'block', width: '100%', textAlign: 'left', padding: '7px 12px', border: 0, borderBottom: '1px solid var(--line)', background: selectedNode?.id === n.id ? 'var(--accent)' : 'transparent', color: selectedNode?.id === n.id ? '#fff' : 'inherit' }}>
                {n.name} <span style={{ opacity: 0.65, fontSize: 12 }}>· {n.module}{n.attempt_count ? ` · ${n.attempt_count} 次作答` : ' · 未练习'}</span>
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button className="primary" disabled={!selectedNode || generating !== null} onClick={() => generate('ai')}>
              {generating === 'ai' ? '正在生成草稿…' : '生成学习草稿（AI 卡片 + 自查题）'}
            </button>
            <button disabled={!selectedNode || generating !== null} onClick={() => generate('excerpt')}>
              {generating === 'excerpt' ? '正在生成…' : '仅原文摘录（零模型）'}
            </button>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, 1fr) minmax(320px, 2fr)', gap: 16, alignItems: 'start' }}>
          <div className="card" style={{ padding: 12 }}>
            <h3 style={{ margin: '0 0 8px' }}>任务集{selectedNode ? ` · ${selectedNode.name}` : ''}</h3>
            {sets.length === 0 && <div className="empty-state">还没有任务集。选择考点后生成。</div>}
            {sets.map(s => (
              <button key={s.id} onClick={() => loadSetDetail(s.id)}
                style={{ display: 'block', width: '100%', textAlign: 'left', padding: 10, marginBottom: 8, border: activeSet?.id === s.id ? '1px solid var(--accent)' : '1px solid var(--line)', borderRadius: 8, background: 'transparent', cursor: 'pointer' }}>
                <div style={{ fontWeight: 600 }}>{s.title}</div>
                <div style={{ fontSize: 12, opacity: 0.75, marginTop: 4 }}>
                  <span className="pill">{statusLabel[s.status]}</span> {s.done_count}/{s.task_count} 完成
                  {s.generation_note ? ` · ${s.generation_note}` : ''}
                </div>
              </button>
            ))}
          </div>

          <div>
            {!activeSet && <div className="card empty-state" style={{ padding: 24 }}>左侧选择一个任务集查看内容。</div>}
            {activeSet && (
              <div className="card" style={{ padding: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'start', flexWrap: 'wrap' }}>
                  <div>
                    <h3 style={{ margin: 0 }}>{activeSet.title}</h3>
                    <div style={{ fontSize: 12, opacity: 0.75, marginTop: 4 }}>
                      <span className="pill">{statusLabel[activeSet.status]}</span>
                      {' '}完成 {activeSet.done_count}/{activeSet.task_count}
                      {activeSet.source_document_title ? ` · 来源：${activeSet.source_document_title}` : ''}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    {activeSet.status === 'draft' && <button className="primary" onClick={() => setAction(activeSet.id, 'publish')}>确认发布</button>}
                    {activeSet.status !== 'archived' && <button onClick={() => setAction(activeSet.id, 'archive')}>归档</button>}
                  </div>
                </div>
                {activeSet.provenance?.evidence?.length ? (
                  <details style={{ marginTop: 10, fontSize: 13 }}>
                    <summary style={{ cursor: 'pointer', opacity: 0.8 }}>证据清单（{activeSet.provenance.evidence.length} 条，出处可核验）</summary>
                    <ul style={{ margin: '6px 0', paddingLeft: 18 }}>
                      {activeSet.provenance.evidence.map((e, i) => (
                        <li key={i} style={{ marginBottom: 4 }}>{provenanceLine(e)}：{(e.excerpt_head || '').slice(0, 60)}…</li>
                      ))}
                    </ul>
                  </details>
                ) : null}

                <div style={{ marginTop: 12 }}>
                  {activeSet.tasks?.map(t => (
                    <div key={t.id} style={{ border: '1px solid var(--line)', borderRadius: 10, padding: 12, marginBottom: 10, opacity: t.status === 'skipped' ? 0.55 : 1 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                          <span className="pill" style={{ color: SOURCE_KIND_COLOR[t.source_kind] }}>{t.source_kind_label}</span>
                          <span className="pill">{t.task_type === 'self_check' ? '自查题' : '知识卡'}</span>
                          <span className="pill">{statusLabel[t.status]}</span>
                        </div>
                        {activeSet.status === 'draft' && (
                          <div style={{ display: 'flex', gap: 6 }}>
                            <button disabled={busyTask === t.id} onClick={() => { setEditing(t); setEditTitle(t.title || ''); setEditContent(t.content); }}>编辑</button>
                            <button disabled={busyTask === t.id} onClick={() => deleteTask(t)}>删除</button>
                          </div>
                        )}
                      </div>
                      <div style={{ fontWeight: 600, margin: '8px 0 4px' }}>{t.title}</div>
                      <div style={{ whiteSpace: 'pre-wrap', fontSize: 14 }}>{t.content}</div>
                      <div style={{ fontSize: 12, opacity: 0.7, marginTop: 6 }}>出处：{provenanceLine(t.provenance)}</div>

                      {t.task_type === 'self_check' && t.status === 'published' && (
                        <div style={{ marginTop: 10, borderTop: '1px dashed var(--line)', paddingTop: 10 }}>
                          {t.detail.rubric && <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 6 }}>自评依据：{t.detail.rubric}</div>}
                          <textarea value={answers[t.id] || ''} onChange={e => setAnswers(prev => ({ ...prev, [t.id]: e.target.value }))}
                            placeholder="用自己的话作答（理解与应用，不背原文）" rows={3} style={{ width: '100%', padding: 8 }} />
                          <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                            <button className="primary" disabled={busyTask === t.id} onClick={() => answerTask(t, true)}>已理解，提交</button>
                            <button disabled={busyTask === t.id} onClick={() => answerTask(t, false)}>还不太确定，提交</button>
                            <button disabled={busyTask === t.id} onClick={() => skipTask(t)}>跳过</button>
                          </div>
                        </div>
                      )}
                      {t.status === 'done' && t.result && (
                        <div style={{ marginTop: 10, borderTop: '1px dashed var(--line)', paddingTop: 10, fontSize: 13 }}>
                          <div>你的回答：{t.result.user_answer}{t.result.understood === false ? '（自评：未完全理解）' : ''}</div>
                          {t.result.reference_answer && <div style={{ marginTop: 4, opacity: 0.85 }}>参考答案：{t.result.reference_answer}</div>}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      {editing && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div className="card" style={{ padding: 18, width: 'min(680px, 92vw)', maxHeight: '86vh', overflowY: 'auto' }}>
            <h3 style={{ marginTop: 0 }}>编辑草稿条目</h3>
            <label style={{ fontSize: 13 }}>标题<input value={editTitle} onChange={e => setEditTitle(e.target.value)} style={{ width: '100%', padding: 8, margin: '4px 0 10px' }} /></label>
            <label style={{ fontSize: 13 }}>内容<textarea value={editContent} onChange={e => setEditContent(e.target.value)} rows={10} style={{ width: '100%', padding: 8 }} /></label>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 10 }}>
              <button onClick={() => setEditing(null)}>取消</button>
              <button className="primary" disabled={busyTask === editing.id}
                onClick={() => patchTask(editing, { title: editTitle, content: editContent })}>保存</button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
