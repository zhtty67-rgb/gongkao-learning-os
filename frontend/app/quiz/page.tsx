'use client';

import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import Link from 'next/link';
import {
  api,
  ApiError,
  Current,
  DailyGoal,
  DiagnosisOutput,
  ErrorEvent,
  GroupQuestionItem,
  GroupSubmitResult,
  HintOutput,
  MasteryData,
  Question,
  QuizGroup,
  Result,
  Session,
  TutorExplanationOutput,
} from '../../lib/api';
import { QuestionReviewCard } from '../../lib/QuestionReviewCard';
import { InteractiveReviewCard } from '../../lib/InteractiveReviewCard';
import { RecordedTime } from '../../lib/RecordedTime';
import { FormattedStem } from '../../lib/FormattedStem';
import { FormattedExplanation } from '../../lib/FormattedExplanation';
import { DeviceSyncModal } from '../../lib/DeviceSyncModal';
import { buildForest } from '../../lib/framework/model';
import { CONFIDENCE_TIERS, CONFIDENCE_DRAFT_VALUES, confidenceLabel } from '../../lib/confidence';

const SESSION_KEY = 'gongkao-session';
const questionCache = new Map<string, Question>();
function cacheQuestion(q: Question) {
  if (q && q.id) {
    questionCache.set(q.id, q);
    try {
      sessionStorage.setItem(`q_cache:${q.id}`, JSON.stringify(q));
    } catch { /* ignore */ }
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
const ERROR_TYPES = [
  ['knowledge_gap', '知识缺口'], ['conceptual_error', '概念理解'], ['method_selection', '方法选择'],
  ['reading_error', '审题偏差'], ['calculation_error', '计算失误'], ['time_pressure', '时间压力'],
  ['careless_error', '粗心失误'], ['transfer_failure', '迁移困难'], ['unknown', '尚不确定'],
] as const;
type Draft = { selected: string; confidence: number | null; changed: boolean };
function read(key: string) { try { return localStorage.getItem(key); } catch { return null; } }
function write(key: string, value: string) { try { localStorage.setItem(key, value); } catch { /* URL still restores the server session. */ } }
function format(ms: number) { const s = Math.floor(ms / 1000); return `${Math.floor(s / 60).toString().padStart(2, '0')}:${(s % 60).toString().padStart(2, '0')}`; }
function getOptionsGridClass(options?: Record<string, string>): string {
  if (!options) return '';
  const entries = Object.entries(options);
  if (entries.length === 0) return '';
  const isAllSingleLetter = entries.every(([k, v]) => !v || v.trim() === k || v.trim().length <= 2);
  if (isAllSingleLetter) return 'options-letters';
  const maxLen = Math.max(...entries.map(([k, v]) => (v ? v.length : 0)));
  if (maxLen <= 10) return 'options-compact';
  return '';
}

interface QuizAnswerSheetProps {
  total: number;
  history: Result[];
  reviewIndex: number | null;
  busy: boolean;
  onSelectReview: (index: number) => void;
  onReturnCurrent: () => void;
}

const QuizAnswerSheet = memo(function QuizAnswerSheet({
  total,
  history,
  reviewIndex,
  busy,
  onSelectReview,
  onReturnCurrent,
}: QuizAnswerSheetProps) {
  const answeredCount = history.length;
  const isHuge = total > 40;
  const ANSWERED_PAGE_SIZE = 25;
  const totalPages = Math.ceil(answeredCount / ANSWERED_PAGE_SIZE) || 1;

  const [page, setPage] = useState<number>(() => Math.max(0, totalPages - 1));

  // 当外部 reviewIndex 变化时（如键盘方向键回看），自动同步展示对应页
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
    <div className="quiz-chips-bar" role="navigation" aria-label="答题卡（点击回看已答题目）">
      <span style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 600, marginRight: 2 }}>
        答题卡 ({answeredCount}/{total})
      </span>

      {isHuge && totalPages > 1 && (
        <span className="quiz-chips-pagination" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginRight: 4 }}>
          <button
            type="button"
            className="quiz-page-btn"
            disabled={activePage <= 0 || busy}
            onClick={() => setPage(p => Math.max(0, p - 1))}
            style={{ fontSize: 10, padding: '2px 5px', borderRadius: 4, border: '1px solid var(--line)', background: '#fff', cursor: 'pointer' }}
            title="查看上一组已答题"
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
            title="查看下一组已答题"
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
                : (isCurrentPending ? '当前待答题' : `第 ${i + 1} 题 · 未作答`)
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
          +{remainingCount} 题待答
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
          返回当前题
        </button>
      )}
    </div>
  );
});

export type ErrorRecorderHandle = {
  flush: () => Promise<void>;
};

const ErrorRecorder = forwardRef<ErrorRecorderHandle, { attemptId: string; initial: ErrorEvent | null }>(
  function ErrorRecorder({ attemptId, initial }, ref) {
    const [type, setType] = useState(initial?.error_type || '');
    const [explanation, setExplanation] = useState(initial?.explanation || '');
    const [saved, setSaved] = useState(initial ? '错因已记录' : '');
    const [hasRecord, setHasRecord] = useState(Boolean(initial));
    const [working, setWorking] = useState(false);
    const [message, setMessage] = useState('');

    const latestSavedRef = useRef<{ type: string; explanation: string }>({
      type: initial?.error_type || '',
      explanation: initial?.explanation || '',
    });
    const debounceTimerRef = useRef<NodeJS.Timeout | null>(null);

    const performSave = useCallback(async (targetType: string, targetExpl: string) => {
      if (!targetType) return;
      if (
        hasRecord &&
        latestSavedRef.current.type === targetType &&
        latestSavedRef.current.explanation === targetExpl
      ) {
        setSaved('错因已记录');
        return;
      }
      setWorking(true);
      setMessage('');
      try {
        await api(`/attempts/${attemptId}/error`, { error_type: targetType, explanation: targetExpl });
        latestSavedRef.current = { type: targetType, explanation: targetExpl };
        setHasRecord(true);
        setSaved('错因已记录');
      } catch (error) {
        setMessage(error instanceof ApiError ? error.message : '保存失败，请重试。');
      } finally {
        setWorking(false);
      }
    }, [attemptId, hasRecord]);

    useImperativeHandle(ref, () => ({
      flush: async () => {
        if (debounceTimerRef.current) {
          clearTimeout(debounceTimerRef.current);
          debounceTimerRef.current = null;
        }
        if (type) {
          await performSave(type, explanation);
        }
      },
    }), [type, explanation, performSave]);

    const handleSelectType = (val: string) => {
      setType(val);
      setMessage('');
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = null;
      }
      void performSave(val, explanation);
    };

    const handleExplanationChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
      const val = event.target.value;
      setExplanation(val);
      setSaved('');
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
      if (type) {
        debounceTimerRef.current = setTimeout(() => {
          void performSave(type, val);
        }, 500);
      }
    };

    const handleBlur = () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = null;
      }
      if (type) {
        void performSave(type, explanation);
      }
    };

    return (
      <section className="error-recorder" aria-label="错因记录">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4, gap: 8 }}>
          <h3 style={{ margin: 0 }}>这道题为什么错？</h3>
          <span role={message ? 'alert' : 'status'} style={{ fontSize: 12, fontWeight: 500, color: message ? '#b91c1c' : 'var(--accent)' }}>
            {message ? `⚠️ ${message}` : working ? '正在保存…' : (saved || (type ? '已记录' : '点击即自动记录'))}
          </span>
        </div>
        <p>选择最接近的原因，点击即自动记录到错题本。</p>
        <div className="error-types">
          {ERROR_TYPES.map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={type === value ? 'selected' : ''}
              onClick={() => handleSelectType(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="error-note">
          补充说明（可选，输入后自动保存）
          <textarea
            maxLength={500}
            value={explanation}
            onChange={handleExplanationChange}
            onBlur={handleBlur}
            placeholder="例如：把充分条件看成了必要条件"
          />
        </label>
      </section>
    );
  }
);

const SECTION_NAMES: Record<string, string> = {
  "政治理论": "政治理论",
  "常识判断": "第一部分 · 常识判断",
  "言语理解": "第二部分 · 言语理解与表达",
  "数量关系": "第三部分 · 数量关系",
  "图形推理": "第四部分 · 图形推理",
  "立体图推": "第四部分 · 图形推理",
  "定义判断": "第四部分 · 定义判断",
  "类比推理": "第四部分 · 类比推理",
  "逻辑判断": "第四部分 · 逻辑判断",
  "资料分析": "第五部分 · 资料分析",
};

export interface QuizModuleItem {
  id: string;
  name: string;
  total: number;
  unpracticed: number;
  submodules?: Array<{
    id: string;
    name: string;
    total: number;
    unpracticed: number;
  }>;
}

