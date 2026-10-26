'use client';
import { useEffect, useState } from 'react';
import { api, InteractiveDiagnosisRecord, QuestionReviewHistory } from './api';
import { QuestionNoteBox } from './QuestionNoteBox';
import { GuidedTeacherReview } from './GuidedTeacherReview';
import { TeachingContent } from './TeachingContent';
export const SUPPLEMENTARY_CAUSES: Array<[string, string]> = [
  ['time_pressure', '时间紧迫/慌乱'], ['pure_guess', '纯粹猜测/蒙题'], ['slip_of_hand', '看错题问/选非'],
];
interface Props {
  attemptId: string;
  questionId?: string;
  isCorrect?: boolean;
  confidence?: number | null;
  stem?: string;
  module?: string;
  justGraded?: boolean;
  onUpdate?: (record: InteractiveDiagnosisRecord) => void;
}

// Shared teaching flow; record tools preserve distinct functions and old data.
export function InteractiveReviewCard({ attemptId, questionId, module, onUpdate }: Props) {
  const [selected, setSelected] = useState(attemptId);
  const [tools, setTools] = useState(false);
  const [record, setRecord] = useState<InteractiveDiagnosisRecord | null>(null);
  const [history, setHistory] = useState<QuestionReviewHistory['attempts']>([]);
  const [stage, setStage] = useState('');
  const [supplementary, setSupplementary] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { setSelected(attemptId); setTools(false); }, [attemptId]);
  useEffect(() => {
    setRecord(null); setSaved(false); setError(''); setStage(''); setNote(''); setSupplementary('');
    if (!tools) return;
    let active = true;
    api<InteractiveDiagnosisRecord>(`/attempts/${selected}/review-diagnosis`).then(r => {
      if (!active) return;
      setRecord(r); setStage(r.selected_error_type || '');
      const lastCause=r.cause_history?.at(-1);
      setNote(lastCause?.explanation || r.user_feedback_text || '');
      setSupplementary(lastCause?.supplementary || '');
      if (!questionId && r.question_id) api<QuestionReviewHistory>(`/questions/${r.question_id}/review-history`).then(h => {
        if (active) setHistory(h.attempts);
      }).catch((e: Error) => { if (active) setError(e.message); });
    }).catch((e: Error) => { if (active) setError(e.message); });
    if (questionId) api<QuestionReviewHistory>(`/questions/${questionId}/review-history`).then(r => {
      if (active) setHistory(r.attempts);
    }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [selected, tools, questionId]);
  async function saveCause() {
    if (!stage || busy) return;
    setBusy(true); setError(''); setSaved(false);
    try {
      const r = await api<InteractiveDiagnosisRecord>(`/attempts/${selected}/review-cause`, {
        error_type: stage, stage_code: stage, knowledge_node_id: record?.knowledge_node?.node_id,
        supplementary_cause: supplementary, explanation: note,
      });
      setRecord(r); setSaved(true); onUpdate?.(r);
    } catch (e: unknown) { setError(e instanceof Error ? e.message : '保存失败'); }
    finally { setBusy(false); }
  }
  const qid = questionId || record?.question_id;
  return <div>
    <GuidedTeacherReview key={selected} attemptId={selected} />
    <details onToggle={e => setTools(e.currentTarget.open)}>
      <summary>错因记录、笔记与历史</summary>
      {tools && <section aria-label="复盘记录工具" style={{ padding: 12 }}>
        {error && <p role="alert">{error}</p>}
        {history.length > 1 && <label>历次作答<select aria-label="历次作答" value={selected} disabled={busy} onChange={e => setSelected(e.target.value)}>
          {history.map(a => <option key={a.attempt_id} value={a.attempt_id}>{a.submitted_at} · {a.selected_answer} · {a.correct ? '正确' : '错误'}</option>)}
        </select></label>}
        {!record && !error && <p>正在读取记录…</p>}
        {record && <>
          <p>已确认自己的失误时记录具体环节；教师对话中的推测不会自动记为错因。</p>
          <label>失误环节<select aria-label="失误环节" value={stage} disabled={busy} onChange={e => { setStage(e.target.value); setSaved(false); }}>
            <option value="">请选择</option>{record.problem_solving_stages?.map(s => <option key={s.code} value={s.code}>{s.label}</option>)}
          </select></label>
          <label>补充原因<select aria-label="补充原因" value={supplementary} disabled={busy} onChange={e => { setSupplementary(e.target.value); setSaved(false); }}>
            <option value="">无</option>{SUPPLEMENTARY_CAUSES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select></label>
          <textarea aria-label="错因说明" placeholder="具体哪一步卡住了？" value={note} disabled={busy} onChange={e => { setNote(e.target.value); setSaved(false); }} rows={3} maxLength={2000} style={{ display: 'block', width: '100%' }} />
          <button disabled={busy || !stage} onClick={() => void saveCause()}>{busy ? '正在保存…' : '保存错因记录'}</button>
          {saved && <p role="status">已记录</p>}
          {!!record.messages?.some(m => m.turn_type !== 'guided_teacher') && <details><summary>旧版复盘记录（仅查看）</summary>
            {record.messages.filter(m => m.turn_type !== 'guided_teacher').map(m => <div key={m.id}><strong>{m.role === 'user' ? '我的记录：' : '历史教师回复（可能有误）：'}</strong><TeachingContent text={m.content} /></div>)}
          </details>}
        </>}
        {qid && <QuestionNoteBox questionId={qid} attemptId={selected} module={module} knowledgeNodeId={record?.knowledge_node?.node_id} knowledgeNodeCode={record?.knowledge_node?.knowledge_code} />}
      </section>}
    </details>
  </div>;
}
