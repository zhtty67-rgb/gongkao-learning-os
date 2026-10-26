'use client';

import { memo, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { api, ApiError, Current, DailyGoal, DiagnosisOutput, Question, Result, ReviewStatus, Session } from '../../lib/api';
import { QuestionReviewCard } from '../../lib/QuestionReviewCard';
import { InteractiveReviewCard } from '../../lib/InteractiveReviewCard';
import { RecordedTime } from '../../lib/RecordedTime';
import { FormattedStem } from '../../lib/FormattedStem';
import { FormattedExplanation } from '../../lib/FormattedExplanation';
import { ReviewTeachingLink } from '../../lib/ReviewTeachingLink';
import { CONFIDENCE_TIERS, CONFIDENCE_DRAFT_VALUES, confidenceLabel } from '../../lib/confidence';

const SESSION_KEY = 'gongkao-review-session';
const questionCache = new Map<string, Question>();
function cacheQuestion(q: Question) {
  if (q && q.id) {
    questionCache.set(q.id, q);
    try { sessionStorage.setItem(`q_cache:${q.id}`, JSON.stringify(q)); } catch { /* ignore */ }
  }
}
function getCachedQuestion(qid?: string): Question | null {
  if (!qid) return null;
  if (questionCache.has(qid)) return questionCache.get(qid)!;
  try {
    const raw = sessionStorage.getItem(`q_cache:${qid}`);
    if (raw) {
      const parsed = JSON.parse(raw);
      questionCache.set(qid, parsed);
      return parsed;
    }
  } catch { /* ignore */ }
  return null;
}

type Draft = { selected: string; confidence: number | null; changed: boolean };
function read(key: string) { try { return localStorage.getItem(key); } catch { return null; } }
function write(key: string, value: string) { try { localStorage.setItem(key, value); } catch { /* The URL still restores the session. */ } }
function format(ms: number) { const seconds = Math.floor(ms / 1000); return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`; }
function formatDue(value: string) { return new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value)); }

interface ReviewAnswerSheetProps {
  total: number;
  history: Result[];
  reviewIndex: number | null;
  busy: boolean;
  onSelectReview: (index: number) => void;
  onReturnCurrent: () => void;
}

const ReviewAnswerSheet = memo(function ReviewAnswerSheet({
  total,
  history,
  reviewIndex,
  busy,
  onSelectReview,
  onReturnCurrent,
}: ReviewAnswerSheetProps) {
  const answeredCount = history.length;
  const isHuge = total > 40;
  const ANSWERED_PAGE_SIZE = 25;
  const totalPages = Math.ceil(answeredCount / ANSWERED_PAGE_SIZE) || 1;

  const [page, setPage] = useState<number>(() => Math.max(0, totalPages - 1));

  // 当外部 reviewIndex 变化时，自动同步对应页
  const activePage = reviewIndex !== null
    ? Math.floor(reviewIndex / ANSWERED_PAGE_SIZE)
    : Math.min(page, Math.max(0, totalPages - 1));

  const visibleIndices: number[] = [];
  let remainingCount = 0;

  if (!isHuge) {
    for (let i = 0; i < total; i++) visibleIndices.push(i);
  } else {
    // 已答题按页窗口化渲染
    const startIdx = activePage * ANSWERED_PAGE_SIZE;
    const endIdx = Math.min(answeredCount, startIdx + ANSWERED_PAGE_SIZE);
    for (let i = startIdx; i < endIdx; i++) visibleIndices.push(i);

    // 待答题窗口展示当前题及后续最多 15 题
    const futureLimit = Math.min(total, answeredCount + 16);
    for (let i = answeredCount; i < futureLimit; i++) visibleIndices.push(i);
    remainingCount = Math.max(0, total - futureLimit);
  }

  return (
    <div className="quiz-chips-bar" role="navigation" aria-label="复习重刷答题卡（点击回看已答题目）">
      <span style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 600, marginRight: 4 }}>
        重刷进度 ({answeredCount}/{total})
      </span>

      {isHuge && totalPages > 1 && (
        <span className="quiz-chips-pagination" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginRight: 4 }}>
          <button
            type="button"
            className="quiz-page-btn"
            disabled={activePage <= 0 || busy}
            onClick={() => setPage(p => Math.max(0, p - 1))}
            style={{ fontSize: 10, padding: '2px 5px', borderRadius: 4, border: '1px solid var(--line)', background: '#fff', cursor: 'pointer' }}
            title="查看上一组已重刷题目"
          >
            ◀
          </button>
          <select
            value={activePage}
            onChange={(e) => setPage(Number(e.target.value))}
            style={{ fontSize: 11, padding: '1px 4px', borderRadius: 4, border: '1px solid var(--line)', background: '#fff', cursor: 'pointer' }}
            aria-label="切换已答题组"
          >
            {Array.from({ length: totalPages }, (_, idx) => {
              const pStart = idx * ANSWERED_PAGE_SIZE + 1;
              const pEnd = Math.min(answeredCount, (idx + 1) * ANSWERED_PAGE_SIZE);
              return (
                <option key={idx} value={idx}>
                  已答 {pStart}-{pEnd} 题
                </option>
              );
            })}
          </select>
          <button
            type="button"
            className="quiz-page-btn"
            disabled={activePage >= totalPages - 1 || busy}
            onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
            style={{ fontSize: 10, padding: '2px 5px', borderRadius: 4, border: '1px solid var(--line)', background: '#fff', cursor: 'pointer' }}
            title="查看下一组已重刷题目"
          >
            ▶
          </button>
        </span>
      )}

      {visibleIndices.map(i => {
        const answeredItem = history[i] ?? null;
        const isCurrentPending = !answeredItem && i === answeredCount;
        const reviewing = reviewIndex === i;

        let statusClass = 'unanswered';
        let isClickable = false;
        if (answeredItem) {
          statusClass = answeredItem.correct ? 'correct' : 'incorrect';
          isClickable = true;
        } else if (isCurrentPending) {
          statusClass = 'current';
        }

        const className = `quiz-chip ${statusClass} ${isClickable ? 'clickable' : ''} ${reviewing ? 'reviewing' : ''}`;

        return (
          <button
            key={i}
            type="button"
            disabled={!answeredItem || busy}
            onClick={() => answeredItem && onSelectReview(i)}
            className={className}
            title={
              answeredItem
                ? `回看第 ${i + 1} 题 · ${answeredItem.correct ? '回答正确' : (answeredItem.selected_answer ? '回答错误' : '未作答')}`
                : (isCurrentPending ? '当前待重刷题目' : `第 ${i + 1} 题 · 未作答`)
            }
          >
            {i + 1}
          </button>
        );
      })}

      {remainingCount > 0 && (
        <span
          style={{
            fontSize: 11,
            color: 'var(--muted)',
            padding: '2px 8px',
            background: '#f1f5f9',
            borderRadius: 6,
            fontWeight: 500,
          }}
          title={`后续还有 ${remainingCount} 道未答题`}
        >
          +{remainingCount} 题待刷
        </span>
      )}

      {reviewIndex !== null && (
        <button
          type="button"
          onClick={() => {
            setPage(Math.max(0, totalPages - 1));
            onReturnCurrent();
          }}
          style={{
            padding: '3px 10px',
            fontSize: 11,
            border: '1px solid var(--line)',
            borderRadius: 6,
            background: '#fff',
            cursor: 'pointer',
            fontWeight: 600,
            marginLeft: 'auto',
          }}
        >
          返回当前待刷题
        </button>
      )}
    </div>
  );
});

export default function Review() {
  const [status, setStatus] = useState<ReviewStatus | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [current, setCurrent] = useState<Current | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [history, setHistory] = useState<Result[]>([]);
  const [reviewIndex, setReviewIndex] = useState<number | null>(null);
  const [draft, setDraft] = useState<Draft>({ selected: '', confidence: null, changed: false });
  const [elapsed, setElapsed] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [isPaused, setIsPaused] = useState(false);
  const [zoomImage, setZoomImage] = useState<string | null>(null);
  const [dailyGoal, setDailyGoal] = useState<DailyGoal | null>(null);
  const [justGradedAttemptId, setJustGradedAttemptId] = useState<string | null>(null);
  const [diagnosis, setDiagnosis] = useState<DiagnosisOutput | null>(null);
  const [aiWorking, setAiWorking] = useState(false);
  const [aiStatus, setAiStatus] = useState('');

  const initialized = useRef(false);
  const lock = useRef(false);
  const timerOrigin = useRef({ base: 0, tick: 0 });
  const pausedMsRef = useRef(0);
  const pauseStartRef = useRef(0);

  const loadDailyGoal = () => {
    api<DailyGoal>('/daily-goal').then(setDailyGoal).catch(() => {});
  };

  function togglePause(force?: boolean) {
    setIsPaused(prev => {
      const next = typeof force === 'boolean' ? force : !prev;
      if (next === prev) return prev;
      if (next) {
        pauseStartRef.current = performance.now();
      } else {
        if (pauseStartRef.current > 0) {
          const duration = performance.now() - pauseStartRef.current;
          pausedMsRef.current += duration;
          timerOrigin.current.tick += duration;
          pauseStartRef.current = 0;
        }
      }
      return next;
    });
  }

  function present(value: Current) {
    cacheQuestion(value.question);
    setCurrent(value);
    setResult(null);
    setReviewIndex(null);
    setDiagnosis(null);
    setJustGradedAttemptId(null);
    setIsPaused(false);
    pausedMsRef.current = 0;
    pauseStartRef.current = 0;
    setZoomImage(null);
    const base = Math.max(0, Date.parse(value.server_now) - Date.parse(value.started_at));
    timerOrigin.current = { base, tick: performance.now() };
    setElapsed(base);
    let restored: Draft = { selected: '', confidence: null, changed: false };
    try {
      const saved = JSON.parse(read(`draft:${value.attempt_id}`) || 'null');
      if (saved && ['', 'A', 'B', 'C', 'D'].includes(saved.selected) && CONFIDENCE_DRAFT_VALUES.includes(saved.confidence)) {
        restored = { selected: saved.selected, confidence: saved.confidence, changed: saved.changed === true };
      }
    } catch { /* Ignore malformed browser draft. */ }
    setDraft(restored);
  }

  async function readStatus() {
    const value = await api<ReviewStatus>('/review/status');
    setStatus(value);
    return value;
  }

  async function load(sid: string) {
    const state = await api<Session>(`/quiz/${sid}`);
    if (state.mode !== 'REVIEW') throw new ApiError(409, '该会话不是复习会话。');
    setSession(state);

    // 同步拉取已答题目清单，驱动复习答题卡
    try {
      const res = await api<{ answered: Result[] }>(`/quiz/${sid}/answered`);
      setHistory(res.answered || []);
    } catch { /* ignore */ }

    const isCompleted = state.status === 'completed' || (state.total > 0 && state.answered >= state.total);

    if (isCompleted) {
      // 整轮复习已做完
      setCurrent(null);
      setReviewIndex(null);
      if (state.latest_result) {
        setResult(state.latest_result);
      }
      return;
    }

    // 核心重刷逻辑：若会话尚未完成，绝对不展示上一题答案，必须直接进入当前待重刷题目！
    if (state.current) {
      cacheQuestion(state.current.question);
      present(state.current);
    } else {
      // 推进至下一题，直接呈现待做题面
      const value = await api<Current | { done: true }>(`/quiz/${sid}/next`);
      if (!value.done) {
        present(value);
      } else {
        setCurrent(null);
      }
    }
  }

  async function perform(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try { await action(); }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : '连接失败。复习记录仍保存在本机，请稍后重试。'); }
    finally { lock.current = false; setBusy(false); }
  }

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    loadDailyGoal();
    void perform(async () => {
      const sid = new URLSearchParams(window.location.search).get('session') || read(SESSION_KEY);
      if (sid) { await load(sid); await readStatus(); return; }
      const value = await readStatus();
      if (value.active_session) {
        write(SESSION_KEY, value.active_session.id);
        window.history.replaceState(null, '', `/review?session=${encodeURIComponent(value.active_session.id)}`);
        await load(value.active_session.id);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!current || result || isPaused) return;
    const timer = window.setInterval(() => setElapsed(timerOrigin.current.base + performance.now() - timerOrigin.current.tick), 250);
    return () => window.clearInterval(timer);
  }, [current, result, isPaused]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const tag = target?.tagName?.toLowerCase();
      const isTextInput = tag === 'textarea' || (tag === 'input' && !['radio', 'checkbox'].includes((target as HTMLInputElement).type?.toLowerCase()));
      if (isTextInput) return;

      if (e.key === 'p' || e.key === 'P') {
        if (current && !result) {
          e.preventDefault();
          togglePause();
        }
      } else if (e.code === 'Space') {
        if (isPaused) {
          e.preventDefault();
          togglePause(false);
        } else if (result && !busy && session && session.status !== 'completed' && reviewIndex === null) {
          e.preventDefault();
          next();
        }
      } else if (e.key === 'Enter') {
        if (result && !busy && session && session.status !== 'completed' && reviewIndex === null) {
          e.preventDefault();
          next();
        }
      } else if (e.key === 'Escape') {
        if (zoomImage) {
          setZoomImage(null);
        } else if (isPaused) {
          togglePause(false);
        } else if (reviewIndex !== null) {
          handleReturnCurrent();
        }
      } else if (current && !result && !isPaused && !busy) {
        const upper = e.key.toUpperCase();
        if (['A', 'B', 'C', 'D'].includes(upper)) {
          if (current.question.options && upper in current.question.options) {
            updateDraft({
              ...draft,
              selected: upper,
              changed: draft.changed || (!!draft.selected && draft.selected !== upper),
            });
          }
        } else if (['1', '2', '3'].includes(e.key)) {
          const confValues = [0.2, 0.5, 0.9];
          const val = confValues[Number(e.key) - 1];
          updateDraft({
            ...draft,
            confidence: draft.confidence === val ? null : val,
          });
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [current, result, isPaused, zoomImage, busy, session, reviewIndex, draft]);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.hidden && current && !result && !isPaused) {
        togglePause(true);
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, [current, result, isPaused]);

  function updateDraft(nextDraft: Draft) {
    setDraft(nextDraft);
    if (current) write(`draft:${current.attempt_id}`, JSON.stringify(nextDraft));
  }

  function start() { void perform(async () => {
    const created = await api<{ id: string | null; total: number; reused: boolean }>('/review/session', {});
    if (!created.id) { await readStatus(); return; }
    write(SESSION_KEY, created.id);
    window.history.replaceState(null, '', `/review?session=${encodeURIComponent(created.id)}`);
    await load(created.id);
    await readStatus();
  }); }

  function submit() {
    if (!session || !current) return;
    void perform(async () => {
      const currentSnapshot = current;
      cacheQuestion(currentSnapshot.question);
      const totalPaused = Math.round(pausedMsRef.current + (isPaused && pauseStartRef.current > 0 ? performance.now() - pauseStartRef.current : 0));
      const saved = await api<Result>(`/quiz/${session.id}/answer`, {
        attempt_id: current.attempt_id,
        // 允许不选任何答案直接提交（未作答/不会）；选项与信心均可留空。
        selected_answer: draft.selected || null,
        confidence: draft.confidence,
        changed_answer: draft.changed,
        paused_ms: totalPaused,
      });

      const fullResult: Result = {
        ...saved,
        stem: saved.stem || currentSnapshot.question.stem,
        options: saved.options || currentSnapshot.question.options,
        stem_assets: (saved.stem_assets && saved.stem_assets.length > 0) ? saved.stem_assets : currentSnapshot.question.stem_assets,
        module: saved.module || currentSnapshot.question.module,
      };

      setResult(fullResult);
      setHistory(prev => [...prev.filter(r => r.id !== saved.id), fullResult]);

      if (!saved.correct) {
        setJustGradedAttemptId(saved.id);
      } else {
        setJustGradedAttemptId(null);
      }

      setCurrent(null);
      setReviewIndex(null);
      const updatedSession = await api<Session>(`/quiz/${session.id}`);
      setSession(updatedSession);
      await readStatus();
      loadDailyGoal();
    });
  }

  function next() { void perform(async () => {
    if (!session) return;
    setJustGradedAttemptId(null);
    setReviewIndex(null);
    setResult(null);
    const value = await api<Current | { done: true }>(`/quiz/${session.id}/next`);
    if (!value.done) {
      present(value);
    } else {
      await load(session.id);
    }
  }); }

  function handleSelectReview(index: number) {
    const item = history[index];
    if (!item) return;
    setReviewIndex(index);
    setResult(item);
  }

  function handleReturnCurrent() {
    setReviewIndex(null);
    setResult(null);
  }

  async function requestDiagnosis() {
    if (!result || aiWorking) return;
    setAiWorking(true); setAiStatus('AI 正在分析错因…');
    try {
      const res = await api<DiagnosisOutput>(`/attempts/${result.id}/diagnose`, {});
      setDiagnosis(res);
      write(`diag:${result.id}`, JSON.stringify(res));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '错因诊断生成失败');
    } finally { setAiWorking(false); setAiStatus(''); }
  }

  const dueCount = status?.due_count ?? 0;
  const isSessionCompleted = session?.status === 'completed' || (session && session.total > 0 && session.answered >= session.total);
  const correctCount = history.filter(h => h.correct).length;
  const sessionTotal = session?.total || 25;

  return (
    <main>
      <header>
        <Link href="/dashboard" className="brand">
          <span className="brand-icon">学</span>公考 Learning OS
        </Link>
        <nav>
          <Link href="/dashboard">学习概览</Link>
          <Link href="/framework">知识框架</Link>
          <Link href="/quiz">行测训练</Link>
          <Link href="/review" className="active">到期复习</Link>
          <Link href="/notes">我的笔记</Link>
          <Link href="/exam">全真模考</Link>
          <Link href="/shenlun">申论工作台</Link>
          <Link href="/importer">题库导入</Link>
        <Link href="/settings">设置</Link></nav>
        <span className="local">● 本地学习空间</span>
      </header>

      <div className="intro">
        <span className="eyebrow">REVIEW DRILL / 到期复习重刷</span>
        <h1>在该复习的时候，重新独立做一次。</h1>
        <p>纯净题目重做，不提前泄露答案。作答后再评测，检验真实记忆与解题能力。</p>
      </div>

      <div className={`workspace ${result ? 'review-mode' : ''}`} style={result ? { gridTemplateColumns: '1fr' } : undefined}>
        <section className="card" aria-label="到期复习">
          <div className="card-top">
            <span style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <strong>🔄 到期重刷</strong>
              {dailyGoal && (
                <span style={{
                  fontSize: 11,
                  fontWeight: 600,
                  background: '#f1f5f9',
                  color: '#334155',
                  padding: '2px 8px',
                  borderRadius: 10,
                  border: '1px solid #cbd5e1'
                }}>
                  🎯 今日已刷：<strong style={{ color: 'var(--accent)' }}>{dailyGoal.completed}</strong> / 500 题 (含复习)
                </span>
              )}
            </span>
            <span>
              {session ? `重刷进度 ${session.answered} / ${session.total}` : `待复习题池 ${dueCount} 道`}
            </span>
          </div>

          {session && session.total > 0 && (
            <div style={{ padding: '8px 16px', background: '#f8fafc', borderBottom: '1px solid var(--line)' }}>
              <ReviewAnswerSheet
                total={session.total}
                history={history}
                reviewIndex={reviewIndex}
                busy={busy}
                onSelectReview={handleSelectReview}
                onReturnCurrent={handleReturnCurrent}
              />
            </div>
          )}

          {error && (
            <div role="alert" className="error">
              {error}
              <button disabled={busy} onClick={() => void perform(async () => { if (session) await load(session.id); await readStatus(); })}>
                重新同步
              </button>
            </div>
          )}

          {busy && !current && !result && <p role="status" style={{ padding: 24, color: 'var(--muted)' }}>正在载入待刷题目…</p>}

          {!session && !busy && dueCount === 0 && (
            <div className="welcome">
              <h2>今天没有到期题目</h2>
              <p>现有复习卡都还没有到期。你仍然可以继续行测日常训练，新的作答会自动排期进复习计划。</p>
              <Link className="primary-link" href="/quiz">去行测训练</Link>
            </div>
          )}

          {!session && !busy && dueCount > 0 && (
            <div className="welcome">
              <h2>有 {dueCount} 道题等待复习重刷</h2>
              <p>进入后将以全新无答案状态重做这批题目，支持答题卡切题、计时与快速提交。</p>
              <button className="primary" onClick={start}>开始重刷（25题）</button>
            </div>
          )}

          {/* 会话已全部完成且当前不在回看单题状态时的整轮结算卡片 */}
          {isSessionCompleted && !result && (
            <div className="welcome" style={{ padding: '36px 24px', textAlign: 'center' }}>
              <div style={{ fontSize: 44, marginBottom: 12 }}>🎉</div>
              <h2>本轮复习重刷已全部完成！</h2>
              <p style={{ color: 'var(--muted)', marginTop: 8 }}>
                共重刷 <strong>{sessionTotal}</strong> 题 · 答对 <strong>{correctCount}</strong> 题 · 正确率 <strong>{Math.round((correctCount / (sessionTotal || 1)) * 100)}%</strong>
              </p>
              <div style={{ display: 'flex', gap: 12, justifyContent: 'center', marginTop: 24 }}>
                <Link className="secondary-link" href="/dashboard">查看学习概览</Link>
                {dueCount > 0 ? (
                  <button className="primary" disabled={busy} onClick={start}>继续下一轮重刷</button>
                ) : (
                  <Link className="primary-link" href="/quiz">去日常训练刷题</Link>
                )}
              </div>
            </div>
          )}

          {/* 纯净待答做题界面：绝无答案泄漏，原汁原味重刷 */}
          {current && !result && (
            <>
              <div className="question-meta">
                <span className="pill">{current.question.module}</span>
                <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>
                  第 {history.length + 1} 题 / 共 {session?.total || 25} 题
                </span>
                <span>已用时 <strong data-testid="timer">{format(elapsed)}</strong></span>
                <button
                  type="button"
                  onClick={() => togglePause()}
                  style={{
                    marginLeft: 'auto',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 5,
                    padding: '4px 10px',
                    fontSize: 12,
                    fontWeight: 600,
                    borderRadius: 6,
                    border: '1px solid var(--border)',
                    background: isPaused ? '#fef3c7' : '#f8fafc',
                    color: isPaused ? '#b45309' : '#475569',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease'
                  }}
                  title="按 P 键或空格键暂停/恢复"
                >
                  {isPaused ? '▶ 继续作答 (P)' : '⏸ 暂停 (P)'}
                </button>
              </div>

              <div style={{ position: 'relative', marginTop: 10 }}>
                <div style={{
                  filter: isPaused ? 'blur(14px)' : 'none',
                  userSelect: isPaused ? 'none' : 'auto',
                  pointerEvents: isPaused ? 'none' : 'auto',
                  transition: 'filter 0.2s ease',
                }}>
                  {current.question.passage && (
                    <div className="passage-card" style={{ margin: '14px 0', padding: '14px 18px', background: '#f8fafc', border: '1px solid #cbd5e1', borderRadius: 8 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                        <span style={{ fontSize: 11, background: '#e2e8f0', color: '#334155', padding: '2px 8px', borderRadius: 4, fontWeight: 700 }}>
                          📑 资料/篇章背景材料
                        </span>
                        <small style={{ color: 'var(--muted)', fontSize: 11 }}>本组题目均根据此材料作答</small>
                      </div>
                      {current.question.passage.content && (
                        <div style={{ fontSize: 14, lineHeight: 1.8, color: '#1e293b', whiteSpace: 'pre-wrap', maxHeight: 320, overflowY: 'auto' }}>
                          {current.question.passage.content}
                        </div>
                      )}
                      {current.question.passage.assets && current.question.passage.assets.length > 0 && (
                        <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                          {current.question.passage.assets.map((asset, aIdx) => (
                            <img
                              key={aIdx}
                              src={asset}
                              alt={`材料配图 ${aIdx + 1}`}
                              onClick={() => setZoomImage(asset)}
                              style={{ maxWidth: '100%', maxHeight: 380, objectFit: 'contain', borderRadius: 6, border: '1px solid #e2e8f0', background: '#fff', padding: 6, cursor: 'zoom-in' }}
                              title="点击全屏高清放大"
                            />
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  <h2 className="stem"><FormattedStem text={current.question.stem} /></h2>

                  {current.question.stem_assets && current.question.stem_assets.length > 0 && (
                    <div className="stem-assets" style={{ margin: '14px 0', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
                      {current.question.stem_assets.map((asset, idx) => (
                        <img
                          key={idx}
                          src={asset}
                          alt={`题面图 ${idx + 1}`}
                          onClick={() => setZoomImage(asset)}
                          style={{ maxWidth: '100%', maxHeight: 520, objectFit: 'contain', borderRadius: 6, border: '1px solid #e2e8f0', background: '#fff', padding: 8, cursor: 'zoom-in', boxShadow: '0 1px 4px rgba(0,0,0,0.06)' }}
                          title="点击全屏高清放大"
                        />
                      ))}
                    </div>
                  )}

                  <fieldset disabled={busy} className="options">
                    <legend className="sr-only">选择一个答案</legend>
                    {Object.entries(current.question.options).map(([key, value]) => (
                      <label key={key} className={draft.selected === key ? 'option selected' : 'option'}>
                        <input
                          type="radio"
                          name="answer"
                          value={key}
                          checked={draft.selected === key}
                          onChange={() => updateDraft({ ...draft, selected: key, changed: draft.changed || (!!draft.selected && draft.selected !== key) })}
                        />
                        <span>{value === key || !value ? key : `${key}. ${value}`}</span>
                      </label>
                    ))}
                  </fieldset>

                  <fieldset disabled={busy} className="confidence">
                    <legend>你有多大把握？<span>可选 · 键盘 1-3 快速选择，再次点击可取消</span></legend>
                    <div>
                      {CONFIDENCE_TIERS.map(tier => (
                        <label
                          key={tier.value}
                          className={draft.confidence === tier.value ? 'selected' : ''}
                        >
                          <input
                            type="radio"
                            name="confidence"
                            value={tier.value}
                            checked={draft.confidence === tier.value}
                            onClick={() => {
                              if (draft.confidence === tier.value) {
                                updateDraft({ ...draft, confidence: null });
                              }
                            }}
                            onChange={() => {
                              updateDraft({ ...draft, confidence: tier.value });
                            }}
                          />
                          {tier.label}
                        </label>
                      ))}
                    </div>
                    <p>纯蒙题＝基本在猜 · 半猜＝有思路没把握 · 有信心＝基本确定；不选则不记录信心。</p>
                  </fieldset>

                  <div className="submit-row">
                    <span className="muted">{current.question.source || '复习到期真题'}</span>
                    <div style={{ display: 'flex', gap: 8 }}>
                      {!draft.selected && (
                        <button
                          type="button"
                          className="secondary"
                          disabled={busy}
                          title="按“未作答/不会”记录本题并结束作答，直接进入解析"
                          onClick={submit}
                        >
                          不会，直接提交
                        </button>
                      )}
                      <button
                        className="primary"
                        disabled={busy || !draft.selected}
                        onClick={submit}
                      >
                        {busy ? '正在判分…' : '提交重刷答案'}
                      </button>
                    </div>
                  </div>
                </div>

                {isPaused && (
                  <div style={{
                    position: 'absolute',
                    inset: 0,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    backgroundColor: 'rgba(255, 255, 255, 0.88)',
                    backdropFilter: 'blur(8px)',
                    zIndex: 30,
                    borderRadius: 12,
                    padding: 24,
                    textAlign: 'center',
                    minHeight: 380,
                  }}>
                    <div style={{ fontSize: 44, marginBottom: 12 }}>⏸️</div>
                    <h3 style={{ fontSize: 20, fontWeight: 700, margin: '0 0 8px', color: '#1e293b' }}>复习已暂停</h3>
                    <p style={{ color: '#64748b', fontSize: 14, maxWidth: 360, margin: '0 0 16px', lineHeight: 1.6 }}>
                      计时已冻结，题面已安全遮挡。<br />准备好后按空格继续。
                    </p>
                    <div style={{ display: 'flex', gap: 12 }}>
                      <button
                        type="button"
                        className="primary"
                        onClick={() => togglePause(false)}
                        style={{ padding: '10px 24px', fontSize: 15, fontWeight: 600 }}
                      >
                        ▶ 继续作答 (空格 / P)
                      </button>
                      <Link
                        href="/dashboard"
                        className="secondary"
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          padding: '10px 18px',
                          textDecoration: 'none',
                          borderRadius: 6,
                          fontSize: 14,
                          color: 'var(--text)',
                          border: '1px solid var(--border)'
                        }}
                      >
                        返回学习概览
                      </Link>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}

          {/* 作答提交后反馈 或 答题卡主动回看单题状态 */}
          {result && (
            <div className="result review-comparison-view" aria-live="polite">
              {reviewIndex !== null && (
                <div style={{
                  padding: '8px 12px',
                  background: '#eff6ff',
                  borderRadius: 6,
                  color: '#1d4ed8',
                  fontSize: 13,
                  fontWeight: 600,
                  marginBottom: 10,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between'
                }}>
                  <span>📌 正在回看第 {reviewIndex + 1} 题作答详情</span>
                  <button
                    type="button"
                    onClick={handleReturnCurrent}
                    style={{
                      background: '#fff',
                      border: '1px solid #bfdbfe',
                      padding: '2px 10px',
                      borderRadius: 4,
                      cursor: 'pointer',
                      fontSize: 12,
                      fontWeight: 700,
                      color: '#1e40af'
                    }}
                  >
                    返回当前待刷题 ➔
                  </button>
                </div>
              )}

              {!result.correct && <ReviewTeachingLink attemptId={result.id} />}

              <div className="review-summary-bar">
                <div className="review-summary-left">
                  <span className="pill" style={{ background: result.correct ? '#edf5ef' : '#fff1eb', color: result.correct ? 'var(--accent)' : '#b91c1c' }}>
                    {result.correct ? '✓ 重刷回答正确' : (!result.selected_answer ? '✗ 未作答 · 已按不会记录' : '✗ 重刷未通过 · 需巩固')}
                  </span>
                  <h2>{result.correct ? '回答正确' : (!result.selected_answer ? '未作答，直接看解析' : '再巩固一次')}</h2>
                  {!result.correct && !result.selected_answer && (
                    <p style={{ margin: '6px 0 0', fontSize: 12.5, color: '#64748b' }}>
                      本题已按“未作答／不会”如实记录并结束作答{String(result.audit_note || '').includes('跳过教学重答') ? '；本次在获取提示后提交，属于跳过教学重答，不计入正式统计，也不改变首次成绩' : '，已计入正式统计与复习计划'}。
                    </p>
                  )}
                </div>
                <div className="review-metrics-compact">
                  <div className="metric-pill">
                    <small>你的选择</small>
                    <strong style={{ color: result.correct ? 'var(--accent)' : '#b91c1c' }}>{result.selected_answer ?? '未作答'}</strong>
                  </div>
                  <div className="metric-pill">
                    <small>本题用时</small>
                    <strong><RecordedTime elapsedMs={result.elapsed_ms} timingValid={result.timing_valid} /></strong>
                  </div>
                  <div className="metric-pill">
                    <small>作答把握</small>
                    <strong>{confidenceLabel(result.confidence)}</strong>
                  </div>
                </div>
              </div>

              <div className="comparison-grid">
                <QuestionReviewCard result={result} revealAnswer={true} />

                <div className="panel-explanation-review">
                  <InteractiveReviewCard
                    attemptId={result.id}
                    isCorrect={result.correct}
                    confidence={result.confidence}
                    stem={result.stem}
                    module={result.module}
                    justGraded={justGradedAttemptId === result.id}
                  />

                  {result.review_schedule && (
                    <div className="review-update" style={{ margin: '8px 0' }}>
                      <strong>FSRS 计划已更新</strong>
                      <span>下次到期：{formatDue(result.review_schedule.due)}</span>
                      <small>累计复习 {result.review_schedule.review_count} 次</small>
                    </div>
                  )}

                  {session?.status === 'completed' || (session && session.total > 0 && session.answered >= session.total) ? (
                    <div style={{ marginTop: 14 }}>
                      <p className="completion">本轮复习已完成，{session?.total || 25} 道作答均已记录。</p>
                      <div className="result-actions">
                        <Link className="secondary-link" href="/dashboard">查看学习概览</Link>
                        {dueCount > 0 ? (
                          <button className="primary" disabled={busy} onClick={start}>继续下一轮重刷</button>
                        ) : (
                          <Link className="primary-link" href="/quiz">继续日常训练</Link>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div style={{ marginTop: 14, display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
                      <button
                        className="primary"
                        style={{ minWidth: 140, padding: '10px 20px', fontSize: 14, fontWeight: 700 }}
                        disabled={busy}
                        onClick={next}
                      >
                        {busy ? '正在载入…' : '下一题 (Enter) ➔'}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </section>

        {!result && (
          <aside>
            <div className="note">
              <span className="eyebrow">间隔复习机制</span>
              <h2>时间由系统排期，作答由你独立完成。</h2>
              <p>采用 FSRS-6 确定性遗忘算法，每次作答后根据正确性、用时与把握度动态计算下一轮复习时间。</p>
              <hr/>
              <p><b>01</b> 优先以白纸原题重刷，严禁提前剧透答案</p>
              <p><b>02</b> 支持答题卡随时切题与回看已答错题</p>
              <p><b>03</b> 重刷答对自动推迟复习，攻克薄弱环节</p>
            </div>
            <p className="aside-note">复习重刷会话已在服务端持久化，中途离开或刷新将自动恢复待刷题目。</p>
          </aside>
        )}
      </div>

      <footer>到期复习重刷<span>FSRS 间隔复习 / 独立作答 / 错题巩固</span></footer>

      {zoomImage && (
        <div
          onClick={() => setZoomImage(null)}
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.78)',
            backdropFilter: 'blur(5px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            cursor: 'zoom-out',
            padding: 24,
          }}
        >
          <div style={{ position: 'relative', maxWidth: '92vw', maxHeight: '92vh' }} onClick={e => e.stopPropagation()}>
            <img
              src={zoomImage}
              alt="放大预览"
              style={{ maxWidth: '100%', maxHeight: '90vh', objectFit: 'contain', borderRadius: 8, boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)' }}
            />
            <button
              type="button"
              onClick={() => setZoomImage(null)}
              style={{
                position: 'absolute',
                top: -14,
                right: -14,
                background: '#ef4444',
                color: '#fff',
                border: 'none',
                borderRadius: '50%',
                width: 32,
                height: 32,
                cursor: 'pointer',
                fontSize: 18,
                fontWeight: 'bold',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: '0 2px 6px rgba(0,0,0,0.3)'
              }}
              title="关闭 (Esc)"
            >
              ×
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
