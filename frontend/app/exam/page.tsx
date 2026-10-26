'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { api, ApiError, Current, DiagnosisOutput, Result, Session, TutorExplanationOutput } from '../../lib/api';
import { FormattedStem } from '../../lib/FormattedStem';

const EXAM_KEY = 'gongkao-exam-session';

function format(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m.toString().padStart(2, '0')}:${rem.toString().padStart(2, '0')}`;
}

export default function ExamPage() {
  const [examState, setExamState] = useState<{
    session_id: string;
    total: number;
    time_limit_seconds: number;
    status: string;
    earned_score?: number;
    max_score?: number;
  } | null>(null);

  const [current, setCurrent] = useState<Current | null>(null);
  const [selectedAnswer, setSelectedAnswer] = useState<string>('');
  const [timeLeftMs, setTimeLeftMs] = useState<number>(7200 * 1000);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [examResult, setExamResult] = useState<any | null>(null);
  const [reviewResult, setReviewResult] = useState<Result | null>(null);
  const [explanation, setExplanation] = useState<TutorExplanationOutput | null>(null);

  async function startExam() {
    setBusy(true); setError('');
    try {
      const res = await api<{ session_id: string; total_questions: number; time_limit_seconds: number }>('/exam/start', { time_limit_seconds: 7200 });
      setExamState({
        session_id: res.session_id,
        total: res.total_questions,
        time_limit_seconds: res.time_limit_seconds,
        status: 'active',
      });
      setTimeLeftMs(res.time_limit_seconds * 1000);
      const nextQ = await api<Current>(`/quiz/${res.session_id}/next`);
      setCurrent(nextQ);
      setSelectedAnswer('');
    } catch (err: any) {
      setError(err.message || '创建模考失败');
    } finally { setBusy(false); }
  }

  async function answerQuestion() {
    if (!examState || !current || !selectedAnswer) return;
    setBusy(true);
    try {
      await api(`/quiz/${examState.session_id}/answer`, {
        attempt_id: current.attempt_id,
        selected_answer: selectedAnswer,
        confidence: 0.8,
      });
      const next = await api<Current | { done: true }>(`/quiz/${examState.session_id}/next`);
      if ('done' in next && next.done) {
        // All answered -> auto submit
        await submitPaper();
      } else {
        setCurrent(next as Current);
        setSelectedAnswer('');
      }
    } catch (err: any) {
      setError(err.message || '保存答案失败');
    } finally { setBusy(false); }
  }

  async function submitPaper() {
    if (!examState) return;
    setBusy(true);
    try {
      const res = await api(`/exam/${examState.session_id}/submit`, {});
      setExamResult(res);
      setExamState(prev => prev ? { ...prev, status: 'completed' } : null);
      setCurrent(null);
    } catch (err: any) {
      setError(err.message || '交卷失败');
    } finally { setBusy(false); }
  }

  async function loadExplanation(attId: string) {
    setBusy(true);
    try {
      const exp = await api<TutorExplanationOutput>(`/attempts/${attId}/explain`, {});
      setExplanation(exp);
    } catch (err: any) {
      setError(err.message || '获取解析失败');
    } finally { setBusy(false); }
  }

  return (
    <main>
      <header>
        <Link href="/dashboard" className="brand"><span className="brand-icon">考</span>公考 Learning OS · 模拟考场</Link>
        <nav>
          <Link href="/dashboard">学习概览</Link>
          <Link href="/framework">知识框架</Link>
          <Link href="/quiz">行测训练</Link>
          <Link href="/review">到期复习</Link>
          <Link href="/exam" className="active">全真模考</Link>
          <Link href="/shenlun">申论工作台</Link>
          <Link href="/importer">题库导入</Link>
        <Link href="/settings">设置</Link></nav>
        <span className="local" style={{ color: '#b23b18' }}>⚠️ 考试模式：AI 全程锁闭</span>
      </header>

      <div className="intro">
        <span className="eyebrow">EXAM MODE / 全真模考</span>
        <h1>严肃模拟，检验真实水准。</h1>
        <p>考试过程中锁闭一切 AI 提示与答案检索，提交后解锁成绩单与考点深度复盘。</p>
      </div>

      {error && <div role="alert" className="error">{error}</div>}

      <div className="workspace">
        <section className="card" aria-label="考试工作台">
          {!examState && (
            <div className="welcome">
              <h2>准备好开始全真模拟考试了吗？</h2>
              <p>限时闭卷答题，全真计时。交卷前不可查看解析，AI 助教功能将被彻底锁闭。</p>
              <button className="primary" disabled={busy} onClick={startExam}>开始全真模考</button>
            </div>
          )}

          {examState && examState.status === 'active' && current && (
            <>
              <div className="card-top">
                <span>模考进行中 · 第 1 卷</span>
                <span>剩余时间：<strong style={{ color: '#b23b18', fontSize: 16 }}>{format(timeLeftMs)}</strong></span>
              </div>
              <div className="question-meta">
                <span className="pill">{current.question.module}</span>
                <span className="pill" style={{ background: '#fcedea', color: '#b23b18' }}>🔒 考试模式硬锁定</span>
              </div>
              <h2 className="stem"><FormattedStem text={current.question.stem} /></h2>
              <fieldset disabled={busy} className="options">
                {Object.entries(current.question.options).map(([k, v]) => (
                  <label key={k} className={selectedAnswer === k ? 'option selected' : 'option'}>
                    <input type="radio" name="exam-ans" value={k} checked={selectedAnswer === k} onChange={() => setSelectedAnswer(k)} />
                    <span>{k}. {v}</span>
                  </label>
                ))}
              </fieldset>
              <div className="submit-row" style={{ marginTop: 24 }}>
                <button type="button" className="secondary" disabled={busy} onClick={submitPaper}>提前交卷</button>
                <button className="primary" disabled={busy || !selectedAnswer} onClick={answerQuestion}>下一题 / 保存</button>
              </div>
            </>
          )}

          {examResult && (
            <div className="result" aria-live="polite">
              <span className="pill" style={{ background: '#e5f3ea', color: 'var(--accent)' }}>模考已交卷</span>
              <h2>成绩单：{examResult.earned_score} 分 / {examResult.max_score} 分</h2>
              <div className="metrics">
                <div><small>正确题目</small><strong>{examResult.correct_count} / {examResult.total_questions}</strong></div>
                <div><small>试卷正确率</small><strong>{Math.round(examResult.accuracy * 100)}%</strong></div>
                <div><small>交卷状态</small><strong>AI 已解锁</strong></div>
              </div>
              <p style={{ marginTop: 16 }}>现在可以自由进行试卷复盘。已为您解锁 AI 深度解析与错题归因服务。</p>
              {explanation && (
                <div className="explanation-card" style={{ margin: '16px 0', padding: 14, background: '#f5f7fa', border: '1px solid #dbe2ea', borderRadius: 8 }}>
                  <h4>📖 考点深度复盘</h4>
                  <p><b>考点：</b>{explanation.core_concept}</p>
                  <p>{explanation.summary}</p>
                  <p><b>建议动作：</b>{explanation.recommended_action}</p>
                </div>
              )}
              <div className="result-actions" style={{ marginTop: 24 }}>
                <Link className="primary-link" href="/dashboard">返回学习概览</Link>
                <button type="button" className="secondary" onClick={startExam}>再考一卷</button>
              </div>
            </div>
          )}
        </section>

        <aside>
          <div className="note">
            <span className="eyebrow">考场纪律</span>
            <h2>完全无干扰环境</h2>
            <p>考试模式由后端安全机制硬锁定。前端即使尝试调用 `/hint`，后端也会强制返回 403 权限拒绝。</p>
            <hr />
            <p><b>01</b> 专注答卷，把握时间节奏</p>
            <p><b>02</b> 遇到难题先凭直觉标记</p>
            <p><b>03</b> 考后复盘，逐题消化失误</p>
          </div>
        </aside>
      </div>
    </main>
  );
}
