'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { api, ImportJob, ReviewItem, PublishResult, MasteryData, MasteryNode } from '../../lib/api';

const SAMPLE_PARSED_DOC = {
  schema_version: '1.0.0',
  document_version_id: 'sample-version-2026',
  document_id: 'sample-doc-gongkao-2026',
  parser: 'docling',
  parser_version: '1.0.0',
  markdown: '2026年公务员录用考试标准真题',
  pages: [1, 2],
  blocks: [
    {
      block_id: 'b_mod_5',
      block_type: 'heading',
      text: '第五部分 资料分析',
      page: 1,
      heading_path: ['第五部分 资料分析'],
    },
    {
      block_id: 'b_mat_1',
      block_type: 'paragraph',
      text: '根据以下资料，回答第101~102题：\n2023年全国规模以上文化及相关产业企业实现营业收入129515亿元，比上年增长8.2%。其中，文化新业态特征较为明显的16个行业小类实现营业收入52395亿元，比上年增长15.3%，占规模以上文化企业营业收入的比重为40.5%。',
      page: 1,
      heading_path: ['第五部分 资料分析'],
    },
    {
      block_id: 'b_q_101',
      block_type: 'paragraph',
      text: '101. 2023年全国规模以上文化企业中，文化新业态特征较为明显的行业小类营业收入比上年增加约多少亿元？',
      page: 1,
      heading_path: ['第五部分 资料分析'],
    },
    {
      block_id: 'b_opt_101',
      block_type: 'paragraph',
      text: 'A. 6950   B. 7500   C. 8100   D. 8900',
      page: 1,
      heading_path: ['第五部分 资料分析'],
    },
    {
      block_id: 'b_q_102',
      block_type: 'paragraph',
      text: '102. 2022年文化新业态行业小类营业收入占全国规模以上文化企业营业收入的比重约为：',
      page: 1,
      heading_path: ['第五部分 资料分析'],
    },
    {
      block_id: 'b_opt_102',
      block_type: 'paragraph',
      text: 'A. 35.0%   B. 38.0%   C. 42.0%   D. 45.0%',
      page: 1,
      heading_path: ['第五部分 资料分析'],
    },
    {
      block_id: 'b_ans_head',
      block_type: 'heading',
      text: '参考答案及解析',
      page: 2,
      heading_path: ['参考答案及解析'],
    },
    {
      block_id: 'b_ans_101',
      block_type: 'paragraph',
      text: '101.【答案】A。解析：增长量计算公式为现期量×增长率÷(1+增长率)。52395×15.3%÷(1+15.3%)≈52395÷7.5≈6986亿元，与A项最接近。故本题选A。',
      page: 2,
      heading_path: ['参考答案及解析'],
    },
    {
      block_id: 'b_ans_102',
      block_type: 'paragraph',
      text: '102.【答案】B。解析：两期比重计算。部分增速15.3%大于整体增速8.2%，因此2023年比重高于2022年，2022年比重小于40.5%，排除C、D；结合比重差计算可知约38.0%。故本题选B。',
      page: 2,
      heading_path: ['参考答案及解析'],
    },
  ],
};

function parsePastedAnswers(raw: string): Record<string, string> {
  const result: Record<string, string> = {};
  if (!raw.trim()) return result;

  const lines = raw.split(/[\r\n]+/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    // Pattern 1: Range lines like "1-5: A B C D A" or "1~5: A B C D A"
    const rangeMatch = trimmed.match(/^(\d+)\s*[-~至到]\s*(\d+)[\s:：]+([A-D\s]+)/i);
    if (rangeMatch) {
      const start = parseInt(rangeMatch[1], 10);
      const end = parseInt(rangeMatch[2], 10);
      const letters = rangeMatch[3].replace(/\s+/g, '').toUpperCase().split('');
      for (let i = 0; i < letters.length && start + i <= end; i++) {
        result[String(start + i)] = letters[i];
      }
      continue;
    }

    // Pattern 2: Dotted / colons like "1.A 2.B 3.C" or "第1题: A"
    const pairs = Array.from(trimmed.matchAll(/(?:第\s*)?(\d+)\s*(?:[\.、:：\s]|\s*题\s*[\.、:：\s]*)\s*([A-D])/gi));
    if (pairs.length > 0) {
      for (const p of pairs) {
        result[p[1]] = p[2].toUpperCase();
      }
      continue;
    }

    // Pattern 3: Tokens like "1A 2B 3C"
    const tokens = Array.from(trimmed.matchAll(/(\d+)\s*([A-D])\b/gi));
    if (tokens.length > 0) {
      for (const tm of tokens) {
        result[tm[1]] = tm[2].toUpperCase();
      }
      continue;
    }
  }

  // Fallback: If no numbered pairs detected, read continuous letter stream
  if (Object.keys(result).length === 0) {
    const letters = raw.replace(/[^A-Za-z]/g, '').toUpperCase().split('');
    letters.forEach((letter, idx) => {
      if (['A', 'B', 'C', 'D'].includes(letter)) {
        result[String(idx + 1)] = letter;
      }
    });
  }

  return result;
}