export default function Quiz() {
  const [session, setSession] = useState<Session | null>(null);
  const [current, setCurrent] = useState<Current | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [history, setHistory] = useState<Result[]>([]);
  const [reviewIndex, setReviewIndex] = useState<number | null>(null);
  const [hint, setHint] = useState<HintOutput | null>(null);
  const [diagnosis, setDiagnosis] = useState<DiagnosisOutput | null>(null);
  const [explanation, setExplanation] = useState<TutorExplanationOutput | null>(null);
  const [aiWorking, setAiWorking] = useState(false);
  const [aiStatus, setAiStatus] = useState('');
  const [draft, setDraft] = useState<Draft>({ selected: '', confidence: null, changed: false });
  const [elapsed, setElapsed] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [isPaused, setIsPaused] = useState(false);
  const [zoomImage, setZoomImage] = useState<string | null>(null);
  const [bankTotal, setBankTotal] = useState<number | null>(null);
  const [dailyGoal, setDailyGoal] = useState<DailyGoal | null>(null);
  const [selectedSize, setSelectedSize] = useState<number>(20);
  const [modulesData, setModulesData] = useState<QuizModuleItem[]>([]);
  const [selectedModule, setSelectedModule] = useState<string>('ALL');
  const [showSyncModal, setShowSyncModal] = useState(false);
  const [showTrainingSetup, setShowTrainingSetup] = useState(false);

  // 资料分析五题整组专属状态
  const [groupData, setGroupData] = useState<QuizGroup | null>(null);
  const [activeQIndex, setActiveQIndex] = useState<number>(0);
  const [reviewQIndex, setReviewQIndex] = useState<number>(0);
  const [groupDrafts, setGroupDrafts] = useState<Record<string, Draft>>({});
  const [passageZoom, setPassageZoom] = useState<number>(100);
  const [showUnansweredConfirm, setShowUnansweredConfirm] = useState<boolean>(false);
  const [justGradedAttemptId, setJustGradedAttemptId] = useState<string | null>(null);
  // 历史组回看：整组模式下回看已结算组的只读视图；null 表示正在当前组作答/复盘。
  const [pastGroup, setPastGroup] = useState<QuizGroup | null>(null);

  const initialized = useRef(false);
  const lock = useRef(false);
  const timerOrigin = useRef({ base: 0, tick: 0 });
  const pausedMsRef = useRef(0);
  const pauseStartRef = useRef(0);
  const errorRecorderRef = useRef<ErrorRecorderHandle | null>(null);

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
    setCurrent(value); setResult(null);
    setReviewIndex(null);
    setGroupData(null);
    setPastGroup(null);
    setJustGradedAttemptId(null);
    setHint(null); setDiagnosis(null); setExplanation(null);
    setIsPaused(false);
    pausedMsRef.current = 0;
    pauseStartRef.current = 0;
    setZoomImage(null);
    errorRecorderRef.current = null;
    const base = Math.max(0, Date.parse(value.server_now) - Date.parse(value.started_at));
    timerOrigin.current = { base, tick: performance.now() };
    setElapsed(base);
    let restored: Draft = { selected: '', confidence: null, changed: false };
    try {
      const saved = JSON.parse(read(`draft:${value.attempt_id}`) || 'null');
      if (saved && ['', 'A', 'B', 'C', 'D'].includes(saved.selected) && CONFIDENCE_DRAFT_VALUES.includes(saved.confidence)) restored = { selected: saved.selected, confidence: saved.confidence, changed: saved.changed === true };
    } catch { /* Ignore malformed browser draft. */ }
    setDraft(restored);
  }

  async function load(sid: string) {
    const state = await api<Session>(`/quiz/${sid}`);
    setSession(state);
    setPastGroup(null);
    // 回看数据：已答题目按题序返回；获取失败不阻塞作答流程。
    api<{ answered: Result[] }>(`/quiz/${sid}/answered`)
      .then(res => setHistory(res.answered || []))
      .catch(() => {});

    // 优先尝试获取五题整组数据（资料分析 / 材料篇章）
    if (state.current?.question.passage || state.latest_result?.passage || selectedModule === '资料分析') {
    try {
      const grp = await api<QuizGroup>(`/quiz/${sid}/group`);
      if (grp && (grp.passage || (selectedModule === '资料分析' && grp.questions && grp.questions.length > 1))) {
        setGroupData(grp);
        setReviewIndex(null);
        setActiveQIndex(0);
        setReviewQIndex(0);
        for (const q of grp.questions) {
          cacheQuestion(q.question);
        }
        const restored: Record<string, Draft> = {};
        for (const q of grp.questions) {
          try {
            const saved = JSON.parse(read(`draft:${sid}:${q.question_id}`) || 'null');
            if (saved && ['', 'A', 'B', 'C', 'D'].includes(saved.selected)) {
              restored[q.question_id] = saved;
            } else if (q.selected_answer) {
              restored[q.question_id] = { selected: q.selected_answer, confidence: q.confidence ?? null, changed: false };
            } else {
              restored[q.question_id] = { selected: '', confidence: null, changed: false };
            }
          } catch {
            restored[q.question_id] = { selected: '', confidence: null, changed: false };
          }
        }
        setGroupDrafts(restored);
        setCurrent(null);
        setResult(null);

        const base = Math.max(0, Date.parse(grp.server_now) - Date.parse(grp.started_at));
        timerOrigin.current = { base, tick: performance.now() };
        setElapsed(base);
        setIsPaused(false);
        pausedMsRef.current = 0;
        pauseStartRef.current = 0;
        return;
      }
    } catch {
      // 非整组材料题，平滑回退至单题常规模式
    }
    }

    setGroupData(null);
    if (state.current) {
      cacheQuestion(state.current.question);
      present(state.current);
    } else if (state.latest_result) {
      const qid = state.latest_result.question_id;
      const cached = getCachedQuestion(qid);
      setCurrent(null);
      const savedDiag = read(`diag:${state.latest_result.id}`);
      if (savedDiag) {
        try { setDiagnosis(JSON.parse(savedDiag)); } catch { /* ignore */ }
      }
      setResult(prev => {
        const mergedStem = state.latest_result?.stem || prev?.stem || cached?.stem;
        const mergedOptions = state.latest_result?.options || prev?.options || cached?.options;
        const mergedModule = state.latest_result?.module || prev?.module || cached?.module;
        const mergedAssets = (state.latest_result?.stem_assets && state.latest_result.stem_assets.length > 0)
          ? state.latest_result.stem_assets
          : (prev?.stem_assets || cached?.stem_assets);
        return {
          ...state.latest_result!,
          stem: mergedStem,
          options: mergedOptions,
          module: mergedModule,
          stem_assets: mergedAssets,
        };
      });
    } else {
      const value = await api<Current | { done: true }>(`/quiz/${sid}/next`);
      if (!value.done) present(value);
    }
  }

  async function perform(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try { await action(); }
    catch (e) { setError(e instanceof ApiError ? e.message : '连接失败。请确认后端已启动，然后重试；已保存的数据不会丢失。'); }
    finally { lock.current = false; setBusy(false); }
  }

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    loadDailyGoal();
    Promise.all([
      api<{ modules: QuizModuleItem[]; total: number }>('/quiz/modules'),
      api<MasteryData>('/mastery').catch(() => null),
    ]).then(([res, mastery]) => {
      const bankModules = res.modules.flatMap(m => m.submodules?.length ? m.submodules : [m]);
      const forest = mastery ? buildForest(mastery.nodes.filter(n => n.subject === '行测')) : null;
      const categories = forest?.modules.length ? forest.modules.map(id => ({
        id, name: forest.rootsByModule[id].find(n => n.node_type === 'module')?.name || id,
        total: bankModules.find(m => m.id === id)?.total || 0,
        unpracticed: bankModules.find(m => m.id === id)?.unpracticed || 0,
      })) : bankModules.filter(m => m.id !== 'ALL');
      setModulesData([{id:'ALL',name:'全部模块',total:res.total,unpracticed:res.modules.find(m => m.id === 'ALL')?.unpracticed || 0}, ...categories]);
    })
      .catch(() => {});
    api<{ status: string; questions: number }>('/health')
      .then(res => { if (res && typeof res.questions === 'number') setBankTotal(res.questions); })
      .catch(() => {});
    const urlSid = new URLSearchParams(window.location.search).get('session');
    const localSid = read(SESSION_KEY);
    if (urlSid) {
      void perform(() => load(urlSid));
      return;
    }
    // 跨设备统一进度：优先接续服务端最近活跃的训练会话，本地指针仅作兜底。
    api<{ id: string } | null>('/quiz/current')
      .then(remote => {
        const sid = remote?.id || localSid;
        if (sid) {
          write(SESSION_KEY, sid);
          window.history.replaceState(null, '', `/quiz?session=${encodeURIComponent(sid)}`);
          void perform(() => load(sid));
        } else setBusy(false);
      })
      .catch(() => {
        if (localSid) void perform(() => load(localSid));
        else setBusy(false);
      });
    // One restoration on mount; subsequent transitions are explicit user actions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if ((!current && !groupData) || result || (groupData && groupData.is_group_settled) || isPaused) return;
    const timer = window.setInterval(() => setElapsed(timerOrigin.current.base + performance.now() - timerOrigin.current.tick), 250);
    return () => window.clearInterval(timer);
  }, [current, groupData, result, isPaused]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const tag = target?.tagName?.toLowerCase();
      const isTextInput = tag === 'textarea' || (tag === 'input' && !['radio', 'checkbox'].includes((target as HTMLInputElement).type?.toLowerCase()));
      if (isTextInput) return;

      if (reviewIndex !== null && !groupData) {
        if (e.key === 'Escape' || e.key === 'Enter') {
          e.preventDefault();
          setReviewIndex(null);
        } else if (e.key === 'ArrowLeft') {
          e.preventDefault();
          setReviewIndex(i => (i === null ? null : Math.max(0, i - 1)));
        } else if (e.key === 'ArrowRight') {
          e.preventDefault();
          setReviewIndex(i => (i === null ? null : Math.min(history.length - 1, i + 1)));
        }
        return;
      }

      // 历史组回看中的按键：阻止误改当前组草稿或触发结算
      if (pastGroup) {
        if (e.key === 'Escape') {
          if (zoomImage) setZoomImage(null);
          else if (isPaused) togglePause(false);
          else {
            e.preventDefault();
            exitPastGroup();
          }
        } else if (['1', '2', '3', '4', '5'].includes(e.key)) {
          const idx = parseInt(e.key) - 1;
          if (idx < pastGroup.questions.length) {
            setReviewQIndex(idx);
          }
        } else if (e.key === 'ArrowLeft' && pastGroup.group_index > 1) {
          e.preventDefault();
          openPastGroup(pastGroup.group_index - 1);
        } else if (e.key === 'ArrowRight') {
          const pastMax = groupData ? (groupData.is_group_settled ? groupData.group_index : groupData.group_index - 1) : pastGroup.group_index;
          if (pastGroup.group_index < pastMax) {
            e.preventDefault();
            openPastGroup(pastGroup.group_index + 1);
          }
        }
        return;
      }

      if (e.key === 'p' || e.key === 'P') {
        if ((current || (groupData && !groupData.is_group_settled)) && !result) {
          e.preventDefault();
          togglePause();
        }
      } else if (e.code === 'Space') {
        if (isPaused) {
          e.preventDefault();
          togglePause(false);
        }
      } else if (e.key === 'Escape') {
        if (zoomImage) {
          setZoomImage(null);
        } else if (showUnansweredConfirm) {
          setShowUnansweredConfirm(false);
        } else if (isPaused) {
          togglePause(false);
        }
      } else if (current && !result && !groupData && !isPaused) {
        if (['a', 'b', 'c', 'd', 'A', 'B', 'C', 'D'].includes(e.key)) {
          const key = e.key.toUpperCase();
          if (current.question.options[key] !== undefined) {
            updateDraft({
              selected: key,
              confidence: draft.confidence,
              changed: draft.changed || (Boolean(draft.selected) && draft.selected !== key),
            });
          }
        } else if (['1', '2', '3'].includes(e.key)) {
          const confMap: Record<string, number> = { '1': 0.2, '2': 0.5, '3': 0.9 };
          const val = confMap[e.key];
          updateDraft({
            selected: draft.selected,
            confidence: draft.confidence === val ? null : val,
            changed: draft.changed,
          });
        } else if (e.key === 'Enter') {
          if (draft.selected) {
            submit();
          }
        }
      } else if (result && !groupData && !isPaused) {
        if (e.key === 'Enter') {
          if (session?.status !== 'completed') {
            nextQuestion();
          }
        }
      } else if (groupData && !groupData.is_group_settled && !isPaused) {
        if (['1', '2', '3', '4', '5'].includes(e.key)) {
          const idx = parseInt(e.key) - 1;
          if (idx < groupData.questions.length) {
            setActiveQIndex(idx);
          }
        } else if (['a', 'b', 'c', 'd', 'A', 'B', 'C', 'D'].includes(e.key)) {
          const activeQ = groupData.questions[activeQIndex];
          if (activeQ) {
            const key = e.key.toUpperCase();
            const curDraft = groupDrafts[activeQ.question_id] || { selected: '', confidence: null, changed: false };
            updateGroupDraft(activeQ.question_id, {
              selected: key,
              confidence: curDraft.confidence ?? null,
              changed: curDraft.changed || (Boolean(curDraft.selected) && curDraft.selected !== key),
            });
          }
        } else if (e.key === 'Enter') {
          const answeredCount = groupData.questions.filter(q => Boolean(groupDrafts[q.question_id]?.selected)).length;
          if (answeredCount === groupData.questions.length) {
            submitGroup(false);
          }
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [current, result, isPaused, zoomImage, groupData, pastGroup, activeQIndex, groupDrafts, showUnansweredConfirm, draft, session, reviewIndex, history]);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.hidden && (current || (groupData && !groupData.is_group_settled)) && !result && !isPaused) {
        togglePause(true);
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, [current, groupData, result, isPaused]);

  function updateDraft(next: Draft) {
    setDraft(next);
    if (current) write(`draft:${current.attempt_id}`, JSON.stringify(next));
  }

  function updateGroupDraft(qid: string, patch: Partial<Draft>) {
    setGroupDrafts(prev => {
      const existing = prev[qid] || { selected: '', confidence: null, changed: false };
      const nextDraft = { ...existing, ...patch };
      const next = { ...prev, [qid]: nextDraft };
      if (session) {
        write(`draft:${session.id}:${qid}`, JSON.stringify(nextDraft));
      }
      return next;
    });
  }

  async function submitGroup(force: boolean = false) {
    if (!session || !groupData) return;

    const unansweredIndices: number[] = [];
    groupData.questions.forEach((q, idx) => {
      const d = groupDrafts[q.question_id];
      if (!d || !d.selected) {
        unansweredIndices.push(idx + 1);
      }
    });

    if (!force && unansweredIndices.length > 0) {
      setShowUnansweredConfirm(true);
      return;
    }

    setShowUnansweredConfirm(false);
    if (errorRecorderRef.current) {
      try { await errorRecorderRef.current.flush(); } catch { /* ignore */ }
    }

    void perform(async () => {
      const answers = groupData.questions.map(q => {
        const d = groupDrafts[q.question_id] || { selected: '', confidence: null, changed: false };
        return {
          question_id: q.question_id,
          attempt_id: q.attempt_id,
          selected_answer: d.selected || null,
          confidence: d.confidence ?? null,
          changed_answer: d.changed,
        };
      });

      const totalPaused = Math.round(
        pausedMsRef.current + (isPaused && pauseStartRef.current > 0 ? performance.now() - pauseStartRef.current : 0)
      );

      await api<GroupSubmitResult>(`/quiz/${session.id}/group-answer`, {
        answers,
        total_elapsed_ms: Math.round(elapsed),
        paused_ms: totalPaused,
      });

      const refreshed = await api<QuizGroup>(`/quiz/${session.id}/group?group_idx=${groupData.group_index}`);
      setGroupData(refreshed);
      setPastGroup(null);
      setReviewQIndex(0);
      // 仅在全组判分提交完成的瞬时，若第一道题答错，标记为刚判分
      const firstQ = refreshed.questions[0];
      if (firstQ && firstQ.correct === false && firstQ.attempt_id) {
        setJustGradedAttemptId(firstQ.attempt_id);
      } else {
        setJustGradedAttemptId(null);
      }
      loadDailyGoal();
    });
  }

  async function loadNextGroup() {
    if (!session) return;
    if (errorRecorderRef.current) {
      try { await errorRecorderRef.current.flush(); } catch { /* ignore */ }
    }
    void perform(async () => {
      const nextGrp = await api<QuizGroup>(`/quiz/${session.id}/group`);
      if (nextGrp) {
        setGroupData(nextGrp);
        setPastGroup(null);
        setActiveQIndex(0);
        setReviewQIndex(0);
        for (const q of nextGrp.questions) {
          cacheQuestion(q.question);
        }
        const restored: Record<string, Draft> = {};
        for (const q of nextGrp.questions) {
          try {
            const saved = JSON.parse(read(`draft:${session.id}:${q.question_id}`) || 'null');
            if (saved && ['', 'A', 'B', 'C', 'D'].includes(saved.selected)) {
              restored[q.question_id] = saved;
            } else if (q.selected_answer) {
              restored[q.question_id] = { selected: q.selected_answer, confidence: q.confidence ?? null, changed: false };
            } else {
              restored[q.question_id] = { selected: '', confidence: null, changed: false };
            }
          } catch {
            restored[q.question_id] = { selected: '', confidence: null, changed: false };
          }
        }
        setGroupDrafts(restored);

        const base = Math.max(0, Date.parse(nextGrp.server_now) - Date.parse(nextGrp.started_at));
        timerOrigin.current = { base, tick: performance.now() };
        setElapsed(base);
        setIsPaused(false);
        pausedMsRef.current = 0;
        pauseStartRef.current = 0;
      }
    });
  }

  // 历史组回看：拉取指定已结算组的只读复盘视图。组内题目均已提交，端点不会再创建作答。
  function openPastGroup(groupIdx: number) {
    if (!session) return;
    void perform(async () => {
      const grp = await api<QuizGroup>(`/quiz/${session.id}/group?group_idx=${groupIdx}`);
      if (grp && grp.is_group_settled) {
        for (const q of grp.questions) cacheQuestion(q.question);
        setPastGroup(grp);
        setReviewQIndex(0);
      }
    });
  }

  function exitPastGroup() {
    setPastGroup(null);
    setReviewQIndex(0);
  }

  async function requestGroupDiagnosis(attId?: string | null) {
    if (!attId || aiWorking) return;
    setAiWorking(true); setAiStatus('AI 正在分析错因…');
    try {
      const res = await api<DiagnosisOutput>(`/attempts/${attId}/diagnose`, {});
      setDiagnosis(res);
      write(`diag:${attId}`, JSON.stringify(res));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '错因诊断生成失败');
    } finally { setAiWorking(false); setAiStatus(''); }
  }

  async function requestGroupExplanation(attId?: string | null) {
    if (!attId || aiWorking) return;
    setAiWorking(true); setAiStatus('正在生成分步讲解…');
    try {
      const res = await api<TutorExplanationOutput>(`/attempts/${attId}/explain`, {});
      setExplanation(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '深度解析生成失败');
    } finally { setAiWorking(false); setAiStatus(''); }
  }

  function start(targetSize?: number, targetModule?: string) { void perform(async () => {
    if (errorRecorderRef.current) {
      try { await errorRecorderRef.current.flush(); } catch { /* ignore */ }
    }
    const finalSize = targetSize || selectedSize || 20;
    const activeModule = targetModule !== undefined ? targetModule : selectedModule;
    const payload: { size: number; module?: string } = { size: finalSize };
    if (activeModule && activeModule !== 'ALL') {
      payload.module = activeModule;
    }
    const created = await api<{ id: string }>('/quiz/session', payload);
    write(SESSION_KEY, created.id);
    window.history.replaceState(null, '', `/quiz?session=${encodeURIComponent(created.id)}`);
    await load(created.id);
    setShowTrainingSetup(false);
    loadDailyGoal();
  }); }

  function startAdaptive() { void perform(async () => {
    if (errorRecorderRef.current) {
      try { await errorRecorderRef.current.flush(); } catch { /* ignore */ }
    }
    const created = await api<{ id: string; policy_version: string }>('/practice/adaptive/session', { limit: 10 });
    write(SESSION_KEY, created.id);
    window.history.replaceState(null, '', `/quiz?session=${encodeURIComponent(created.id)}`);
    await load(created.id);
  }); }

  function nextQuestion() { void perform(async () => {
    if (!session) return;
    setJustGradedAttemptId(null);
    if (errorRecorderRef.current) {
      try { await errorRecorderRef.current.flush(); } catch { /* ignore */ }
    }
    const value = await api<Current | { done: true }>(`/quiz/${session.id}/next`);
    if (!value.done) present(value); else await load(session.id);
  }); }

  function submit() { if (!session || !current) return;
    void perform(async () => {
      const currentSnapshot = current;
      cacheQuestion(currentSnapshot.question);
      const totalPaused = Math.round(pausedMsRef.current + (isPaused && pauseStartRef.current > 0 ? performance.now() - pauseStartRef.current : 0));
      const saved = await api<Result>(`/quiz/${session.id}/answer`, {
        attempt_id: current.attempt_id,
        // 允许不选任何答案直接提交（未作答/不会）；选项与信心均可留空，绝不伪造选项。
        selected_answer: draft.selected || null,
        confidence: draft.confidence,
        changed_answer: draft.changed,
        paused_ms: totalPaused,
      });
      setResult({
        ...saved,
        stem: saved.stem || currentSnapshot.question.stem,
        options: saved.options || currentSnapshot.question.options,
        stem_assets: (saved.stem_assets && saved.stem_assets.length > 0) ? saved.stem_assets : currentSnapshot.question.stem_assets,
        module: saved.module || currentSnapshot.question.module,
      });
      setHistory(prev => [...prev.filter(r => r.id !== saved.id), {
        ...saved,
        stem: saved.stem || currentSnapshot.question.stem,
        options: saved.options || currentSnapshot.question.options,
        stem_assets: (saved.stem_assets && saved.stem_assets.length > 0) ? saved.stem_assets : currentSnapshot.question.stem_assets,
        module: saved.module || currentSnapshot.question.module,
        position: saved.selection?.position,
      }].sort((a, b) => (a.position ?? Number.MAX_SAFE_INTEGER) - (b.position ?? Number.MAX_SAFE_INTEGER)));
      // 记录本次刚判分的 attemptId，仅在做错时供自动追问消费
      if (!saved.correct) {
        setJustGradedAttemptId(saved.id);
      } else {
        setJustGradedAttemptId(null);
      }
      setCurrent(null);
      await load(session.id);
      loadDailyGoal();
    });
  }

  async function requestHint() {
    if (!session || !current || aiWorking) return;
    const nextLevel = Math.min(4, (hint?.hint_level || 0) + 1);
    setAiWorking(true); setAiStatus('正在生成提示…');
    try {
      const res = await api<HintOutput>(`/quiz/${session.id}/hint`, {
        attempt_id: current.attempt_id,
        requested_level: nextLevel,
      });
      setHint(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '获取提示失败');
    } finally { setAiWorking(false); setAiStatus(''); }
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


  const currentActiveModuleName =
    (modulesData.find(m => m.id === selectedModule)?.name || (selectedModule === 'ALL' ? '全部模块' : selectedModule));

  // 整组布局统一渲染 displayGroup：回看历史组时切换为历史组数据，作答时即当前组。
  const displayGroup = pastGroup ?? groupData;
  const isPastGroupView = pastGroup !== null;
  // 回看时最多能翻到的组：当前组已结算则含当前组，否则只到当前组的前一组。
  const pastViewMaxIdx = groupData
    ? (groupData.is_group_settled ? groupData.group_index : groupData.group_index - 1)
    : 0;

  const viewResult = reviewIndex !== null ? (history[reviewIndex] ?? null) : result;
  const viewUnanswered = !!viewResult && !viewResult.correct && !viewResult.selected_answer;
  const reviewPos =
    reviewIndex !== null
      ? (typeof history[reviewIndex]?.position === 'number'
          ? history[reviewIndex].position! + 1
          : reviewIndex + 1)
      : null;

  return <main>
    <header>
      <Link href="/dashboard" className="brand"><span className="brand-icon">学</span>公考 Learning OS</Link>
      <nav>
        <Link href="/dashboard">学习概览</Link>
        <Link href="/framework">知识框架</Link>
        <Link href="/quiz" className="active">行测训练</Link>
        <Link href="/question-sources">按原书找题</Link>
        <Link href="/review">到期复习</Link>
        <Link href="/notes">我的笔记</Link>
        <Link href="/exam">全真模考</Link>
        <Link href="/shenlun">申论工作台</Link>
        <Link href="/importer">题库导入</Link>
      <Link href="/settings">设置</Link></nav>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <button
          type="button"
          onClick={() => setShowSyncModal(true)}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            padding: '5px 11px',
            fontSize: 12,
            fontWeight: 600,
            background: '#edf5ef',
            border: '1px solid #c4d8c7',
            color: '#296044',
            borderRadius: 8,
            cursor: 'pointer',
          }}
          title="手机/平板扫码同步刷题"
        >
          <span>📱</span>
          <span>手机/平板刷题</span>
        </button>
        <span className="local">● 本地学习空间</span>
      </div>
    </header>
    <div className="intro"><span className="eyebrow">PRACTICE / 行测</span><h1>每一次作答，都是进步的起点。</h1><p>先独立思考，再记录判断。让学习留下真实的证据。</p></div>
    <div className={`workspace ${result || groupData ? 'review-mode' : ''}`} style={{ gridTemplateColumns: '1fr' }}><section className="card" aria-label="行测训练" style={groupData ? { padding: '16px 18px', background: 'transparent', border: 'none', boxShadow: 'none' } : undefined}>
      <div className="card-top">
        <span style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span>{groupData ? '资料分析 · 五题整组专项训练' : '单选题训练'}</span>
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
        <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {session ? `已完成 ${session.answered} / ${session.total}` : (bankTotal ? `题库共 ${bankTotal.toLocaleString()} 题 · 准备开始` : '准备开始')}
          {session && (
            <button
              type="button"
              disabled={busy}
              onClick={() => setShowTrainingSetup(value => !value)}
              style={{
                padding: '2px 8px',
                fontSize: 11,
                border: '1px solid var(--line)',
                borderRadius: 4,
                background: 'none',
                color: 'var(--muted)',
                cursor: 'pointer'
              }}
              title="开启新的全库或专项训练"
            >
              {showTrainingSetup ? '返回当前训练' : '选择模块 / 新训练'}
            </button>
          )}
        </span>
      </div>
      {session && !groupData && history.length > 0 && (
        <QuizAnswerSheet
          total={session.total}
          history={history}
          reviewIndex={reviewIndex}
          busy={busy}
          onSelectReview={setReviewIndex}
          onReturnCurrent={() => setReviewIndex(null)}
        />
      )}
      {error && <div role="alert" className="error">{error}{session && <button disabled={busy} onClick={() => void perform(() => load(session.id))}>重新同步</button>}</div>}
      {busy && !current && !result && <p role="status">正在载入训练…</p>}
      {(!session || showTrainingSetup) && !busy && <div className="welcome" role="region" aria-label="训练设置">
        {(!session || showTrainingSetup) && <>
        <h2>给自己一段专注的时间</h2>
        <p>分模块专项突破或自由全真练习。记录信心，再查看结果，无固定配比约束。</p>
        {session && <p>选择模块后点击“开始训练”开启新一轮；已提交作答保留，未提交的答案请先完成当前训练。</p>}

        {dailyGoal && (
          <div style={{ margin: '14px 0', padding: '12px 18px', background: '#f8fafc', border: '1px solid #cbd5e1', borderRadius: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, textAlign: 'left' }}>
            <div>
              <span style={{ fontSize: 13, color: '#334155', fontWeight: 700 }}>🎯 每日 500 题冲刺目标：</span>
              <span style={{ fontSize: 13, color: 'var(--accent)', fontWeight: 700, marginLeft: 4 }}>
                今日已完成 {dailyGoal.completed} / 500 题 ({dailyGoal.progress_percent}%)
              </span>
              <small style={{ display: 'block', color: 'var(--muted)', fontSize: 11, marginTop: 2 }}>
                日常训练 {dailyGoal.practice_count} 题 + 到期复习 {dailyGoal.review_count} 题
              </small>
            </div>
            <span style={{ fontSize: 11, color: '#475569', background: '#e2e8f0', padding: '2px 8px', borderRadius: 10, fontWeight: 600 }}>
              {dailyGoal.remaining > 0 ? `还差 ${dailyGoal.remaining} 题` : '🎉 今日已达标'}
            </span>
          </div>
        )}

        </>}
        {/* 分类与知识地图共用知识树，训练过程中始终可见。 */}
        <div style={{ margin: '16px 0', textAlign: 'left' }}>
          <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', display: 'block', marginBottom: 8 }}>
            选择训练模块（按知识地图分类）：
          </label>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {(modulesData.length > 0
              ? modulesData
              : [
                  { id: 'ALL', name: '全部模块', total: bankTotal || 0, unpracticed: 0 },
                  { id: '图形推理', name: '图形推理', total: 0, unpracticed: 0 },
                  { id: '立体图推', name: '立体图推', total: 0, unpracticed: 0 },
                  { id: '定义判断', name: '定义判断', total: 0, unpracticed: 0 },
                  { id: '类比推理', name: '类比推理', total: 0, unpracticed: 0 },
                  { id: '逻辑判断', name: '逻辑判断', total: 0, unpracticed: 0 },
                  { id: '言语理解', name: '言语理解与表达', total: 0, unpracticed: 0 },
                  { id: '资料分析', name: '资料分析', total: 0, unpracticed: 0 },
                  { id: '数量关系', name: '数量关系', total: 0, unpracticed: 0 },
                  { id: '政治理论', name: '政治理论', total: 0, unpracticed: 0 },
                  { id: '常识判断', name: '常识判断', total: 0, unpracticed: 0 },
                ]
            ).map(mod => {
              const isSelected = selectedModule === mod.id;
              return (
                <button
                  key={mod.id}
                  type="button"
                  className={isSelected ? 'primary' : 'secondary'}
                  onClick={() => {
                    if (session) setShowTrainingSetup(true);
                    setSelectedModule(mod.id);
                    if (mod.id === '资料分析') {
                      setSelectedSize(20);
                    } else if (selectedSize === 5 || selectedSize === 40) {
                      setSelectedSize(20);
                    }
                  }}
                  style={{
                    padding: '6px 12px',
                    fontSize: 12,
                    borderRadius: 6,
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6
                  }}
                >
                  <span>{mod.name}</span>
                  {mod.total > 0 && (
                    <span style={{
                      fontSize: 10,
                      opacity: isSelected ? 0.9 : 0.7,
                      background: isSelected ? 'rgba(255,255,255,0.25)' : '#e2e8f0',
                      padding: '1px 5px',
                      borderRadius: 8
                    }}>
                      {mod.total}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

        </div>

        {/* 2. 题量选择 */}
        {(!session || showTrainingSetup) && <>
        <div style={{ margin: '16px 0', textAlign: 'left' }}>
          <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', display: 'block', marginBottom: 8 }}>
            选择本轮刷题题量：
          </label>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {(selectedModule === '资料分析'
              ? [
                  { size: 5, label: '⚡ 1篇精练 (5 题)' },
                  { size: 10, label: '🎯 2篇强化 (10 题)' },
                  { size: 20, label: '🚀 4篇真题套卷 (20 题)' },
                  { size: 40, label: '🔥 8篇冲刺 (40 题)' },
                  { size: 50, label: '📋 10篇深度突破 (50 题)' },
                ]
              : [
                  { size: 10, label: '⚡ 快速热身 (10 题)' },
                  { size: 20, label: '🎯 专项精练 (20 题)' },
                  { size: 50, label: '🚀 标准强化 (50 题)' },
                  { size: 100, label: '🔥 深度突破 (100 题)' },
                  { size: 200, label: '📋 海量刷题 (200 题)' },
                ]
            ).map(item => (
              <button
                key={item.size}
                type="button"
                className={selectedSize === item.size ? 'primary' : 'secondary'}
                onClick={() => setSelectedSize(item.size)}
                style={{ padding: '6px 12px', fontSize: 12, borderRadius: 6 }}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="start-actions" style={{ marginTop: 16 }}>
          <button className="primary" aria-label="开始训练" onClick={() => start(selectedSize)}>
            开始【{currentActiveModuleName}】训练 ({selectedSize} 题)
          </button>
          <button className="secondary" style={{ marginLeft: 8 }} onClick={startAdaptive}>自适应专项 (10 题)</button>
        </div>
        <details className="muted" style={{ marginTop: 12 }}>
          <summary style={{ cursor: 'pointer' }}>模式说明</summary>
          <p style={{ margin: '6px 0 0' }}>自由分模块刷题：选定模块后只出该模块的题目，优先安排没练过的题，不做模考配比。</p>
        </details>
        </>}
      </div>}

      {displayGroup ? (
        <div className="data-analysis-layout" style={{ position: 'relative' }}>
          {/* 暂停遮罩 */}
          {isPaused && (
            <div style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: 'rgba(255, 255, 255, 0.92)',
              backdropFilter: 'blur(10px)',
              zIndex: 50,
              borderRadius: 14,
              padding: 24,
              textAlign: 'center',
            }}>
              <div style={{ fontSize: 48, marginBottom: 12 }}>⏸️</div>
              <h3 style={{ fontSize: 22, fontWeight: 700, margin: '0 0 8px', color: '#1e293b' }}>训练已暂停</h3>
              <p style={{ color: '#64748b', fontSize: 14, maxWidth: 380, margin: '0 0 16px', lineHeight: 1.6 }}>
                计时已冻结，材料与题面已安全遮挡。<br />准备好后按空格或 P 键继续。
              </p>
              <button type="button" className="primary" onClick={() => togglePause(false)} style={{ padding: '10px 26px', fontSize: 15 }}>
                ▶ 继续作答 (空格 / P)
              </button>
            </div>
          )}

          {/* 左栏：资料背景材料区（固定高、独立滚动、高清可放大缩放） */}
          <div className="da-passage-panel" style={{ filter: isPaused ? 'blur(14px)' : 'none', pointerEvents: isPaused ? 'none' : 'auto' }}>
            <div className="da-passage-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 12, background: '#e2e8f0', color: '#1e293b', padding: '3px 8px', borderRadius: 6, fontWeight: 700 }}>
                  📑 资料背景材料
                </span>
                <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 500 }}>
                  第 {displayGroup.group_index} / {displayGroup.total_groups} 组 · 本组共 {displayGroup.questions.length} 题
                </span>
              </div>
              <div className="da-zoom-toolbar">
                <button type="button" className="da-zoom-btn" onClick={() => setPassageZoom(z => Math.max(60, z - 15))} title="缩小材料图">
                  🔍- 缩小
                </button>
                <button type="button" className="da-zoom-btn" onClick={() => setPassageZoom(100)} title="恢复100%大小">
                  {passageZoom}%
                </button>
                <button type="button" className="da-zoom-btn" onClick={() => setPassageZoom(z => Math.min(250, z + 15))} title="放大材料图">
                  🔍+ 放大
                </button>
                <button type="button" className="da-zoom-btn" onClick={() => setPassageZoom(150)} title="1.5倍特大字号">
                  1.5x
                </button>
                {displayGroup.passage?.assets?.[0] && (
                  <button
                    type="button"
                    className="da-zoom-btn"
                    onClick={() => setZoomImage(displayGroup.passage!.assets![0])}
                    style={{ color: '#296044', borderColor: '#c4d8c7', background: '#edf5ef' }}
                    title="全屏高清无遮挡查看"
                  >
                    ⛶ 全屏
                  </button>
                )}
              </div>
            </div>

            {displayGroup.passage?.content && (
              <div className="da-passage-text">
                {displayGroup.passage.content}
              </div>
            )}

            {displayGroup.passage?.assets && displayGroup.passage.assets.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {displayGroup.passage.assets.map((asset, aIdx) => (
                  <div key={aIdx} className="da-passage-image-wrapper">
                    <img
                      src={asset}
                      alt={`材料配图 ${aIdx + 1}`}
                      className="da-passage-img"
                      style={{ width: `${passageZoom}%`, maxWidth: passageZoom <= 100 ? '100%' : 'none' }}
                      onClick={() => setZoomImage(asset)}
                      title="点击全屏高清放大"
                    />
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 右栏：小题作答区 或 五题结算复盘区 */}
          <div className="da-questions-panel" style={{ filter: isPaused ? 'blur(14px)' : 'none', pointerEvents: isPaused ? 'none' : 'auto' }}>
            {displayGroup.is_group_settled ? (
              /* ===== 五题合并结算与复盘看板（含历史组回看） ===== */
              <div>
                {/* 结算成绩看板 */}
                <div className="da-settle-banner" style={{ marginBottom: 18 }}>
                  <div>
                    <span className="pill" style={{
                      background: isPastGroupView
                        ? '#e2e8f0'
                        : (displayGroup.summary?.is_all_correct ? '#edf5ef' : '#fef2f2'),
                      color: isPastGroupView
                        ? '#1e293b'
                        : (displayGroup.summary?.is_all_correct ? 'var(--accent)' : '#b91c1c'),
                      fontWeight: 700,
                      fontSize: 12
                    }}>
                      {isPastGroupView
                        ? '📋 历史组回看'
                        : (displayGroup.summary?.is_all_correct ? '🎉 本组 5 题全部正确！' : '📝 本组 5 题作答结算')}
                    </span>
                    <h2 style={{ margin: '8px 0 4px', fontSize: 22, color: '#0f172a' }}>
                      {isPastGroupView && `第 ${displayGroup.group_index} / ${displayGroup.total_groups} 组 · `}
                      本组答对 {displayGroup.summary?.correct_count} / {displayGroup.summary?.total} 题 · 正确率 {displayGroup.summary?.accuracy_percent}%
                    </h2>
                    <small style={{ color: 'var(--muted)', fontSize: 12 }}>
                      第 {displayGroup.group_index} / {displayGroup.total_groups} 组材料 · 本组总用时 {format(displayGroup.summary?.total_elapsed_ms || 0)} (题均 {Math.round((displayGroup.summary?.avg_elapsed_ms || 0) / 1000)} 秒)
                    </small>
                  </div>
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                    {isPastGroupView ? (
                      <>
                        <button
                          type="button"
                          className="secondary"
                          disabled={busy || displayGroup.group_index <= 1}
                          onClick={() => openPastGroup(displayGroup.group_index - 1)}
                          style={{ padding: '8px 14px', fontSize: 13 }}
                          title="回看更早的已答组"
                        >
                          ◀ 上一组
                        </button>
                        <button
                          type="button"
                          className="secondary"
                          disabled={busy || displayGroup.group_index >= pastViewMaxIdx}
                          onClick={() => openPastGroup(displayGroup.group_index + 1)}
                          style={{ padding: '8px 14px', fontSize: 13 }}
                          title="回看更晚的已答组"
                        >
                          下一组 ▶
                        </button>
                        <button type="button" className="primary" onClick={exitPastGroup} style={{ padding: '8px 18px', fontSize: 13 }}>
                          返回当前作答 ➔
                        </button>
                      </>
                    ) : (
                      <>
                        {displayGroup.group_index > 1 && (
                          <button
                            type="button"
                            className="secondary"
                            disabled={busy}
                            onClick={() => openPastGroup(displayGroup.group_index - 1)}
                            style={{ padding: '8px 14px', fontSize: 13 }}
                            title="回看前面已结算组的材料、作答与解析"
                          >
                            📋 回看上一组
                          </button>
                        )}
                        {displayGroup.has_next_group ? (
                          <button type="button" className="primary" onClick={loadNextGroup} style={{ padding: '8px 18px', fontSize: 13 }}>
                            进入下一组材料 (5题) ➔
                          </button>
                        ) : (
                          <Link href="/dashboard" className="primary-link" style={{ padding: '8px 18px', fontSize: 13 }}>
                            完成全部训练 ➔
                          </Link>
                        )}
                      </>
                    )}
                  </div>
                </div>

                {/* 五题切换 Pills */}
                <div className="da-nav-pills" style={{ marginBottom: 16 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#475569', marginRight: 4 }}>
                    小题复盘：
                  </span>
                  {displayGroup.questions.map((q, idx) => {
                    const isCorrect = q.correct === true;
                    const isFocused = reviewQIndex === idx;
                    return (
                      <button
                        key={q.question_id}
                        type="button"
                        className={`da-nav-pill ${isFocused ? 'active' : ''} ${isCorrect ? 'correct' : 'incorrect'}`}
                        onClick={() => setReviewQIndex(idx)}
                      >
                        <span>第 {idx + 1} 题</span>
                        <span className="da-sub-badge" style={{
                          background: isCorrect ? '#dcfce7' : '#fee2e2',
                          color: isCorrect ? '#166534' : '#991b1b'
                        }}>
                          {isCorrect ? '✓' : '✗'} {q.selected_answer || '未答'}
                        </span>
                      </button>
                    );
                  })}
                </div>

                {/* 当前选中小题复盘详情 */}
                {(() => {
                  const focusedQ = displayGroup.questions[reviewQIndex];
                  if (!focusedQ) return null;
                  const isCorrect = focusedQ.correct === true;

                  return (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                      {/* 题头指标对比 */}
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#f8fafc', padding: '10px 16px', borderRadius: 8, border: '1px solid #e2e8f0', flexWrap: 'wrap', gap: 10 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                          <span style={{ fontSize: 13, fontWeight: 700, color: isCorrect ? 'var(--accent)' : '#b91c1c' }}>
                            {isCorrect ? '✓ 回答正确' : '✗ 回答错误'}
                          </span>
                          <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                            你的答案：<strong style={{ color: isCorrect ? 'var(--accent)' : '#b91c1c', fontSize: 14 }}>{focusedQ.selected_answer || '未作答'}</strong>
                          </span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12, color: 'var(--muted)' }}>
                          <span>本题用时：<strong><RecordedTime elapsedMs={focusedQ.elapsed_ms || 0} timingValid={focusedQ.timing_valid} /></strong></span>
                          <span>信心度：<strong>{confidenceLabel(focusedQ.confidence ?? null)}</strong></span>
                        </div>
                      </div>

                      {/* 题干 */}
                      <h3 className="da-stem" style={{ margin: '4px 0 8px' }}>
                        <FormattedStem text={focusedQ.question?.stem || focusedQ.stem || ''} />
                      </h3>

                      {/* 题图配图 */}
                      {Boolean((focusedQ.question?.stem_assets && focusedQ.question.stem_assets.length > 0) || (focusedQ.stem_assets && focusedQ.stem_assets.length > 0)) && (
                        <div className="da-stem-assets">
                          {(focusedQ.question?.stem_assets || focusedQ.stem_assets || []).map((asset, aIdx) => (
                            <img
                              key={aIdx}
                              src={asset}
                              alt="题图"
                              onClick={() => setZoomImage(asset)}
                              title="点击全屏高清放大"
                            />
                          ))}
                        </div>
                      )}

                      {/* 选项对比列表 */}
                      <div style={{ display: 'grid', gap: 8 }}>
                        {Object.entries(focusedQ.question?.options || focusedQ.options || {}).map(([k, v]) => {
                          const isUserPick = focusedQ.selected_answer === k;
                          const isStdAns = isUserPick && focusedQ.correct === true;

                          let bg = '#ffffff';
                          let border = '#e2e8f0';
                          let badge = null;

                          if (isStdAns) {
                            bg = '#f0fdf4';
                            border = '#22c55e';
                            badge = <span style={{ marginLeft: 'auto', fontSize: 11, background: '#22c55e', color: '#fff', padding: '2px 8px', borderRadius: 4, fontWeight: 700 }}>✓ 你的作答（正确）</span>;
                          } else if (isUserPick) {
                            bg = '#fef2f2';
                            border = '#ef4444';
                            badge = <span style={{ marginLeft: 'auto', fontSize: 11, background: '#ef4444', color: '#fff', padding: '2px 8px', borderRadius: 4, fontWeight: 700 }}>你的作答</span>;
                          }

                          return (
                            <div
                              key={k}
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 12,
                                padding: '10px 14px',
                                borderRadius: 8,
                                border: `1.5px solid ${border}`,
                                background: bg,
                                fontSize: 14,
                                lineHeight: 1.5,
                              }}
                            >
                              <strong style={{ minWidth: 20 }}>{k}.</strong>
                              <span>{v === k || !v ? k : v}</span>
                              {badge}
                            </div>
                          );
                        })}
                      </div>

                      {/* 本题复盘（AI追问、分步精讲、错因选择与自由对话统一面板） */}
                      {focusedQ.attempt_id && (
                        <InteractiveReviewCard
                          key={focusedQ.attempt_id}
                          attemptId={focusedQ.attempt_id}
                          isCorrect={isCorrect}
                          confidence={focusedQ.confidence ?? null}
                          stem={focusedQ.question.stem}
                          module={focusedQ.question.module}
                          justGraded={justGradedAttemptId === focusedQ.attempt_id}
                        />
                      )}

                      {/* 小题复盘切换按钮（切换小题时严格清除刚判分标记，绝不重复触发自动追问） */}
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12, paddingTop: 14, borderTop: '1px solid var(--line)' }}>
                        <button
                          type="button"
                          className="secondary"
                          disabled={reviewQIndex === 0}
                          onClick={() => {
                            setJustGradedAttemptId(null);
                            setReviewQIndex(i => i - 1);
                          }}
                          style={{ fontSize: 13 }}
                        >
                          ◀ 上一题解析
                        </button>
                        <button
                          type="button"
                          className="secondary"
                          disabled={reviewQIndex === displayGroup.questions.length - 1}
                          onClick={() => {
                            setJustGradedAttemptId(null);
                            setReviewQIndex(i => i + 1);
                          }}
                          style={{ fontSize: 13 }}
                        >
                          下一题解析 ▶
                        </button>
                      </div>
                    </div>
                  );
                })()}
              </div>
            ) : (
              /* ===== 五题一组作答区 ===== */
              <div>
                {/* 作答顶部状态条 */}
                <div className="da-group-topbar">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <span className="pill" style={{ fontWeight: 700 }}>
                      材料第 {displayGroup.group_index} / {displayGroup.total_groups} 组小题作答
                    </span>
                    <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                      ⏱️ 已用时 <strong data-testid="timer" style={{ color: '#0f172a', fontSize: 15 }}>{format(elapsed)}</strong>
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    {displayGroup.group_index > 1 && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => openPastGroup(displayGroup.group_index - 1)}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 5,
                          padding: '4px 10px',
                          fontSize: 12,
                          fontWeight: 600,
                          borderRadius: 6,
                          border: '1px solid var(--border)',
                          background: '#f8fafc',
                          color: '#475569',
                          cursor: busy ? 'default' : 'pointer',
                        }}
                        title="回看前面已结算组的材料、作答与解析"
                      >
                        📋 回看已答组
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => togglePause()}
                    style={{
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
                    }}
                    title="按 P 键或空格键暂停/恢复"
                  >
                    {isPaused ? '▶ 继续作答 (P)' : '⏸ 暂停 (P)'}
                  </button>
                  </div>
                </div>

                {/* 五题切换 Pills */}
                <div className="da-nav-pills" style={{ margin: '14px 0' }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#475569', marginRight: 4 }}>
                    小题导航：
                  </span>
                  {displayGroup.questions.map((q, idx) => {
                    const d = groupDrafts[q.question_id];
                    const isAnswered = Boolean(d && d.selected);
                    const isActive = activeQIndex === idx;

                    return (
                      <button
                        key={q.question_id}
                        type="button"
                        className={`da-nav-pill ${isActive ? 'active' : ''} ${isAnswered ? 'answered' : ''}`}
                        onClick={() => setActiveQIndex(idx)}
                        title={`第 ${idx + 1} 题 (快捷键 ${idx + 1})`}
                      >
                        <span>第 {idx + 1} 题</span>
                        {isAnswered && <span className="da-sub-badge">{d.selected}</span>}
                      </button>
                    );
                  })}
                  <span style={{ marginLeft: 'auto', fontSize: 11.5, color: 'var(--muted)', fontWeight: 600 }}>
                    已作答 {displayGroup.questions.filter(q => Boolean(groupDrafts[q.question_id]?.selected)).length} / {displayGroup.questions.length} 题
                  </span>
                </div>

                {/* 当前选中小题作答卡片 */}
                {(() => {
                  const activeQ = displayGroup.questions[activeQIndex];
                  if (!activeQ) return null;
                  const activeDraft = groupDrafts[activeQ.question_id] || { selected: '', confidence: null, changed: false };

                  return (
                    <div key={activeQ.question_id}>
                      {/* 题干 */}
                      <h2 className="da-stem">
                        <FormattedStem text={activeQ.question.stem} />
                      </h2>

                      {/* 题图配图 */}
                      {activeQ.question.stem_assets && activeQ.question.stem_assets.length > 0 && (
                        <div className="da-stem-assets">
                          {activeQ.question.stem_assets.map((asset, idx) => (
                            <img
                              key={idx}
                              src={asset}
                              alt={`题面图 ${idx + 1}`}
                              onClick={() => setZoomImage(asset)}
                              title="点击全屏高清放大"
                            />
                          ))}
                        </div>
                      )}

                      {/* 选项列表 */}
                      <div className={`da-options ${getOptionsGridClass(activeQ.question.options)}`}>
                        {Object.entries(activeQ.question.options).map(([key, value]) => {
                          const isSelected = activeDraft.selected === key;
                          return (
                            <label
                              key={key}
                              className={`da-option-label ${isSelected ? 'selected' : ''}`}
                              onClick={() => {
                                updateGroupDraft(activeQ.question_id, {
                                  selected: key,
                                  changed: activeDraft.changed || (Boolean(activeDraft.selected) && activeDraft.selected !== key),
                                });
                              }}
                            >
                              <input
                                type="radio"
                                name={`da-opt-${activeQ.question_id}`}
                                value={key}
                                checked={isSelected}
                                onChange={() => {}}
                              />
                              <span>{value === key || !value ? key : `${key}. ${value}`}</span>
                            </label>
                          );
                        })}
                      </div>

                      {/* 作答把握度 */}
                      <fieldset disabled={busy} className="confidence" style={{ marginTop: 20 }}>
                        <legend>你有多大把握？<span>可选 · 键盘 1-3 快速选择，再次点击可取消</span></legend>
                        <div>
                          {CONFIDENCE_TIERS.map(tier => (
                            <label
                              key={tier.value}
                              className={activeDraft.confidence === tier.value ? 'selected' : ''}
                            >
                              <input
                                type="radio"
                                name={`da-conf-${activeQ.question_id}`}
                                value={tier.value}
                                checked={activeDraft.confidence === tier.value}
                                onClick={() => {
                                  if (activeDraft.confidence === tier.value) {
                                    updateGroupDraft(activeQ.question_id, { confidence: null });
                                  }
                                }}
                                onChange={() => {
                                  updateGroupDraft(activeQ.question_id, { confidence: tier.value });
                                }}
                              />
                              {tier.label}
                            </label>
                          ))}
                        </div>
                        <p>纯蒙题＝基本在猜 · 半猜＝有思路没把握 · 有信心＝基本确定；不选则不记录信心。</p>
                      </fieldset>

                      {/* 底部导航与结算操作 */}
                      <div className="da-group-actions">
                        <div style={{ display: 'flex', gap: 8 }}>
                          <button
                            type="button"
                            className="secondary"
                            disabled={activeQIndex === 0}
                            onClick={() => setActiveQIndex(i => i - 1)}
                          >
                            ◀ 上一题
                          </button>
                          {activeQIndex < displayGroup.questions.length - 1 && (
                            <button
                              type="button"
                              className="secondary"
                              onClick={() => setActiveQIndex(i => i + 1)}
                            >
                              下一题 ▶
                            </button>
                          )}
                        </div>
                        <button
                          type="button"
                          className="primary"
                          disabled={busy}
                          onClick={() => submitGroup(false)}
                          style={{ padding: '11px 22px', fontSize: 14 }}
                        >
                          {busy ? '正在保存结算…' : `✨ 结算本组作答 (${displayGroup.questions.filter(q => Boolean(groupDrafts[q.question_id]?.selected)).length}/${displayGroup.questions.length}题)`}
                        </button>
                      </div>
                    </div>
                  );
                })()}
              </div>
            )}
          </div>
        </div>
      ) : (
        <>
          {current && reviewIndex === null && <>
        <div className="question-meta">
          <span className="pill">{SECTION_NAMES[current.question.module] || current.question.module}</span>
          {current.selection && <span className="pill" title={`得分: ${current.selection.selection_score}`}>🎯 自适应：{current.selection.selection_reason}</span>}
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
            <fieldset disabled={busy} className={`options ${getOptionsGridClass(current.question.options)}`}><legend className="sr-only">选择一个答案</legend>{Object.entries(current.question.options).map(([key, value]) => <label key={key} className={draft.selected === key ? 'option selected' : 'option'}><input type="radio" name="answer" value={key} checked={draft.selected === key} onChange={() => updateDraft({ ...draft, selected: key, changed: draft.changed || (!!draft.selected && draft.selected !== key) })} /><span>{value === key || !value ? key : `${key}. ${value}`}</span></label>)}</fieldset>
            <fieldset disabled={busy} className="confidence"><legend>你有多大把握？<span>可选 · 键盘 1-3 快速选择，再次点击可取消</span></legend><div>{CONFIDENCE_TIERS.map(tier => <label key={tier.value} className={draft.confidence === tier.value ? 'selected' : ''}><input type="radio" name="confidence" value={tier.value} checked={draft.confidence === tier.value} onClick={() => { if (draft.confidence === tier.value) { updateDraft({ ...draft, confidence: null }); } }} onChange={() => { updateDraft({ ...draft, confidence: tier.value }); }} />{tier.label}</label>)}</div><p>纯蒙题＝基本在猜 · 半猜＝有思路没把握 · 有信心＝基本确定；不选则不记录信心。</p></fieldset>
            {hint && <div className="hint-card" style={{ margin: '18px 0', padding: 16, background: '#f6f9f6', border: '1px solid #d2e4d6', borderRadius: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 4 }}>
                <strong style={{ color: 'var(--accent)' }}>💡 提示</strong>
                {hint.citation
                  ? <small style={{ color: 'var(--muted)' }}>参考：{hint.citation}</small>
                  : <small style={{ color: '#b58900' }}>本次未引用教材资料</small>}
              </div>
              {hint.direction && <p style={{ margin: '8px 0', fontSize: 13 }}><b>方向提示：</b>{hint.direction}</p>}
              {hint.method && <p style={{ margin: '8px 0', fontSize: 13 }}><b>适用方法：</b>{hint.method}</p>}
              {hint.partial_step && <p style={{ margin: '8px 0', fontSize: 13 }}><b>部分步骤：</b>{hint.partial_step}</p>}
              {hint.full_explanation && <p style={{ margin: '8px 0', fontSize: 13 }}><b>完整推导：</b>{hint.full_explanation}</p>}
              <small style={{ color: '#888', display: 'block', marginTop: 6 }}>本次使用了提示，已如实记录。</small>
              <details style={{ marginTop: 4, fontSize: 12, color: '#888' }}>
                <summary style={{ cursor: 'pointer' }}>使用提示会影响掌握度吗？</summary>
                <p style={{ margin: '4px 0 0', lineHeight: 1.6 }}>会。使用提示后答对，这条作答在掌握度评估中的分量会降低：第 1 层提示按 65% 计，第 3 层按 25% 计。记录和计算都自动完成，不需要你操作。</p>
              </details>
            </div>}
            <div className="submit-row"><span className="muted">{current.question.source}</span><div style={{ display: 'flex', gap: 8 }}>{!draft.selected && <button type="button" className="secondary" disabled={busy} title="按“未作答/不会”记录本题并结束作答，直接进入解析，不影响先获取提示" onClick={submit}>不会，直接提交</button>}<button type="button" className="secondary" disabled={busy || aiWorking || (hint?.hint_level || 0) >= 4} title={(hint?.hint_level || 0) >= 4 ? '已经是最详细的提示了' : undefined} onClick={requestHint}>💡 {(hint?.hint_level || 0) === 0 ? '提示' : '再给一点提示'}</button><button className="primary" disabled={busy || !draft.selected} onClick={submit}>{busy ? '正在保存…' : '提交答案'}</button></div></div>
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
              <h3 style={{ fontSize: 20, fontWeight: 700, margin: '0 0 8px', color: '#1e293b' }}>训练已暂停</h3>
              <p style={{ color: '#64748b', fontSize: 14, maxWidth: 360, margin: '0 0 16px', lineHeight: 1.6 }}>
                计时已冻结，题面已安全遮挡。<br />喝口水或处理下事务，准备好后点击继续。
              </p>
              <div style={{ fontSize: 13, color: '#475569', marginBottom: 24, background: '#f1f5f9', padding: '6px 14px', borderRadius: 20 }}>
                当前作答用时：<strong>{format(elapsed)}</strong>
              </div>
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
                  暂存并返回概览
                </Link>
              </div>
            </div>
          )}
        </div>
      </>}
      {viewResult && <div className="result review-comparison-view" aria-live="polite">
        {reviewIndex !== null && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', margin: '0 0 10px', padding: '8px 14px', background: '#f8fafc', border: '1px solid var(--line)', borderRadius: 8 }}>
            <span style={{ fontSize: 13, color: '#334155', fontWeight: 600 }}>
              📋 回看 · 第 {reviewPos} 题（{viewResult.correct ? '回答正确' : (viewResult.selected_answer ? '回答错误' : '未作答')}）
            </span>
            <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button type="button" disabled={reviewIndex <= 0 || busy} onClick={() => setReviewIndex(reviewIndex - 1)}
                style={{ padding: '4px 12px', fontSize: 12, border: '1px solid var(--line)', borderRadius: 6, background: '#fff', cursor: reviewIndex <= 0 ? 'default' : 'pointer' }}>◀ 上一题</button>
              <span style={{ fontSize: 12, color: 'var(--muted)' }}>{reviewIndex + 1} / {history.length}</span>
              <button type="button" disabled={reviewIndex >= history.length - 1 || busy} onClick={() => setReviewIndex(reviewIndex + 1)}
                style={{ padding: '4px 12px', fontSize: 12, border: '1px solid var(--line)', borderRadius: 6, background: '#fff', cursor: reviewIndex >= history.length - 1 ? 'default' : 'pointer' }}>下一题 ▶</button>
            </span>
          </div>
        )}
        <div className="review-summary-bar">
          <div className="review-summary-left">
            <span className="pill" style={{ background: viewResult.correct ? '#edf5ef' : '#fff1eb', color: viewResult.correct ? 'var(--accent)' : '#b91c1c' }}>
              {reviewIndex !== null ? '历史作答回看' : (viewResult.correct ? '作答已保存 · 回答正确' : (viewUnanswered ? '作答已保存 · 未作答（不会）' : '作答已保存 · 再接再厉'))}
            </span>
            <h2>{viewResult.correct ? '回答正确' : (viewUnanswered ? '未作答，直接看解析' : '再接再厉')}</h2>
            {viewUnanswered && (
              <p style={{ margin: '6px 0 0', fontSize: 12.5, color: '#64748b' }}>
                本题已按“未作答／不会”如实记录并结束作答{String(viewResult.audit_note || '').includes('跳过教学重答') ? '；本次在获取提示后提交，属于跳过教学重答，不计入正式统计，也不改变首次成绩' : '，已计入正式统计与复习计划'}。
              </p>
            )}
          </div>
          <div className="review-metrics-compact">
            <div className="metric-pill">
              <small>你的原始答案</small>
              <strong style={{ color: viewResult.correct ? 'var(--accent)' : '#b91c1c' }}>{viewResult.selected_answer ?? '未作答'}</strong>
            </div>
            <div className="metric-pill">
              <small>本题用时</small>
              <strong><RecordedTime elapsedMs={viewResult.elapsed_ms} timingValid={viewResult.timing_valid} /></strong>
            </div>
            <div className="metric-pill">
              <small>作答信心</small>
              <strong>{confidenceLabel(viewResult.confidence)}</strong>
            </div>
          </div>
        </div>

        <div className="comparison-grid">
          <QuestionReviewCard result={viewResult} revealAnswer={reviewIndex !== null} />

          <div className="panel-explanation-review">
            <InteractiveReviewCard
              attemptId={viewResult.id}
              isCorrect={viewResult.correct}
              confidence={viewResult.confidence}
              stem={viewResult.stem}
              module={viewResult.module}
              justGraded={reviewIndex === null && justGradedAttemptId === viewResult.id}
            />

            {reviewIndex !== null ? (
              <div style={{ marginTop: 12, display: 'flex', justifyContent: 'center' }}>
                <button className="primary" style={{ minWidth: 140 }} disabled={busy} onClick={() => setReviewIndex(null)}>
                  {session?.status === 'completed' ? '返回总览' : '返回当前题'}
                </button>
              </div>
            ) : session?.status === 'completed' ? (
              <div style={{ marginTop: 12 }}>
                <p className="completion">本轮训练已完成，{session.total} 道作答均已保存。</p>
                <div className="result-actions">
                  <Link className="secondary-link" href="/dashboard">查看学习概览</Link>
                  <button className="primary" disabled={busy} onClick={() => start(selectedSize)}>再练一轮</button>
                </div>
              </div>
            ) : (
              <div style={{ marginTop: 12, display: 'flex', justifyContent: 'flex-end' }}>
                <button className="primary" style={{ minWidth: 120 }} disabled={busy} onClick={nextQuestion}>下一题</button>
              </div>
            )}
          </div>
        </div>
      </div>}
        </>
      )}
    </section></div>
    <footer>行测训练<span>作答 / 解析 / 复盘 / 心得</span></footer>
    {showUnansweredConfirm && groupData && (
      <div
        onClick={() => setShowUnansweredConfirm(false)}
        style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.65)',
          backdropFilter: 'blur(4px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1100,
          padding: 24,
        }}
      >
        <div
          onClick={e => e.stopPropagation()}
          style={{
            background: '#fff',
            borderRadius: 14,
            padding: 28,
            maxWidth: 440,
            width: '100%',
            boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.2)',
          }}
        >
          <h3 style={{ margin: '0 0 10px', fontSize: 18, color: '#b45309' }}>⚠️ 本组还有未作答题目</h3>
          <p style={{ margin: '0 0 20px', color: '#475569', fontSize: 14, lineHeight: 1.6 }}>
            第 {groupData.questions.map((q, idx) => (!groupDrafts[q.question_id]?.selected ? idx + 1 : null)).filter(Boolean).join('、')} 题尚未选择答案。<br />
            可返回继续作答；也可确认结算——未作答题目将按“未作答/不会”如实记录，计入本组结算，绝不伪造选项。
          </p>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                const firstUnanswered = groupData.questions.findIndex(q => !groupDrafts[q.question_id]?.selected);
                if (firstUnanswered !== -1) setActiveQIndex(firstUnanswered);
                setShowUnansweredConfirm(false);
              }}
            >
              返回修改
            </button>
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => submitGroup(true)}
            >
              {busy ? '正在保存结算…' : '确认结算（未答题记为未作答）'}
            </button>
          </div>
        </div>
      </div>
    )}
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
    <DeviceSyncModal isOpen={showSyncModal} onClose={() => setShowSyncModal(false)} />
  </main>;
}
