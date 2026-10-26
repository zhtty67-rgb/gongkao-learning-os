'use client';

import { useEffect, useRef, useState } from 'react';
import { api, clipReviewMessage } from './api';
import { TeachingContent } from './TeachingContent';
import { FormattedExplanation } from './FormattedExplanation';
import { createRequestId } from './requestId';

type Action = 'thought' | 'dont_know' | 'retry' | 'hint' | 'direct' | 'full' | 'transfer' | 'check_transfer' | 'followup' | 'ask';
type Payload = { action: Action; message?: string; answer?: string };
type Turn = { id: string; role: string; content: string; status: string; guided_review: { action: Action; phase?: string; request_payload: Payload; request_id?: string; skipped_retry?: boolean; skip_label?: string } };
type Stage = 'review' | 'retry' | 'complete' | 'transfer' | 'correct';
type State = { stage: Stage; messages: Turn[]; options: Record<string, string>; teacher_name: string; module?: string; vision_available?: boolean; available_actions?: Action[]; unavailable_reason?: string | null; question_images?: { url: string; label: string }[]; attempt_correct?: boolean };

const STAGE_LABELS: Record<Stage, string> = {
  review: '① 复盘与重答',
  retry: '② 提示后重答',
  complete: '③ 完整解析与对照',
  transfer: '④ 新变式独立自测',
  correct: '① 作答正确 · 理解巩固',
};
const STAGE_INTROS: Record<Stage, string> = {
  review: '先点“获取提示”，再重新选择答案提交。可选填原思路或卡点，老师会结合内容给提示；仍不会可留空查看详细解析。',
  retry: '看完提示后：选好选项点“提交重答，查看详细解析”；仍不会可留空直接点“仍然不会，查看详细解析”，不会伪造答案，也不算新增答错。重答仍错会给出完整解析并指出未解决的步骤。',
  complete: '完整解析已给出。可继续追问，或用一道新变式自测验证理解；教学对话不计入首次成绩。',
  transfer: '独立作答这道变式并写下理由，提交后教师核验；变式练习不写入正式成绩或掌握度。',
  correct: '答对不等于掌握。点“请老师讲解”：不填内容时查看完整解析，填写思路或问题时老师针对内容讲解。',
};