export default function ImporterPage() {
  const [activeTab, setActiveTab] = useState<'pdf' | 'manual'>('pdf');
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<ImportJob | null>(null);
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [filterReason, setFilterReason] = useState<string>('');

  // Knowledge Nodes for dropdowns
  const [knowledgeNodes, setKnowledgeNodes] = useState<MasteryNode[]>([]);

  // Real PDF file upload state
  const [questionFile, setQuestionFile] = useState<File | null>(null);
  const [answerFile, setAnswerFile] = useState<File | null>(null);
  const [uploadTitle, setUploadTitle] = useState('');
  const [importStage, setImportStage] = useState<string | null>(null);

  // Batch Answer Paste Drawer state
  const [showBatchDrawer, setShowBatchDrawer] = useState(false);
  const [batchRawText, setBatchRawText] = useState('');

  // Edit draft modal / form state
  const [editingItem, setEditingItem] = useState<ReviewItem | null>(null);
  const [editAnswer, setEditAnswer] = useState('A');
  const [editKnowledge, setEditKnowledge] = useState('');
  const [editExplanation, setEditExplanation] = useState('');

  // Manual Question Authoring State
  const [manualModule, setManualModule] = useState<string>('图形推理');
  const [manualNodeId, setManualNodeId] = useState<string>('');
  const [manualSource, setManualSource] = useState('精选好题');
  const [manualStem, setManualStem] = useState('');
  const [manualIsInline, setManualIsInline] = useState(false);
  const [manualOptA, setManualOptA] = useState('');
  const [manualOptB, setManualOptB] = useState('');
  const [manualOptC, setManualOptC] = useState('');
  const [manualOptD, setManualOptD] = useState('');
  const [manualAnswer, setManualAnswer] = useState<'A' | 'B' | 'C' | 'D'>('A');
  const [manualExplanation, setManualExplanation] = useState('');
  const [manualDifficulty, setManualDifficulty] = useState(0.6);
  const [manualSaving, setManualSaving] = useState(false);

  const loadJobs = async (targetId?: string) => {
    try {
      const res = await api<{ jobs: ImportJob[] }>('/importer/jobs');
      setJobs(res.jobs);
      if (res.jobs.length > 0) {
        const stored = typeof window !== 'undefined' ? localStorage.getItem('gongkao_last_import_job_id') : null;
        const meaningfulJob = res.jobs.find(
          j =>
            (j.published_questions || 0) > 0 ||
            (j.total_candidates || 0) > 0 ||
            (j.needs_review || 0) > 0 ||
            j.status === 'completed' ||
            j.status === 'needs_review'
        );
        const selected =
          targetId ||
          (stored && res.jobs.some(j => j.id === stored) ? stored : null) ||
          activeJobId ||
          (meaningfulJob ? meaningfulJob.id : res.jobs[0].id);
        setActiveJobId(selected);
        if (typeof window !== 'undefined' && selected) {
          localStorage.setItem('gongkao_last_import_job_id', selected);
        }
      }
    } catch {
      // ignore on initial load
    }
  };

  useEffect(() => {
    // Load knowledge nodes for dropdowns
    api<MasteryData>('/mastery')
      .then(res => {
        setKnowledgeNodes(res.nodes);
        if (res.nodes.length > 0 && !manualNodeId) {
          setManualNodeId(res.nodes[0].id);
        }
      })
      .catch(() => {});

    if (typeof window !== 'undefined') {
      const urlParams = new URLSearchParams(window.location.search);
      const urlJobId = urlParams.get('job_id');
      loadJobs(urlJobId || undefined);
    } else {
      loadJobs();
    }
  }, []);

  useEffect(() => {
    if (!activeJobId) return;
    if (typeof window !== 'undefined') {
      const currentUrl = new URL(window.location.href);
      currentUrl.searchParams.set('job_id', activeJobId);
      window.history.replaceState(null, '', currentUrl.toString());
    }
    const fetchDetail = async () => {
      try {
        const job = await api<ImportJob>(`/importer/jobs/${activeJobId}`);
        setActiveJob(job);
        const qUrl = filterReason
          ? `/importer/jobs/${activeJobId}/review?reason=${encodeURIComponent(filterReason)}`
          : `/importer/jobs/${activeJobId}/review`;
        const rRes = await api<{ items: ReviewItem[] }>(qUrl);
        setReviewItems(rRes.items);
      } catch (err: any) {
        setMsg({ type: 'err', text: err.message });
      }
    };
    fetchDetail();
  }, [activeJobId, filterReason]);

  // Filtered knowledge nodes by module
  const moduleKnowledgeNodes = useMemo(() => {
    return knowledgeNodes.filter(n => n.module === manualModule);
  }, [knowledgeNodes, manualModule]);

  useEffect(() => {
    if (moduleKnowledgeNodes.length > 0) {
      setManualNodeId(moduleKnowledgeNodes[0].id);
    }
  }, [manualModule, moduleKnowledgeNodes]);

  const handleUploadImport = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!questionFile) {
      setMsg({ type: 'err', text: '请先选择题库 PDF 文件！' });
      return;
    }
    setLoading(true);
    setMsg(null);
    setImportStage('任务排队中...');

    try {
      const formData = new FormData();
      formData.append('question_file', questionFile);
      if (answerFile) {
        formData.append('answer_file', answerFile);
      }
      if (uploadTitle) {
        formData.append('title', uploadTitle);
      }

      const res = await fetch('/api/importer/upload', {
        method: 'POST',
        body: formData,
      });
      if (!res.ok && res.status !== 202) {
        const errJson = await res.json().catch(() => ({}));
        if (res.status === 500) {
          throw new Error('文件解析超时。若为超过 100 页大讲义，建议拆分后上传。');
        }
        throw new Error(errJson.detail || `Upload failed with status ${res.status}`);
      }

      const queueData = await res.json();
      const jobId = queueData.job_id;
      setActiveJobId(jobId);
      if (typeof window !== 'undefined') {
        localStorage.setItem('gongkao_last_import_job_id', jobId);
      }
      setImportStage('任务已提交后台，正在异步处理中...');
      await loadJobs(jobId);

      // Start asynchronous job polling
      let pollCount = 0;
      const pollTimer = setInterval(async () => {
        try {
          pollCount += 1;
          const jobRes = await api<ImportJob>(`/importer/jobs/${jobId}`);
          setActiveJob(jobRes);
          setImportStage(`阶段: ${jobRes.stage || jobRes.status}`);

          if (jobRes.status === 'needs_review' || jobRes.status === 'ready_to_publish' || jobRes.status === 'completed') {
            clearInterval(pollTimer);
            setLoading(false);
            setImportStage(jobRes.status === 'needs_review' ? '处理完成，部分题目进入待审复核队列' : '导入完成，题目已就绪！');
            await loadJobs(jobId);
            setMsg({
              type: 'ok',
              text: `任务 ${jobId} 导入完成！就绪: ${jobRes.validated_questions} 题，待审: ${jobRes.needs_review} 题。`,
            });
          } else if (jobRes.status === 'failed') {
            clearInterval(pollTimer);
            setLoading(false);
            setImportStage('Failed');
            setMsg({ type: 'err', text: `任务处理异常: ${jobRes.error || '后台解析遇到未处理错误'}` });
          } else if (pollCount > 100) {
            clearInterval(pollTimer);
            setLoading(false);
            setImportStage('任务仍在后台运行，可随时刷新查看');
          }
        } catch {
          // ignore transient poll errors
        }
      }, 1500);

      setQuestionFile(null);
      setAnswerFile(null);
      setUploadTitle('');
    } catch (err: any) {
      setLoading(false);
      setImportStage('Failed');
      setMsg({ type: 'err', text: `导入提交失败: ${err.message}` });
    }
  };

  const handleCreateSampleJob = async () => {
    setLoading(true);
    setMsg(null);
    try {
      const newJob = await api<ImportJob>('/importer/jobs', {
        source_document_id: 'demo_gongkao_2026.pdf',
        source_document_version_id: 'v_2026_01',
        filename: '2026年国考行测真题样卷.pdf',
      });
      setActiveJobId(newJob.id);
      if (typeof window !== 'undefined') {
        localStorage.setItem('gongkao_last_import_job_id', newJob.id);
      }
      // Immediately run extraction on sample
      const processedJob = await api<ImportJob>(`/importer/jobs/${newJob.id}/process`, {
        parsed_document: SAMPLE_PARSED_DOC,
      });
      setActiveJob(processedJob);
      await loadJobs(newJob.id);
      setMsg({ type: 'ok', text: '真题样卷快速导入并解析完成！可直接在下方查看与发布。' });
    } catch (err: any) {
      setMsg({ type: 'err', text: err.message });
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteJob = async (jobId: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    if (!confirm('确定要删除该导入任务记录吗？（已正式发布的题目不会被删除）')) return;
    try {
      await fetch(`/api/importer/jobs/${jobId}`, { method: 'DELETE' });
      const nextJobs = jobs.filter(j => j.id !== jobId);
      setJobs(nextJobs);
      if (activeJobId === jobId) {
        const nextActive = nextJobs[0]?.id || null;
        setActiveJobId(nextActive);
        if (typeof window !== 'undefined') {
          if (nextActive) {
            localStorage.setItem('gongkao_last_import_job_id', nextActive);
          } else {
            localStorage.removeItem('gongkao_last_import_job_id');
          }
        }
      }
      setMsg({ type: 'ok', text: '导入任务记录已成功删除' });
    } catch {
      setMsg({ type: 'err', text: '删除失败，请稍后重试' });
    }
  };

  const handlePublish = async () => {
    if (!activeJobId) return;
    setLoading(true);
    setMsg(null);
    try {
      const res = await api<PublishResult>(`/importer/jobs/${activeJobId}/publish`, {
        job_id: activeJobId,
        draft_ids: null,
      });
      setMsg({
        type: 'ok',
        text: `发布成功！本次成功发布 ${res.published_count} 道题目入库，跳过 ${res.skipped_count} 道。`,
      });
      await loadJobs(activeJobId);
    } catch (err: any) {
      setMsg({ type: 'err', text: `发布失败: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  // Batch Answer Application Handler
  const parsedBatchAnswers = useMemo(() => {
    return parsePastedAnswers(batchRawText);
  }, [batchRawText]);

  const handleApplyBatchAnswers = async () => {
    if (!activeJobId) return;
    const count = Object.keys(parsedBatchAnswers).length;
    if (count === 0) {
      alert('未识别到任何有效题号与答案！请参考格式：1-5: A B C D A 或 1.A 2.B');
      return;
    }
    setLoading(true);
    try {
      const res = await api<{ status: string; updated_count: number }>(`/importer/jobs/${activeJobId}/batch-answers`, {
        answers: parsedBatchAnswers,
      });
      setMsg({
        type: 'ok',
        text: `批量补录成功！已成功为本试卷匹配填入 ${res.updated_count} 道题目的标准答案，并标记为就绪发布！`,
      });
      setShowBatchDrawer(false);
      setBatchRawText('');
      await loadJobs(activeJobId);
    } catch (err: any) {
      setMsg({ type: 'err', text: `批量补录失败: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  // Save Edit Dialog
  const handleSaveEdit = async () => {
    if (!editingItem) return;
    try {
      await api(`/importer/drafts/${editingItem.draft_id}/review`, {
        action: 'modify',
        answer: editAnswer,
        explanation: editExplanation,
        knowledge_node_code: editKnowledge || undefined,
      });
      setEditingItem(null);
      if (activeJobId) {
        const job = await api<ImportJob>(`/importer/jobs/${activeJobId}`);
        setActiveJob(job);
        const qUrl = filterReason
          ? `/importer/jobs/${activeJobId}/review?reason=${encodeURIComponent(filterReason)}`
          : `/importer/jobs/${activeJobId}/review`;
        const rRes = await api<{ items: ReviewItem[] }>(qUrl);
        setReviewItems(rRes.items);
      }
      setMsg({ type: 'ok', text: `第 ${editingItem.question_number} 题答案与解析已更新并标记就绪！` });
    } catch (err: any) {
      setMsg({ type: 'err', text: `更新失败: ${err.message}` });
    }
  };

  // Save Manual Question
  const handleSaveManualQuestion = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualStem.trim()) {
      alert('请填写题干内容！');
      return;
    }
    if (!manualNodeId) {
      alert('请选择归属考点！');
      return;
    }

    setManualSaving(true);
    setMsg(null);

    const optionsMap: Record<string, string> = manualIsInline
      ? { A: 'A', B: 'B', C: 'C', D: 'D' }
      : {
          A: manualOptA || 'A',
          B: manualOptB || 'B',
          C: manualOptC || 'C',
          D: manualOptD || 'D',
        };

    try {
      const res = await api<{ status: string; id: string }>('/questions', {
        module: manualModule,
        knowledge_node_id: manualNodeId,
        stem: manualStem,
        options: optionsMap,
        answer: manualAnswer,
        explanation: manualExplanation || '暂无详细解析',
        source: manualSource || '手动出题录入',
        difficulty: manualDifficulty,
        estimated_seconds: 60,
      });

      setMsg({
        type: 'ok',
        text: `试题录入成功（编号: ${res.id}）！已自动建立考点与技能映射，可在行测训练中刷题！`,
      });

      // Clear question form
      setManualStem('');
      setManualOptA('');
      setManualOptB('');
      setManualOptC('');
      setManualOptD('');
      setManualExplanation('');
    } catch (err: any) {
      setMsg({ type: 'err', text: `录题失败: ${err.message}` });
    } finally {
      setManualSaving(false);
    }
  };

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
          <Link href="/review">到期复习</Link>
          <Link href="/exam">全真模考</Link>
          <Link href="/shenlun">申论工作台</Link>
          <Link href="/importer" className="active">
            题库录入与导入
          </Link>
        <Link href="/settings">设置</Link></nav>
        <span className="local">● 智能导入工作流</span>
      </header>

      <div className="intro dashboard-intro">
        <span className="eyebrow">QUESTION INGESTION / 试题录入中心</span>
        <h1>试卷 PDF 智能导入与手动出题工作台</h1>
        <p>支持真实 PDF 试卷批量版面提取，支持整卷答案快速补录粘贴，亦支持单题手动出题与深度解析直接入库。</p>
      </div>

      {msg && (
        <div
          role="alert"
          className={msg.type === 'err' ? 'error' : 'feedback-card'}
          style={{ marginBottom: '1.5rem' }}
        >
          {msg.text}
        </div>
      )}

      {/* Top Mode Tabs */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        <button
          type="button"
          onClick={() => setActiveTab('pdf')}
          style={{
            background: activeTab === 'pdf' ? 'var(--accent)' : '#fff',
            color: activeTab === 'pdf' ? '#fff' : 'var(--ink)',
            border: `1px solid ${activeTab === 'pdf' ? 'var(--accent)' : 'var(--line)'}`,
            borderRadius: 8,
            padding: '10px 22px',
            fontSize: 14,
            fontWeight: 700,
            cursor: 'pointer',
          }}
        >
          📄 PDF 智能导入与试卷管理
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('manual')}
          style={{
            background: activeTab === 'manual' ? 'var(--accent)' : '#fff',
            color: activeTab === 'manual' ? '#fff' : 'var(--ink)',
            border: `1px solid ${activeTab === 'manual' ? 'var(--accent)' : 'var(--line)'}`,
            borderRadius: 8,
            padding: '10px 22px',
            fontSize: 14,
            fontWeight: 700,
            cursor: 'pointer',
          }}
        >
          ✍️ 手动录入新题与解析
        </button>
      </div>

      {/* ========================================================================= */}
      {/* MODE 1: PDF IMPORT & REVIEW WORKSPACE */}
      {/* ========================================================================= */}
      {activeTab === 'pdf' && (
        <>
          {/* History Jobs Switcher */}
          {jobs.length > 0 && (
            <section className="dashboard-section" style={{ marginBottom: '1.5rem', padding: '20px 24px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                <div>
                  <span className="eyebrow">IMPORT HISTORY / 导入任务历史</span>
                  <h2 style={{ fontSize: 18, margin: '4px 0 0' }}>历史导入任务管理（共 {jobs.length} 个任务已存盘）</h2>
                </div>
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                  点击卡片即可直接切换查看题目与审核结果，刷新自动保留当前选择
                </span>
              </div>
              <div style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 8 }}>
                {jobs.map(j => {
                  const isSelected = j.id === activeJobId;
                  const isDone = j.status === 'completed';
                  const isReview = j.status === 'needs_review';
                  const isFail = j.status === 'failed';
                  const badgeBg = isDone ? '#2e7d32' : isReview ? '#d97706' : isFail ? '#dc2626' : '#0284c7';
                  return (
                    <button
                      key={j.id}
                      type="button"
                      onClick={() => {
                        setActiveJobId(j.id);
                        if (typeof window !== 'undefined') {
                          localStorage.setItem('gongkao_last_import_job_id', j.id);
                        }
                      }}
                      style={{
                        background: isSelected ? '#f6f9f6' : '#ffffff',
                        border: isSelected ? '2px solid var(--accent)' : '1px solid var(--line)',
                        borderRadius: 8,
                        padding: '12px 16px',
                        textAlign: 'left',
                        cursor: 'pointer',
                        minWidth: 260,
                        maxWidth: 320,
                        flexShrink: 0,
                        boxShadow: isSelected ? '0 3px 10px rgba(0,0,0,0.06)' : 'none',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span
                            style={{
                              fontSize: 11,
                              background: `${badgeBg}18`,
                              color: badgeBg,
                              padding: '2px 8px',
                              borderRadius: 4,
                              fontWeight: 700,
                            }}
                          >
                            {j.status}
                          </span>
                          <span
                            role="button"
                            onClick={e => handleDeleteJob(j.id, e)}
                            style={{ color: '#999', fontSize: 12, padding: '1px 5px', borderRadius: 3, lineHeight: 1 }}
                            title="删除此任务记录"
                          >
                            ✕
                          </span>
                        </div>
                        <strong style={{ fontSize: 12, color: (j.published_questions || 0) > 0 || (j.validated_questions || 0) > 0 ? 'var(--accent)' : '#888' }}>
                          {j.published_questions > 0
                            ? `${j.published_questions} 题已发布`
                            : j.validated_questions > 0
                            ? `${j.validated_questions} 题就绪`
                            : j.total_candidates > 0
                            ? `${j.total_candidates} 题解析`
                            : '排队中'}
                        </strong>
                      </div>
                      <div
                        style={{
                          fontSize: 13,
                          fontWeight: isSelected ? 700 : 500,
                          color: 'var(--ink)',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}
                        title={j.filename}
                      >
                        {j.filename || '未命名 PDF 真题'}
                      </div>
                      <small style={{ display: 'block', fontSize: 11, color: '#888', marginTop: 4 }}>
                        阶段: {j.stage || 'queued'} · {j.created_at.slice(0, 16)}
                      </small>
                    </button>
                  );
                })}
              </div>
            </section>
          )}

          {/* Upload and Sample Section */}
          <div className="decision-grid" style={{ marginBottom: '1.5rem' }}>
            <article className="focus-card" style={{ flex: '1 1 55%' }}>
              <span className="eyebrow">REAL PDF UPLOAD / 真题导入</span>
              <h2>真实 PDF 文件上传与配对导入</h2>
              <form onSubmit={handleUploadImport} style={{ display: 'flex', flexDirection: 'column', gap: '0.8rem', marginTop: '0.8rem' }}>
                <div>
                  <label htmlFor="question-pdf-upload" style={{ display: 'block', fontSize: '0.9rem', marginBottom: '0.3rem', fontWeight: 600 }}>
                    题库 PDF *
                  </label>
                  <input
                    type="file"
                    accept=".pdf"
                    id="question-pdf-upload"
                    disabled={loading}
                    onChange={(e) => setQuestionFile(e.target.files?.[0] || null)}
                    style={{ width: '100%', padding: '0.4rem', border: '1px solid #cbd5e1', borderRadius: '4px' }}
                  />
                  <small style={{ color: '#777', display: 'block', marginTop: 3 }}>
                    提示：推荐上传 10~30 页标准真题卷。如为百页以上整本大讲义，请拆分或稍作等待。
                  </small>
                </div>
                <div>
                  <label htmlFor="answer-pdf-upload" style={{ display: 'block', fontSize: '0.9rem', marginBottom: '0.3rem', fontWeight: 600 }}>
                    答案/解析 PDF（可选，支持题本+答案分离模式）
                  </label>
                  <input
                    type="file"
                    accept=".pdf"
                    id="answer-pdf-upload"
                    disabled={loading}
                    onChange={(e) => setAnswerFile(e.target.files?.[0] || null)}
                    style={{ width: '100%', padding: '0.4rem', border: '1px solid #cbd5e1', borderRadius: '4px' }}
                  />
                </div>
                <div>
                  <label htmlFor="upload-title-input" style={{ display: 'block', fontSize: '0.9rem', marginBottom: '0.3rem' }}>
                    套卷标题（可选）
                  </label>
                  <input
                    type="text"
                    id="upload-title-input"
                    placeholder="例如：2026年国考行测真题卷"
                    value={uploadTitle}
                    disabled={loading}
                    onChange={(e) => setUploadTitle(e.target.value)}
                    style={{ width: '100%', padding: '0.4rem', border: '1px solid #cbd5e1', borderRadius: '4px' }}
                  />
                </div>

                {importStage && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.2rem' }}>
                    <span className="pill" style={{ backgroundColor: importStage === 'Completed' ? '#2e7d32' : importStage === 'Failed' ? '#dc2626' : '#0284c7', color: '#fff', fontSize: '0.8rem' }}>
                      阶段: {importStage}
                    </span>
                  </div>
                )}

                <div style={{ display: 'flex', gap: '0.8rem', marginTop: '0.5rem' }}>
                  <button
                    type="submit"
                    disabled={loading || !questionFile}
                    className="primary-link"
                    style={{ border: 'none', cursor: !loading && questionFile ? 'pointer' : 'not-allowed', backgroundColor: '#2563eb', color: '#fff' }}
                  >
                    {loading ? '正在处理中…' : '开始导入'}
                  </button>
                  <button
                    type="button"
                    onClick={handleCreateSampleJob}
                    disabled={loading}
                    className="secondary-btn"
                    style={{ cursor: 'pointer', padding: '0.5rem 1rem', border: '1px solid #cbd5e1', borderRadius: '4px', background: '#f8fafc' }}
                  >
                    导入真题样卷并开始处理
                  </button>
                </div>
              </form>
            </article>

            <article className="evidence-card" style={{ flex: '1 1 35%' }}>
              <h2>导入核心原则与保障</h2>
              <dl>
                <div>
                  <dt>答案权威性</dt>
                  <dd>模型绝对不猜答案；必须来自原 PDF 答案或显式解析</dd>
                </div>
                <div>
                  <dt>题本+答案自动配对</dt>
                  <dd>支持独立的答案篇 PDF，依题号和模块严格对齐</dd>
                </div>
                <div>
                  <dt>知识点收敛 (K6)</dt>
                  <dd>严格约束在 Knowledge Hub K6 体系内，杜绝臆造标签</dd>
                </div>
                <div>
                  <dt>异常严格拦截</dt>
                  <dd>绝大多数标准题自动就绪，缺答案/选项异常题进入复核队列</dd>
                </div>
              </dl>
            </article>
          </div>

          {/* Active Job Details and Actions */}
          {activeJob && (
            <section className="dashboard-section" style={{ marginBottom: '1.5rem' }}>
              <div className="section-heading">
                <div>
                  <span className="eyebrow">JOB #{activeJob.id}</span>
                  <h2>{activeJob.filename || '未命名 PDF 导入任务'}</h2>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <button
                    type="button"
                    onClick={() => handleDeleteJob(activeJob.id)}
                    style={{
                      background: 'transparent',
                      border: '1px solid #cbd5e1',
                      color: '#666',
                      fontSize: 12,
                      padding: '5px 12px',
                      borderRadius: 4,
                      cursor: 'pointer',
                    }}
                  >
                    🗑️ 删除此记录
                  </button>
                  <span
                    className="pill"
                    style={{
                      backgroundColor:
                        activeJob.status === 'completed'
                          ? '#2e7d32'
                          : activeJob.status === 'needs_review'
                          ? '#d97706'
                          : activeJob.status === 'failed'
                          ? '#dc2626'
                          : '#0284c7',
                      color: '#fff',
                    }}
                  >
                    状态: {activeJob.status} ({activeJob.stage})
                  </span>
                </div>
              </div>

              {activeJob.status === 'failed' && (
                <div
                  style={{
                    margin: '16px 0',
                    padding: '14px 18px',
                    background: '#fff1eb',
                    border: '1px solid #fecaca',
                    borderRadius: 8,
                  }}
                >
                  <strong style={{ color: '#b91c1c' }}>⚠️ 该任务解析超时或中断</strong>
                  <p style={{ margin: '6px 0 0', fontSize: 13, color: '#7f1d1d', lineHeight: 1.5 }}>
                    {activeJob.error || '该文档包含超过 100 页大体量切图，单次处理耗时较长。系统已触发保护机制，正式题库未受污染。您可以点击上方切换其他已就绪试卷，或点击右侧“删除此记录”。'}
                  </p>
                </div>
              )}

              <section className="metric-grid" aria-label="处理进度">
                <article>
                  <small>解析题目</small>
                  <strong>
                    {activeJob.parsed_questions} / {activeJob.total_candidates || 2}
                  </strong>
                  <span>识别题干与选项</span>
                </article>
                <article>
                  <small>确定性答案匹配</small>
                  <strong>{activeJob.validated_questions} 题</strong>
                  <span>权威答案页对齐</span>
                </article>
                <article className="featured">
                  <small>自动通过 (Auto Accepted)</small>
                  <strong>{activeJob.auto_accepted_count} 题</strong>
                  <span>高置信直接就绪</span>
                </article>
                <article>
                  <small>待人工复核 (Needs Review)</small>
                  <strong style={{ color: activeJob.needs_review > 0 ? '#dc2626' : 'inherit' }}>
                    {activeJob.needs_review} 题
                  </strong>
                  <span>缺少答案或置信不足</span>
                </article>
                <article>
                  <small>已正式发布</small>
                  <strong>{activeJob.published_questions} 题</strong>
                  <span>进入正式可评分题库</span>
                </article>
              </section>

              {/* Actions Bar: Publish & Batch Answer Drawer */}
              <div style={{ marginTop: '1.5rem', display: 'flex', gap: '1rem', flexWrap: 'wrap', alignItems: 'center' }}>
                <button
                  onClick={handlePublish}
                  disabled={loading || activeJob.validated_questions === 0}
                  className="primary-link"
                  style={{ border: 'none', cursor: 'pointer', backgroundColor: '#2563eb', color: '#fff', padding: '10px 20px', borderRadius: 6 }}
                >
                  发布就绪题目到正式题库
                </button>

                <button
                  type="button"
                  onClick={() => setShowBatchDrawer(!showBatchDrawer)}
                  style={{
                    background: '#f8fafc',
                    border: '1px solid #cbd5e1',
                    borderRadius: 6,
                    padding: '10px 18px',
                    fontSize: 13,
                    fontWeight: 600,
                    cursor: 'pointer',
                    color: 'var(--ink)',
                  }}
                >
                  {showBatchDrawer ? '▲ 收起答案录入' : '📋 批量录入/粘贴本卷答案'}
                </button>
              </div>

              {/* Collapsible Batch Answer Drawer */}
              {showBatchDrawer && (
                <div
                  style={{
                    marginTop: 16,
                    padding: '18px 22px',
                    background: '#f8faf8',
                    border: '1px solid #d2e4d6',
                    borderRadius: 8,
                  }}
                >
                  <h3 style={{ margin: '0 0 8px', fontSize: 15, color: 'var(--accent)' }}>
                    📋 批量录入 / 粘贴参考答案
                  </h3>
                  <p style={{ margin: '0 0 10px', fontSize: 13, color: '#55665b' }}>
                    支持常见答案格式（如 <code>1-5: A B C D A</code>、<code>1.A 2.B 3.C</code> 或连续字母 <code>ABCDA</code>）。系统将自动对应本卷题号并批量标记为就绪发布！
                  </p>
                  <textarea
                    rows={4}
                    value={batchRawText}
                    onChange={e => setBatchRawText(e.target.value)}
                    placeholder="例如粘贴：&#10;1-5: A B C D A&#10;6-10: C B A D C&#10;或 1.A 2.B 3.C 4.D"
                    style={{
                      width: '100%',
                      padding: '10px',
                      borderRadius: 6,
                      border: '1px solid #cbd5e1',
                      fontSize: 13,
                      fontFamily: 'monospace',
                    }}
                  />
                  <div style={{ marginTop: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <small style={{ color: 'var(--muted)', fontSize: 12 }}>
                      已识别到 <strong>{Object.keys(parsedBatchAnswers).length}</strong> 道题答案
                    </small>
                    <button
                      type="button"
                      disabled={loading || Object.keys(parsedBatchAnswers).length === 0}
                      onClick={handleApplyBatchAnswers}
                      style={{
                        background: 'var(--accent)',
                        color: '#fff',
                        border: 'none',
                        padding: '8px 18px',
                        borderRadius: 6,
                        fontSize: 13,
                        fontWeight: 600,
                        cursor: Object.keys(parsedBatchAnswers).length > 0 ? 'pointer' : 'not-allowed',
                      }}
                    >
                      一键应用并标记就绪
                    </button>
                  </div>
                </div>
              )}
            </section>
          )}

          {/* Human Review Queue */}
          <section className="dashboard-section">
            <div className="section-heading">
              <div>
                <span className="eyebrow">HUMAN REVIEW QUEUE</span>
                <h2>异常复核工作台 ({reviewItems.length})</h2>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <button
                  onClick={() => setFilterReason('')}
                  className="pill"
                  style={{ background: filterReason === '' ? '#333' : '#eee', color: filterReason === '' ? '#fff' : '#333' }}
                >
                  全部
                </button>
                <button
                  onClick={() => setFilterReason('ANSWER_MISSING')}
                  className="pill"
                  style={{
                    background: filterReason === 'ANSWER_MISSING' ? '#333' : '#eee',
                    color: filterReason === 'ANSWER_MISSING' ? '#fff' : '#333',
                  }}
                >
                  缺答案
                </button>
                <button
                  onClick={() => setFilterReason('KNOWLEDGE_LOW_CONFIDENCE')}
                  className="pill"
                  style={{
                    background: filterReason === 'KNOWLEDGE_LOW_CONFIDENCE' ? '#333' : '#eee',
                    color: filterReason === 'KNOWLEDGE_LOW_CONFIDENCE' ? '#fff' : '#333',
                  }}
                >
                  知识点低置信
                </button>
              </div>
            </div>

            {reviewItems.length === 0 ? (
              <div className="empty-state">
                <p>当前任务没有需要人工复核的异常试题，或已全部处理就绪！</p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginTop: '1rem' }}>
                {reviewItems.map(item => (
                  <article
                    key={item.draft_id}
                    style={{
                      border: '1px solid #e2e8f0',
                      borderRadius: '8px',
                      padding: '1rem',
                      backgroundColor: '#fff',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                      <span style={{ fontWeight: 600, fontSize: '1.1rem' }}>第 {item.question_number} 题</span>
                      <div style={{ display: 'flex', gap: '0.5rem' }}>
                        {item.review_reasons.map(r => (
                          <span key={r} className="pill" style={{ backgroundColor: '#fee2e2', color: '#991b1b' }}>
                            {r}
                          </span>
                        ))}
                        <span
                          className="pill"
                          style={{
                            backgroundColor: item.validation_status === 'READY_TO_PUBLISH' ? '#dcfce7' : '#fef9c3',
                            color: item.validation_status === 'READY_TO_PUBLISH' ? '#166534' : '#854d0e',
                          }}
                        >
                          {item.validation_status}
                        </span>
                      </div>
                    </div>

                    <div style={{ margin: '0.5rem 0', fontSize: '0.95rem' }}>
                      <p style={{ fontWeight: 500, margin: '0 0 0.5rem' }}>{item.stem}</p>
                      {item.stem_assets && item.stem_assets.length > 0 && (
                        <div style={{ display: 'flex', gap: '0.5rem', margin: '0.5rem 0' }}>
                          {item.stem_assets.map((asset, i) => (
                            <img key={i} src={asset} alt="Stem asset" style={{ maxWidth: '100%', maxHeight: '180px', borderRadius: 4 }} />
                          ))}
                        </div>
                      )}
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.5rem' }}>
                        {Object.entries(item.options).map(([k, v]) => (
                          <div
                            key={k}
                            style={{
                              padding: '0.4rem 0.6rem',
                              background: item.answer === k ? '#dcfce7' : '#f8fafc',
                              border: item.answer === k ? '1px solid #86efac' : '1px solid #e2e8f0',
                              borderRadius: '4px',
                            }}
                          >
                            <span style={{ fontWeight: 600 }}>{k}.</span> {v}
                          </div>
                        ))}
                      </div>
                    </div>

                    {item.explanation && (
                      <div style={{ marginTop: '0.5rem', padding: '0.5rem', background: '#f8fafc', borderRadius: '4px', fontSize: '0.85rem' }}>
                        <strong>解析：</strong> {item.explanation}
                      </div>
                    )}

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '1rem', borderTop: '1px solid #f1f5f9', paddingTop: '0.5rem' }}>
                      <div style={{ fontSize: '0.85rem', color: '#64748b' }}>
                        答案: <strong style={{ color: item.answer ? '#0f172a' : '#ef4444' }}>{item.answer || '缺失'}</strong> | 来源: {item.answer_source || '无'} | 候选考点:{' '}
                        {item.suggested_knowledge_node_code || '未分类'}
                      </div>
                      <div style={{ display: 'flex', gap: '0.5rem' }}>
                        <button
                          onClick={() => {
                            setEditingItem(item);
                            setEditAnswer(item.answer || 'A');
                            setEditKnowledge(item.suggested_knowledge_node_code || '');
                            setEditExplanation(item.explanation || '');
                          }}
                          className="secondary-btn"
                          style={{
                            padding: '0.4rem 0.8rem',
                            border: '1px solid #cbd5e1',
                            borderRadius: '4px',
                            background: '#fff',
                            cursor: 'pointer',
                            fontSize: '0.85rem',
                          }}
                        >
                          修改内容/答案
                        </button>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {/* ========================================================================= */}
      {/* MODE 2: MANUAL QUESTION AUTHORING WORKSPACE */}
      {/* ========================================================================= */}
      {activeTab === 'manual' && (
        <section className="card" style={{ padding: '28px 32px' }}>
          <div style={{ marginBottom: 20 }}>
            <span className="eyebrow">MANUAL ENTRY / 自主录题</span>
            <h2 style={{ fontSize: 22, margin: '6px 0 0' }}>录入单道真题与深度解析</h2>
            <p style={{ margin: '6px 0 0', color: 'var(--muted)', fontSize: 13 }}>
              遇到好题、高频错题无需制作 PDF，直接在此录入题干、选项、答案与解析，录入后立即可刷题与生成复习卡片！
            </p>
          </div>

          <form onSubmit={handleSaveManualQuestion} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* 1. Subject & Module & Knowledge Node */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 }}>
              <div>
                <label style={{ display: 'block', fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
                  学科模块 *
                </label>
                <select
                  value={manualModule}
                  onChange={e => setManualModule(e.target.value)}
                  style={{ width: '100%', padding: '9px 12px', border: '1px solid var(--line)', borderRadius: 6, fontSize: 13, background: '#fff' }}
                >
                  <option value="图形推理">图形推理</option>
                  <option value="立体图推">立体图推</option>
                  <option value="定义判断">定义判断</option>
                  <option value="类比推理">类比推理</option>
                  <option value="逻辑判断">逻辑判断</option>
                  <option value="资料分析">资料分析</option>
                  <option value="言语理解">言语理解</option>
                  <option value="数量关系">数量关系</option>
                  <option value="政治理论">政治理论</option>
                  <option value="常识判断">常识判断</option>
                  <option value="申论">申论</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
                  归属考点 (KnowledgeNode) *
                </label>
                <select
                  value={manualNodeId}
                  onChange={e => setManualNodeId(e.target.value)}
                  style={{ width: '100%', padding: '9px 12px', border: '1px solid var(--line)', borderRadius: 6, fontSize: 13, background: '#fff' }}
                >
                  {moduleKnowledgeNodes.map(kn => (
                    <option key={kn.id} value={kn.id}>
                      {kn.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
                  试题来源备注 (可选)
                </label>
                <input
                  type="text"
                  value={manualSource}
                  onChange={e => setManualSource(e.target.value)}
                  placeholder="例如: 2026模考精选题 / 华图错题"
                  style={{ width: '100%', padding: '9px 12px', border: '1px solid var(--line)', borderRadius: 6, fontSize: 13 }}
                />
              </div>
            </div>

            {/* 2. Stem */}
            <div>
              <label style={{ display: 'block', fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
                题干内容 *
              </label>
              <textarea
                rows={3}
                value={manualStem}
                onChange={e => setManualStem(e.target.value)}
                placeholder="请粘贴或输入题干内容..."
                style={{ width: '100%', padding: '10px 12px', border: '1px solid var(--line)', borderRadius: 6, fontSize: 13 }}
              />
            </div>

            {/* 3. Options */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <label style={{ fontWeight: 600, fontSize: 13 }}>四个选项设置 *</label>
                <label style={{ fontSize: 12, color: 'var(--muted)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <input
                    type="checkbox"
                    checked={manualIsInline}
                    onChange={e => setManualIsInline(e.target.checked)}
                  />
                  选项内嵌于题面/图形中 (无需单独输入 A-D 文本)
                </label>
              </div>

              {!manualIsInline && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
                  <div>
                    <span style={{ fontSize: 12, fontWeight: 700, marginRight: 6 }}>A.</span>
                    <input
                      type="text"
                      value={manualOptA}
                      onChange={e => setManualOptA(e.target.value)}
                      placeholder="选项 A 内容"
                      style={{ width: '85%', padding: '7px 10px', border: '1px solid var(--line)', borderRadius: 4, fontSize: 13 }}
                    />
                  </div>
                  <div>
                    <span style={{ fontSize: 12, fontWeight: 700, marginRight: 6 }}>B.</span>
                    <input
                      type="text"
                      value={manualOptB}
                      onChange={e => setManualOptB(e.target.value)}
                      placeholder="选项 B 内容"
                      style={{ width: '85%', padding: '7px 10px', border: '1px solid var(--line)', borderRadius: 4, fontSize: 13 }}
                    />
                  </div>
                  <div>
                    <span style={{ fontSize: 12, fontWeight: 700, marginRight: 6 }}>C.</span>
                    <input
                      type="text"
                      value={manualOptC}
                      onChange={e => setManualOptC(e.target.value)}
                      placeholder="选项 C 内容"
                      style={{ width: '85%', padding: '7px 10px', border: '1px solid var(--line)', borderRadius: 4, fontSize: 13 }}
                    />
                  </div>
                  <div>
                    <span style={{ fontSize: 12, fontWeight: 700, marginRight: 6 }}>D.</span>
                    <input
                      type="text"
                      value={manualOptD}
                      onChange={e => setManualOptD(e.target.value)}
                      placeholder="选项 D 内容"
                      style={{ width: '85%', padding: '7px 10px', border: '1px solid var(--line)', borderRadius: 4, fontSize: 13 }}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* 4. Correct Answer Selection */}
            <div>
              <label style={{ display: 'block', fontWeight: 600, fontSize: 13, marginBottom: 8 }}>
                正确标准答案 *
              </label>
              <div style={{ display: 'flex', gap: 16 }}>
                {(['A', 'B', 'C', 'D'] as const).map(letter => {
                  const isChecked = manualAnswer === letter;
                  return (
                    <button
                      key={letter}
                      type="button"
                      onClick={() => setManualAnswer(letter)}
                      style={{
                        width: 52,
                        height: 40,
                        borderRadius: 6,
                        border: isChecked ? '2px solid var(--accent)' : '1px solid var(--line)',
                        background: isChecked ? '#eef4ed' : '#ffffff',
                        color: isChecked ? 'var(--accent)' : 'var(--ink)',
                        fontSize: 15,
                        fontWeight: isChecked ? 700 : 500,
                        cursor: 'pointer',
                      }}
                    >
                      {letter}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* 5. Explanation */}
            <div>
              <label style={{ display: 'block', fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
                标准答案与深度解析 (支持 Markdown 与公式)
              </label>
              <textarea
                rows={4}
                value={manualExplanation}
                onChange={e => setManualExplanation(e.target.value)}
                placeholder="请输入详细推导步骤、速算技巧、做题口诀与避坑说明..."
                style={{ width: '100%', padding: '10px 12px', border: '1px solid var(--line)', borderRadius: 6, fontSize: 13 }}
              />
            </div>

            {/* Submit Button */}
            <div style={{ marginTop: 10, display: 'flex', gap: 12 }}>
              <button
                type="submit"
                disabled={manualSaving || !manualStem.trim()}
                style={{
                  background: 'var(--accent)',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  padding: '10px 24px',
                  fontSize: 14,
                  fontWeight: 600,
                  cursor: manualStem.trim() ? 'pointer' : 'not-allowed',
                }}
              >
                {manualSaving ? '正在保存入库…' : '💾 保存并立即存入题库'}
              </button>
            </div>
          </form>
        </section>
      )}

      {/* Edit Single Draft Modal */}
      {editingItem && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 100,
          }}
        >
          <div
            style={{
              background: '#fff',
              padding: '1.5rem',
              borderRadius: '8px',
              maxWidth: '550px',
              width: '90%',
              boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)',
            }}
          >
            <h3 style={{ marginBottom: '1rem' }}>修改第 {editingItem.question_number} 题答案与解析</h3>
            <div style={{ marginBottom: '1rem' }}>
              <label style={{ display: 'block', fontWeight: 600, marginBottom: '0.4rem', fontSize: 13 }}>
                正确标准答案:
              </label>
              <div style={{ display: 'flex', gap: '1rem' }}>
                {['A', 'B', 'C', 'D'].map(opt => (
                  <label key={opt} style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', cursor: 'pointer' }}>
                    <input
                      type="radio"
                      name="answer"
                      value={opt}
                      checked={editAnswer === opt}
                      onChange={e => setEditAnswer(e.target.value)}
                    />
                    <span style={{ fontWeight: 600 }}>{opt}</span>
                  </label>
                ))}
              </div>
            </div>

            <div style={{ marginBottom: '1rem' }}>
              <label style={{ display: 'block', fontWeight: 600, marginBottom: '0.4rem', fontSize: 13 }}>
                归属考点选择:
              </label>
              <select
                value={editKnowledge}
                onChange={e => setEditKnowledge(e.target.value)}
                style={{ width: '100%', padding: '0.5rem', border: '1px solid #ccc', borderRadius: '4px', fontSize: 13 }}
              >
                <option value="">-- 保持原候选分类或暂未选择 --</option>
                {knowledgeNodes.map(kn => (
                  <option key={kn.id} value={kn.knowledge_node_code || kn.id}>
                    [{kn.module}] {kn.name}
                  </option>
                ))}
              </select>
            </div>

            <div style={{ marginBottom: '1rem' }}>
              <label style={{ display: 'block', fontWeight: 600, marginBottom: '0.4rem', fontSize: 13 }}>
                答案详细解析:
              </label>
              <textarea
                value={editExplanation}
                onChange={e => setEditExplanation(e.target.value)}
                rows={4}
                placeholder="请输入题目推导步骤与解析..."
                style={{ width: '100%', padding: '0.5rem', border: '1px solid #ccc', borderRadius: '4px', fontSize: 13 }}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
              <button
                type="button"
                onClick={() => setEditingItem(null)}
                style={{ padding: '0.5rem 1rem', border: '1px solid #ccc', borderRadius: '4px', background: '#fff', cursor: 'pointer' }}
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleSaveEdit}
                style={{ padding: '0.5rem 1rem', borderRadius: '4px', border: 'none', background: 'var(--accent)', color: '#fff', cursor: 'pointer', fontWeight: 600 }}
              >
                保存并就绪发布
              </button>
            </div>
          </div>
        </div>
      )}

      <footer style={{ marginTop: '2rem' }}>
        QI1 · PDF 题库导入与 AI 辅助分类
        <span>Deterministic Core + Agentic Edge · Human Review Queue · Publish Gate</span>
      </footer>
    </main>
  );
}
