'use client';

import { useState } from 'react';
import { api } from './api';

export type GuidanceState = {
  stage: string; revision: number; hint_level: number; paragraph_index: number; paragraph_count: number;
  paragraph?: { id: string; title: string; text: string } | null;
  ai_status: string; can_advance: boolean;
  history: Array<{ stage: string; prompt?: string; response?: string; level?: number; paragraph_id?: string }>;
};
export type PointTrace = {
  status: string; version_key: string; score_note?: string; simulation?: boolean;
  points: Array<{ id: string; text: string; status: string | null; verified: boolean; note: string;
    material_evidence: Array<{ paragraph_id: string; quote: string; start: number; end: number }>;
    student_evidence: Array<{ quote: string; start: number; end: number }> }>;
  recommendations: Array<{ skill_key: string; skill_name: string; error_type: string; instruction: string;
    mastery_score: number; evaluation_count: number; basis: string[] }>;
};

export function ShenlunGuidance({ sessionId, state, onChange }: {
  sessionId: string; state: GuidanceState; onChange: (value: GuidanceState) => void;
}) {
  const [response, setResponse] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function send(action: 'hint' | 'advance') {
    setBusy(true); setError('');
    try {
      onChange(await api<GuidanceState>(`/shenlun/${sessionId}/guidance`, {
        action, expected_revision: state.revision, response,
      }));
      if (action === 'advance') setResponse('');
    } catch (e: any) {
      setError(e.message || '导练暂不可用，输入已保留');
      // Recover authoritative stage after a second device updates it.
      try { onChange(await api<GuidanceState>(`/shenlun/${sessionId}/guidance`)); } catch {}
    } finally { setBusy(false); }
  }
  const stageHistory = state.history.filter(h => h.stage === state.stage);
  return <section aria-label="分阶段 AI 导练" style={{ padding: 14, border: '1px solid #dfcfc3', borderRadius: 6, marginBottom: 16 }}>
    <strong>分阶段 AI 导练 · {state.stage}</strong>
    <p style={{ fontSize: 12 }}>审题 → 分段阅读与提炼 → 组织答案 → 点评修改 · 提示 {state.hint_level}/3</p>
    {state.paragraph && <blockquote style={{ margin: '10px 0', whiteSpace: 'pre-wrap' }}>
      <strong>{state.paragraph.title} · 第 {state.paragraph_index + 1}/{state.paragraph_count} 段</strong>
      <p>{state.paragraph.text}</p>
    </blockquote>}
    {stageHistory.map((h, i) => <p key={i} style={{ whiteSpace: 'pre-wrap' }}>{h.prompt || h.response}</p>)}
    {state.ai_status === 'unavailable' && <p>AI 暂不可用，已使用基础引导问题。</p>}
    {state.ai_status === 'mock' && <p>当前为离线模拟导练。</p>}
    <label>本阶段思路<textarea aria-label="本阶段思路" value={response} maxLength={4000}
      onChange={e => setResponse(e.target.value)} rows={3} style={{ width: '100%', boxSizing: 'border-box' }} /></label>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      <button type="button" disabled={busy || state.hint_level >= 3} onClick={() => void send('hint')}>获取下一层引导</button>
      {state.can_advance && state.stage !== '组织答案' && <button type="button" disabled={busy || !response.trim()}
        onClick={() => void send('advance')}>{state.stage === '阅读提炼' ? '保存本段提炼并继续' : '保存审题并开始阅读'}</button>}
    </div>
    {state.stage === '组织答案' && <p>组织完成后，在正式作答区独立提交；原有直接作答流程仍可使用。</p>}
    {state.history.some(h => h.response) && <details><summary>已保存的审题与提炼</summary>
      {state.history.filter(h => h.response).map((h, i) => <p key={i}>{h.stage} {h.paragraph_id}：{h.response}</p>)}
    </details>}
    {error && <p role="alert">{error}</p>}
  </section>;
}

export function ShenlunPointTrace({ report, sessionId, onChange }: { report: PointTrace; sessionId: string; onChange: (r: PointTrace) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function retry() {
    setBusy(true); setError('');
    try { onChange((await api<{ point_trace: PointTrace }>(`/shenlun/${sessionId}/point-trace`, {})).point_trace); }
    catch (e: any) { setError(e.message || '重试失败'); }
    finally { setBusy(false); }
  }
  const labels: Record<string, string> = { full: '完整', partial: '部分', not_hit: '未命中', omitted: '遗漏' };
  return <section aria-label="采分点证据映射" style={{ padding: 16, border: '1px solid #dfcfc3', margin: '16px 0' }}>
    <h3>采分点—材料—作答证据映射</h3>
    <p>{report.score_note}。状态为 AI 参考判断，可结合原句复核。</p>
    {report.simulation && <p>离线模拟结果，仅用于验证界面与流程。</p>}
    {report.status !== 'available' && <p>部分证据尚未核验。<button disabled={busy} onClick={() => void retry()}>重试证据映射</button></p>}
    {error && <p role="alert">{error}</p>}
    {report.points.map(p => <details key={p.id}>
      <summary>{p.verified ? labels[p.status || ''] : '待核验'} · {p.text}</summary>
      {p.material_evidence.map((e, i) => <p key={i}>材料 {e.paragraph_id}：<q>{e.quote}</q></p>)}
      {p.student_evidence.map((e, i) => <p key={i}>学生原句：<q>{e.quote}</q></p>)}
      {p.status === 'omitted' && <p>本版答案未提供对应内容。</p>}
      <p>{p.note}</p>
    </details>)}
    <h4>针对性训练建议</h4>
    {report.recommendations.length ? report.recommendations.map(r => <p key={r.error_type}>
      <strong>{r.skill_name}</strong>（历史掌握度 {Math.round(r.mastery_score * 100)}%，评价 {r.evaluation_count} 次）：{r.instruction}
    </p>) : <p>暂未形成足够依据的专项训练建议。</p>}
  </section>;
}