export function GuidedTeacherReview({ attemptId }: { attemptId: string }) {
  const [state, setState] = useState<State | null>(null);
  const [text, setText] = useState('');
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [clipped, setClipped] = useState<Record<string, boolean>>({});
  const [zoomImg, setZoomImg] = useState<string | null>(null);
  const alive = useRef(true);
  const dialogue = useRef<HTMLDivElement>(null);
  const inFlight = useRef(false);
  const pendingRequest = useRef<{ key: string; id: string } | null>(null);
  const endpoint = `/attempts/${encodeURIComponent(attemptId)}/guided-review`;
  useEffect(() => {
    alive.current = true;
    api<State>(endpoint).then(r => { if (alive.current) setState(r); }).catch((e: Error) => { if (alive.current) setError(e.message); });
    return () => { alive.current = false; };
  }, [endpoint]);
  async function send(payload: Payload) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true); setError('');
    try {
      const key = JSON.stringify(payload);
      if (pendingRequest.current?.key !== key) pendingRequest.current = { key, id: createRequestId() };
      const next = await api<State>(endpoint, { ...payload, request_id: pendingRequest.current.id });
      pendingRequest.current = null;
      if (!alive.current) return;
      setState(next);
      if (next.messages.at(-1)?.status === 'completed') { setText(''); setAnswer(''); }
    } catch (e: unknown) { if (alive.current) setError(e instanceof Error ? e.message : '教学回复暂不可用'); }
    finally { inFlight.current = false; if (alive.current) setBusy(false); }
  }
  const stage: Stage = state?.stage && state.stage in STAGE_LABELS ? state.stage : 'review';
  useEffect(() => {
    if (dialogue.current) {
      dialogue.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [state?.messages.at(-1)?.id]);
  const graphic = state?.module === '图形推理' || state?.module === '立体图推';
  const graphicLimited = graphic && !state?.vision_available;
  const legacyFailures = new Set(state?.messages.filter(t => graphic && t.status === 'failed' && t.content.includes('当前没有图像输入')).map(t => t.guided_review.request_id));
  const can = (action: Action) => state?.available_actions ? state.available_actions.includes(action) : !graphicLimited || action === 'direct';
  const reanswerStage = stage === 'review' || stage === 'retry';
  const formAction: Action = reanswerStage ? 'retry' : stage === 'transfer' ? 'check_transfer' : stage === 'correct' && !text.trim() ? 'full' : 'followup';
  const options = state?.options || {};
  const hasOptions = Object.keys(options).length > 0;
  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (reanswerStage) {
      void send({ action: 'retry', message: text, answer });
      return;
    }
    if (stage !== 'transfer' && stage !== 'correct' && !text.trim()) {
      setError('请写下追问问题');
      return;
    }
    void send({ action: formAction, message: text, answer });
  }
  const turnLabel = (t: Turn) => t.role === 'user' ? (t.guided_review?.skip_label || '我的思路 / 作答') : t.status === 'failed' ? '本次回复未完成'
    : t.guided_review.action === 'direct' ? '题库原解析' : t.guided_review.action === 'retry' || t.guided_review.action === 'full' ? '教师完整解析'
    : t.guided_review.action === 'transfer' ? '同考点新变式' : t.guided_review.action === 'ask' || (t.guided_review.action === 'thought' && t.guided_review.phase === 'teach') ? '教师讲解' : '教师点拨';
  const sourceBadge = (t: Turn) => {
    if (t.role !== 'assistant' || t.status !== 'completed') return null;
    if (t.guided_review.action === 'direct') return '题库原卷 · 非AI生成';
    if (t.guided_review.action === 'retry' || t.guided_review.action === 'full') return '教师讲解 · AI生成';
    return null;
  };
  const failedRequests = new Set(state?.messages.filter(t => t.status === 'failed').map(t => t.guided_review.request_id).filter(Boolean));
  const lastRequest = state?.messages.at(-1)?.guided_review.request_id;
  const visibleTurns = state?.messages.filter((t, i, all) => {
    const failed = t.status === 'failed' || (!!t.guided_review.request_id && failedRequests.has(t.guided_review.request_id));
    if (t.guided_review.request_id && legacyFailures.has(t.guided_review.request_id)) return false;
    return !failed || (!graphicLimited && (t.guided_review.request_id ? t.guided_review.request_id === lastRequest : i === all.length - 1));
  });
  async function clip(t: Turn) {
    try {
      await clipReviewMessage(attemptId, { message_content: t.content, source_message_id: t.id, turn_type: 'guided_teacher', message_role: t.role === 'user' ? 'user' : 'assistant', title: '教学复盘' });
      setClipped(prev => ({ ...prev, [t.id]: true }));
    } catch (e: unknown) { setError(e instanceof Error ? e.message : '收藏失败'); }
  }
  const placeholder = reanswerStage
    ? (stage === 'review'
      ? '选填原思路或卡点，点“获取提示”让老师帮你找出下一步。'
      : '选填仍卡住的地方或重答理由。重新选择答案提交；仍不会可留空查看完整解析。')
    : stage === 'transfer' ? '写出变式的答案与理由（Enter 发送）。' : stage === 'correct' ? '选填：写下思路或具体问题；不填则查看完整解析。' : '想深入理解哪个概念或步骤？直接写下追问（Enter 发送）。';
  const inputLabel = reanswerStage ? '思路或卡点（选填）' : stage === 'transfer' ? '新变式的答案与理由' : '解析中还有哪一步不懂？';
  const primaryLabel = reanswerStage
    ? (answer ? '提交重答，查看详细解析' : '仍然不会，查看详细解析')
    : stage === 'correct' ? '请老师讲解' : stage === 'complete' ? '继续追问' : '提交自测作答';
  return <section aria-label="教师引导复盘" style={{ padding: 16, border: '1px solid #fed7aa', borderRadius: 10, marginTop: 12 }}>
    <h3>{!state ? '教师引导复盘' : graphicLimited ? '图形题复盘' : `教师引导复盘 · ${STAGE_LABELS[stage]}`}</h3>
    {state && <p style={{ fontSize: 12, color: '#64748b' }}>指导教师：{state.teacher_name}</p>}
    <p style={{ fontSize: 13 }}>{graphicLimited ? state?.unavailable_reason || '当前图形题教学尚未接入图片，可查看题库已有解析，并记录错因和笔记。' : STAGE_INTROS[stage]}</p>
    {graphic && state?.vision_available && <p style={{ fontSize: 12, color: '#166534' }}>已接入原题与选项图片；图形变式使用同考点题库原图。细线与交点仍可能识别有误，请对照原图核验。</p>}
    {error && <p role="alert" style={{ color: '#b91c1c' }}>{error}</p>}
    {!state && error && <button onClick={() => {
      setError('');
      api<State>(endpoint).then(setState).catch((e: Error) => setError(e.message));
    }}>重新读取教学进度</button>}
    {!state && !error && <p>正在读取教学进度…</p>}
    <div ref={dialogue} aria-live="polite">
      {visibleTurns?.map((t, i) => <div key={t.id} style={{ padding: 12, margin: '10px 0', borderRadius: 8, whiteSpace: t.role === 'user' ? 'pre-wrap' : 'normal', overflowWrap: 'anywhere', background: t.status === 'failed' ? '#fef2f2' : t.role === 'user' ? '#eff6ff' : '#f8fafc', border: '1px solid ' + (t.status === 'failed' ? '#fee2e2' : t.role === 'user' ? '#dbeafe' : '#e2e8f0') }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, gap: 8 }}>
          <strong>{turnLabel(t)}</strong>
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {sourceBadge(t) && <span style={{ fontSize: 11, padding: '1px 8px', borderRadius: 999, background: t.guided_review.action === 'direct' ? '#ecfdf5' : '#fff7ed', color: t.guided_review.action === 'direct' ? '#047857' : '#c2410c', border: '1px solid ' + (t.guided_review.action === 'direct' ? '#a7f3d0' : '#fed7aa') }}>{sourceBadge(t)}</span>}
            {t.role === 'assistant' && t.status === 'completed' && <button style={{ fontSize: 12, padding: '2px 8px' }} disabled={!!clipped[t.id]} onClick={() => void clip(t)}>{clipped[t.id] ? '已收藏到笔记' : '收藏到笔记'}</button>}
          </span>
        </div>
        {t.role === 'assistant' && (t.guided_review.action === 'direct' || t.guided_review.action === 'retry' || t.guided_review.action === 'full') ? (
          <FormattedExplanation text={t.content} module={state?.module} images={state?.question_images} onZoom={setZoomImg} />
        ) : (
          <TeachingContent text={t.content} onZoom={setZoomImg} />
        )}
        {t.status === 'failed' && <button disabled={busy} onClick={() => void send(t.guided_review.request_payload)}>重试本步</button>}
      </div>)}
      {busy && <p style={{ color: '#64748b', fontSize: 13, fontStyle: 'italic', margin: '8px 0' }}>⏳ 教师正在组织概念与推导，请稍候…</p>}
    </div>
    {state && can(formAction) && <form onSubmit={handleSubmit}>
      {reanswerStage && hasOptions && <label>重答选项（可直接提交，也可先获取提示）<select aria-label="重答选项" value={answer} onChange={e => { setAnswer(e.target.value); setError(''); }} disabled={busy} style={{ width: '100%', margin: '6px 0' }}>
        <option value="">仍然不会 / 暂不选择</option>{Object.entries(options).map(([k, v]) => <option key={k} value={k}>{k}. {v}</option>)}
      </select></label>}
      <label htmlFor={`guided-${attemptId}`}>{inputLabel}</label>
      <textarea id={`guided-${attemptId}`} value={text} onChange={e => { setText(e.target.value); setError(''); }} onKeyDown={e => {
        if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
          e.preventDefault();
          handleSubmit(e);
        }
      }} maxLength={2000} rows={3} disabled={busy} placeholder={placeholder} style={{ width: '100%', boxSizing: 'border-box', margin: '6px 0' }} />
      <button type="submit" disabled={busy || (!reanswerStage && stage !== 'transfer' && stage !== 'correct' && !text.trim())} style={{ fontWeight: 700 }}>{primaryLabel}</button>
    </form>}
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
      {reanswerStage && can('hint') && <button type="button" disabled={busy} onClick={() => void send(stage === 'review' && text.trim() ? { action: 'thought', message: text } : { action: 'hint', message: text })}>{stage === 'retry' ? '再给一个提示' : '获取提示'}</button>}
      {stage === 'complete' && can('transfer') && <button type="button" disabled={busy} onClick={() => void send({ action: 'transfer' })}>用一道新变式验证</button>}
      {stage === 'transfer' && can('ask') && <button type="button" disabled={busy || !text.trim()} onClick={() => void send({ action: 'ask', message: text })}>向教师请教</button>}
      {can('hint') && stage === 'transfer' && <button type="button" disabled={busy} onClick={() => void send({ action: 'hint', message: text })}>再给一个提示</button>}
      <button type="button" disabled={busy || !state} onClick={() => void send({ action: 'direct' })} title="直接读取题库原卷解析，不调用模型">查看题库解析</button>
    </div>
    <p style={{ fontSize: 12, color: '#64748b' }}>提示后作答与跳过重答单独保存在教学对话中，原始成绩不变；空选项按实际情况记录（如“未获取提示，跳过重答”或“提示后仍不会／跳过重答”），不算新增答错，也不作为掌握证据。</p>

    {/* 解析图高清放大灯箱 */}
    {zoomImg && (
      <div
        onClick={() => setZoomImg(null)}
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100vw',
          height: '100vh',
          background: 'rgba(0,0,0,0.82)',
          zIndex: 9999,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'zoom-out',
          padding: 24,
        }}
      >
        <img
          src={zoomImg}
          alt="解析图放大"
          style={{ maxWidth: '92%', maxHeight: '92%', objectFit: 'contain', background: '#fff', borderRadius: 8, padding: 12, boxShadow: '0 8px 32px rgba(0,0,0,0.5)' }}
        />
      </div>
    )}
  </section>;
}
