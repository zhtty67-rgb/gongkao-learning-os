'use client';
import { TeachingContent } from '../TeachingContent';

import { useEffect, useRef, useState } from 'react';
import { api } from '../api';

type LearningMode = 'concept' | 'breakthrough' | 'qa' | 'self_check' | 'feynman' | 'socratic';
type Teacher = { teacher_id: string; name: string };
type Answer = {
  node_id: string; teacher: Teacher | null; content: string; status: 'completed' | 'failed';
  policies: { policy_id: string; name: string }[];
  knowledge_source: { status: string; candidate_count: number };
  phase?: 'hint' | 'explain' | 'direct' | 'transfer' | 'check_transfer';
  session_id?: string; assistant_turn_id?: string; mode?: LearningMode;
};
type Turn = { role: 'user' | 'assistant'; content: string; answer?: Answer; request?: { mode: LearningMode; phase: Answer['phase'] }; turnId?: string; restored?: boolean };
type SessionDetail = { id: string; mode: string; status: string; turns: Array<{ id: string; role: 'user' | 'assistant'; content: string; status: string }> };

export default function NodeTeacherChat({ nodeId, nodeName }: { nodeId: string; nodeName: string }) {
  const [context, setContext] = useState<{ available: boolean; ai_available?: boolean; teacher: Teacher | null } | null>(null);
  const [contextError, setContextError] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState('');
  const [mode, setMode] = useState<LearningMode>('qa');
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const alive = useRef(true);
  const endpoint = `/knowledge-nodes/${encodeURIComponent(nodeId)}/teacher-chat`;
  const guided = mode === 'breakthrough' || mode === 'concept';
  const available = guided ? context?.available : context?.ai_available;
  const lastPhase = [...turns].reverse().find(t => t.answer?.status === 'completed')?.answer?.phase;
  const stage = lastPhase === 'hint' ? 'retry' : lastPhase === 'transfer' || lastPhase === 'check_transfer' ? 'transfer' : lastPhase === 'explain' || lastPhase === 'direct' ? 'complete' : 'thought';

  // 模式切换：从服务端恢复该 考点+模式 的最近会话（跨浏览器/设备）
  useEffect(() => {
    alive.current = true;
    setTurns([]); setInput(''); setSessionId(null); setNotice('');
    api<{ sessions: Array<{ id: string; status: string }> }>(`/knowledge-nodes/${encodeURIComponent(nodeId)}/teaching-sessions?mode=${mode}`)
      .then(async data => {
        if (!alive.current) return;
        const latest = data.sessions[0];
        if (!latest) return;
        const detail = await api<SessionDetail>(`/teaching-node/sessions/${latest.id}`);
        if (!alive.current || detail.id !== latest.id) return;
        setSessionId(detail.id);
        setTurns(detail.turns.slice(-20).map(t => ({
          role: t.role, content: t.content, turnId: t.id, restored: true,
          answer: t.role === 'assistant' ? {
            node_id: nodeId, teacher: null, content: t.content,
            status: t.status === 'failed' ? 'failed' : 'completed',
            policies: [], knowledge_source: { status: 'restored', candidate_count: 0 },
          } : undefined,
        })));
      })
      .catch(() => { /* 服务端会话读取失败：从新会话开始，不影响使用 */ });
  }, [nodeId, mode]);

  useEffect(() => {
    alive.current = true; setContext(null); setContextError('');
    api<{ available: boolean; ai_available?: boolean; teacher: Teacher | null }>(endpoint)
      .then(value => { if (alive.current) setContext(value); })
      .catch((err: unknown) => { if (alive.current) setContextError(err instanceof Error ? err.message : '无法加载知识点信息'); });
    return () => { alive.current = false; };
  }, [endpoint]);

  const saveTurns = (value: Turn[]) => setTurns(value.slice(-40));

  async function send(question = input, requestMode = mode, phase: Answer['phase'] = guided ? (stage === 'thought' ? 'hint' : stage === 'retry' ? 'explain' : stage === 'transfer' ? 'check_transfer' : 'direct') : undefined) {
    let text = question.trim();
    if (!text) {
      if (guided && stage === 'thought') text = '请给出核心解题思路与提示引导。';
      else if (guided && stage === 'retry') text = '请给出考点完整解析与易错边界。';
      else return;
    }
    if (busy || !available) return;
    const before = turns;
    const userTurn: Turn = { role: 'user', content: text, request: { mode: requestMode, phase } };
    saveTurns([...before, userTurn]);
    setInput(''); setBusy(true); setNotice('');
    try {
      const answer = await api<Answer>(endpoint, {
        message: text, mode: requestMode, phase,
        session_id: sessionId || undefined,
        history: before.filter(t => t.answer?.status !== 'failed').slice(-8).map(t => ({ role: t.role, content: t.content.slice(0, 8000) })),
      });
      if (!alive.current || answer.node_id !== nodeId) return;
      if (answer.session_id) setSessionId(answer.session_id);
      saveTurns([...before, userTurn, { role: 'assistant', content: answer.content, answer, turnId: answer.assistant_turn_id }]);
    } catch (err: unknown) {
      if (!alive.current) return;
      const content = err instanceof Error ? err.message : '回答暂不可用，请重试';
      saveTurns([...before, userTurn, { role: 'assistant', content, answer: { node_id: nodeId, teacher: context?.teacher || null, content, status: 'failed', phase, policies: [], knowledge_source: { status: 'unavailable', candidate_count: 0 } } }]);
    } finally { if (alive.current) setBusy(false); }
  }

  async function closeAndRestart() {
    if (sessionId) { try { await api(`/teaching-node/sessions/${sessionId}/close`, {}); } catch { /* 已结束时忽略 */ } }
    setSessionId(null); setTurns([]); setNotice('已结束本次教学会话，下次提问将开始新会话。');
  }

  async function toTask(turn: Turn) {
    if (!turn.turnId) return;
    setBusy(true); setNotice('');
    try {
      await api(`/teaching-node/turns/${turn.turnId}/to-task`, {});
      setNotice('已转为学习任务（教学沉淀·待验证），可在「学习任务」页作答确认。');
    } catch (err: unknown) {
      setNotice(err instanceof Error ? err.message : '转任务失败，请重试。');
    } finally { if (alive.current) setBusy(false); }
  }

  return <section id={`node-ai-${nodeId}`} className="fw-detail-section" aria-label="AI 知识点学习">
    <h3>AI 知识点学习</h3>
    <p className="fw-muted">{context?.teacher ? `${context.teacher.name} · ${nodeName}` : contextError || (context ? `知识点助教 · ${nodeName}` : '正在加载知识点…')}</p>
    {context && <>
      {guided && <p className="fw-muted">{stage === 'thought' ? '① 先说你的理解或解题思路，教师只给必要提示。' : stage === 'retry' ? '② 根据提示重新表述或作答，再查看完整讲解。' : stage === 'complete' ? '③ 已展开讲解，可用新变式检查理解。' : '④ 独立回答新变式，并说明理由。'}</p>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '10px 0' }} aria-label="AI学习方式">
        {([{ key: 'qa', label: '知识点答疑' }, { key: 'self_check', label: '知识点自查' }, { key: 'feynman', label: '费曼学习法' }, { key: 'socratic', label: '苏格拉底追问' }, { key: 'breakthrough', label: '专项突破' }] as const).map(item => <button key={item.key} className="fw-mini" aria-pressed={mode === item.key} style={{ background: mode === item.key ? '#e0f2fe' : undefined }} onClick={() => setMode(item.key)} disabled={busy}>{item.label}</button>)}
      </div>
      {!guided && <p className="fw-muted">{mode === 'qa' ? '哪里不懂就直接问，结合当前考点解释概念、条件和例子。' : mode === 'self_check' ? '一次检查一个问题，先独立作答，再看反馈并修正。' : mode === 'socratic' ? '严格追问练习：每轮一个关键问题，不抢先给答案；卡住可要提示，说「直接讲」给要点，可随时结束并总结疑点。' : '把知识点讲给初学者听：用自己的话解释、举例，再根据反馈找缺口并重讲。'}</p>}
      {mode === 'breakthrough' && !context.available && <p role="status">该考点未配置专项教师，可使用答疑、自查和费曼练习。</p>}
      {available && !guided && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {mode === 'qa' ? ['这个知识点是什么意思？', '有哪些适用条件和易混点？', '能用一个简单例子解释吗？'].map(question => <button key={question} className="fw-mini" disabled={busy} onClick={() => setInput(question)}>{question}</button>) : <button className="fw-mini fw-mini-strong" disabled={busy} onClick={() => void send(mode === 'self_check' ? `请围绕「${nodeName}」开始知识点自查，一次一道题，先等我作答。` : mode === 'socratic' ? `请围绕「${nodeName}」开始苏格拉底追问练习，先出第一个关键问题。` : `请陪我练习「${nodeName}」的费曼学习法，先请我用自己的话讲解。`)}>{turns.length ? mode === 'self_check' ? '再检查一个问题' : '重新开始讲解' : mode === 'self_check' ? '开始知识点自查' : mode === 'socratic' ? '开始追问练习' : '开始费曼练习'}</button>}
      </div>}
      <div aria-live="polite" style={{ maxHeight: 420, overflowY: 'auto', margin: '12px 0' }}>
        {turns.map((turn, i) => <div key={i} style={{ margin: '8px 0', padding: 10, borderRadius: 8, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', background: turn.role === 'user' ? '#eff6ff' : turn.answer?.status === 'failed' ? '#fef2f2' : '#f8fafc', fontSize: 13, lineHeight: 1.7 }}>
          <strong>{turn.role === 'user' ? '我的问题' : turn.answer?.status === 'failed' ? '本次回答未完成' : 'AI 学习助教'}</strong>
          <TeachingContent text={turn.content} />
          {turn.answer?.status === 'completed' && !turn.restored && <>
            <small className="fw-muted">{turn.answer.knowledge_source.candidate_count > 0 ? `检索到 ${turn.answer.knowledge_source.candidate_count} 条相关教材片段，具体引用见回答。` : (context.teacher ? '本次未获得可用教材片段，依据当前知识树与匹配教师规则回答。' : '本次未获得可用教材片段，依据当前知识树回答；没有专项教师规则。')}</small>
            {turn.answer.policies.length > 0 && <details><summary>本次提供的教师规则</summary>{turn.answer.policies.map(p => <p key={p.policy_id}>{p.name}（{p.policy_id}）</p>)}</details>}
          </>}
          {turn.restored && <small className="fw-muted">（历史轮次·自动恢复）</small>}
          {turn.role === 'assistant' && turn.answer?.status === 'completed' && turn.turnId && !turn.restored && <button className="fw-mini" style={{ marginTop: 6 }} disabled={busy} onClick={() => void toTask(turn)}>把这条疑点/追问转为学习任务</button>}
          {turn.answer?.status === 'failed' && i === turns.length - 1 && <button className="fw-mini" disabled={busy} onClick={() => void send(turns[i - 1]?.content || input, turns[i - 1]?.request?.mode || mode, turns[i - 1]?.request?.phase)}>重试提问</button>}
        </div>)}
        {busy && <p className="fw-muted">教师正在回答…</p>}
      </div>
      <form onSubmit={e => { e.preventDefault(); void send(); }}>
        <label htmlFor={`teacher-question-${nodeId}`}>{!guided ? mode === 'feynman' ? '用自己的话讲解' : mode === 'self_check' ? '你的作答与理由' : mode === 'socratic' ? '你的回答（或：不会／直接讲／结束练习）' : '你不懂的地方' : stage === 'thought' ? '先说理解、思路或卡点（选填）' : stage === 'retry' ? '修改后的理解或作答理由（选填）' : stage === 'transfer' ? '新变式的答案与理由' : '继续向教师提问'}</label>
        <textarea id={`teacher-question-${nodeId}`} value={input} onChange={e => setInput(e.target.value)} maxLength={2000} rows={4} disabled={busy || !available} placeholder={mode === 'feynman' ? '我会这样讲：它是什么、什么时候能用、举个例子……' : mode === 'socratic' ? '先开始练习；回答问题时写下你的思考；卡住可回复「提示」或「直接讲」。' : mode === 'self_check' ? '先开始自查，再写下你的答案和理由。' : !guided ? '例如：这个公式什么时候能用？我总混淆哪两个条件？' : stage === 'thought' ? '可写下你的思路或卡点（选填，也可留空直接获取提示）。' : '可写下修改依据（选填，也可留空直接展开讲解）。'} style={{ width: '100%', boxSizing: 'border-box', margin: '6px 0', padding: 8, border: '1px solid #cbd5e1', borderRadius: 6 }} />
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
          <button type="submit" className="fw-mini fw-mini-strong" disabled={busy || !available || (!input.trim() && !(guided && (stage === 'thought' || stage === 'retry')))}>{busy ? '回答中…' : !guided ? mode === 'feynman' ? '提交讲解，寻找缺口' : mode === 'self_check' ? '提交作答，查看反馈' : '发送回答/问题' : stage === 'thought' ? (input.trim() ? '提交思路，获取提示' : '获取提示') : stage === 'retry' ? '提交重答，展开讲解' : '发送问题'}</button>
          <button type="button" className="fw-mini" disabled={busy || !turns.length} onClick={() => void closeAndRestart()}>结束会话并开新会话</button>
        </div>
      </form>
      {guided && available && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
        {stage === 'thought' && <button className="fw-mini" disabled={busy} onClick={() => void send('我完全不会，请从最基础的已知条件或概念给一个提示。', mode, 'hint')}>我完全不会</button>}
        {stage === 'retry' && <button className="fw-mini" disabled={busy} onClick={() => void send(input.trim() || '请再给一个最小提示，不公布完整讲解。', mode, 'hint')}>再给一个提示</button>}
        <button className="fw-mini" disabled={busy} onClick={() => void send(input.trim() || `请完整讲解「${nodeName}」的概念、方法和适用边界。`, mode, 'direct')}>直接看完整讲解</button>
        {stage === 'complete' && <button className="fw-mini" disabled={busy} onClick={() => void send(`请给一道「${nodeName}」的新变式自测，暂不公布答案。`, mode, 'transfer')}>用新变式检验理解</button>}
      </div>}
      {notice && <p className="fw-muted" role="status" style={{ fontSize: 12 }}>{notice}</p>}
      <p className="fw-muted" style={{ fontSize: 11 }}>教学对话按考点和学习方式保存在本系统，跨会话自动恢复；可把 AI 提出的疑点转为学习任务待验证。问答不直接修改掌握度；用专项训练检验理解。</p>
    </>}
  </section>;
}
