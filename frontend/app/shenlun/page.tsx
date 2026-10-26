'use client';

import { useEffect, useRef, useState, useMemo } from 'react';
import Link from 'next/link';
import { TeacherFollowUpChat } from '../../lib/TeacherFollowUpChat';
import { api, DailyGoal } from '../../lib/api';
import { ShenlunDailyTaskCard } from '../../lib/ShenlunDailyTaskCard';
import { ShenlunStandardGridPaper } from '../../lib/ShenlunStandardGridPaper';
import { ShenlunGuidance, ShenlunPointTrace, GuidanceState, PointTrace } from '../../lib/ShenlunGuidance';
import './paper.css';

// ================= 类型定义 =================
type MaterialItem = { id: string; title: string; content: string };

type ShenlunMaterial = {
  id: string;
  title: string;
  exam_year: number;
  question_stem: string;
  reference_answer: string;
  max_words: number;
  materials: MaterialItem[];
};

type ShenlunMaterialSummary = {
  id: string;
  title: string;
  exam_year: number;
  question_stem: string;
  max_words: number;
  has_reference_answer: boolean;
};

type ShenlunAssessment = {
  coverage: number;
  abstraction: number;
  precision: number;
  structure: number;
  conciseness: number;
  overall_score: number;
  missing_points: string[];
  redundant_points: string[];
  weak_abstractions: string[];
  wording_issues: string[];
  next_action: string;
};

type TeacherBasis = { kind: string; ref: string; title: string; applicability?: string };

type TeacherTarget = {
  type: string;
  severity: string;
  student_span: string;
  reason: string;
  policy_ref: string;
  policy_name: string;
  next_action: { skill: string; instruction: string };
  target_key?: string;
  status?: string;
  user_quote?: string;
  user_quote_state?: string;
  material_quote?: string;
  material_quote_verified?: boolean;
  material_point?: string;
  teacher_basis?: TeacherBasis[];
  problem?: string;
  suggested_fix?: string;
  revision_note?: string;
  revised_by?: string;
  status_note?: string;
};

type TeacherDiagnosis = {
  id: string;
  teacher_name: string;
  teacher_id?: string;
  question_type: string;
  engine_version: string;
  training_targets: TeacherTarget[];
  followups: TeacherTarget[];
  strength: { point: string; basis: string }[];
  matched_policies: { policy_id: string; name: string; score: number; rule: string }[];
  similar_cases: { case_id: string; question: string; error_type: string; diagnosis: string; remedy: string }[];
  coach_note: string;
  created_at: string;
  review_status?: string;
  dismissed?: { suspicion_id: string; type: string; student_span: string; reason: string }[];
  referenced_question_cases?: Array<{
    question_id: string;
    title: string;
    question_type: string;
    core_task: string;
    key_points: string[];
    teacher_reasoning: string;
    word_limit: string;
  }>;
  teachers?: TeacherDiagnosis[];
  out_of_scope_rejected?: boolean;
  rejection_reason?: string;
};

// ================= 名师模型人格与专精设定 =================
const TEACHER_META: Record<
  string,
  {
    name: string;
    shortTitle: string;
    avatar: string;
    specialty: string;
    philosophy: string;
    themeColor: string;
    bgTint: string;
  }
> = {
  teacher_feiyang: {
    name: '飞扬老师',
    shortTitle: '实战提炼 · 省格对仗',
    avatar: '👨‍🏫',
    specialty: '紧扣审题要素 · 动宾结构概括 · 四加三对仗小标题 · 有格写没格不写',
    philosophy: '“申论是按词给分，格子就是分数；优先抓取总结句，多用动宾短语提纲挈领。”',
    themeColor: '#a04825',
    bgTint: '#fdf7f4',
  },
  teacher_zhanzhang: {
    name: '站长申论',
    shortTitle: '采分拆解 · 篇章框架',
    avatar: '🧭',
    specialty: '题型底层逻辑 · 公文框架预留 · 按答题卡占格精算 · 大格局立意',
    philosophy: '“审题定框架，按答题卡占格精算；抓住材料原词采分点，不要在细枝末节上损耗格子。”',
    themeColor: '#0f6c8c',
    bgTint: '#f2f9fb',
  },
  teacher_zhoutairan: {
    name: '周泰然老师',
    shortTitle: '逐句穿透 · 抄词控格',
    avatar: '🔍',
    specialty: '材料逐句穿透 · 抄词不抄句 · 长句变短句 · 严控考场爆格',
    philosophy: '“抄词不抄句，长句变短句；严格时序规范，精减冗余修饰语，严防考场爆格。”',
    themeColor: '#2d6a4f',
    bgTint: '#f1f8f4',
  },
  teacher_jiangmuyun: {
    name: 'W 老师·文段分析',
    shortTitle: '文段剖析 · 范围守卫',
    avatar: '📑',
    specialty: '微观句群关系 · 客观信息提炼 · 恪守文段分析边界',
    philosophy: '“专精于给定资料微观句群逻辑剖析与客观提取；严格守卫任务边界，不越界妄评大作文与公文格式。”',
    themeColor: '#63489e',
    bgTint: '#f6f2fc',
  },
};

// ================= 前缀清理与类型汉化 =================
function getFriendlyTypeName(type: string): string {
  const map: Record<string, string> = {
    missing_point: '采分盲区',
    wording: '用词表述',
    wording_issue: '用词表述',
    structure: '篇章结构',
    abstraction: '提炼概括',
    weak_abstraction: '提炼概括',
    redundant: '语言繁冗',
    VERBOSE: '语言繁冗',
    logic: '逻辑衔接',
    AI_FINDING: '要点分析',
  };
  return map[type] || '要点分析';
}

function getSeverityBadge(severity: string) {
  if (severity === 'high') {
    return <span style={{ color: '#b91c1c', fontWeight: 600, fontSize: 11 }}>● 优先改进</span>;
  }
  if (severity === 'medium') {
    return <span style={{ color: '#d97706', fontWeight: 600, fontSize: 11 }}>● 建议优化</span>;
  }
  return <span style={{ color: '#6b7280', fontSize: 11 }}>● 细节润色</span>;
}

// ================= 围绕学生作答：宽幅舞台 · 文段就地多师同屏批评与改法对比组件 =================
function MultiTeacherReviewPaper({
  answerText,
  diagnosis,
  maxWords = 300,
  onObjectionSelect,
  activeTeacherId,
  onTeacherChange,
}: {
  answerText: string;
  diagnosis: TeacherDiagnosis | null;
  maxWords?: number;
  onObjectionSelect?: (quote: string, teacherId?: string) => void;
  activeTeacherId: string;
  onTeacherChange: (teacherId: string) => void;
}) {
  // 筛选模式：'ALL' (就地同屏对比所有名师 - 默认) | 单师过滤
  const [filterTeacherId, setFilterTeacherId] = useState<string>('ALL');

  // 所有参与评阅的名师列表
  const teacherList: TeacherDiagnosis[] = useMemo(() => {
    if (!diagnosis) return [];
    if (diagnosis.teachers && diagnosis.teachers.length > 0) {
      return diagnosis.teachers;
    }
    return [diagnosis];
  }, [diagnosis]);

  // 将学生作答按段落切分
  const paragraphs = useMemo(() => {
    return (answerText || '').split(/\n+/).filter(p => p.trim().length > 0);
  }, [answerText]);

  // 为每个段落就地聚合所有名师的诊断与改法
  const paragraphInsituData = useMemo(() => {
    return paragraphs.map((pText, pIdx) => {
      const teachersForThisPara: Array<{
        teacherId: string;
        teacherName: string;
        meta: (typeof TEACHER_META)[string];
        targets: TeacherTarget[];
        strengths: Array<{ point: string; basis: string }>;
      }> = [];

      teacherList.forEach(t => {
        const tid = t.teacher_id || t.id;
        const meta = TEACHER_META[tid] || {
          name: t.teacher_name || tid,
          shortTitle: '特邀名师',
          avatar: '🎓',
          specialty: '申论要点提炼',
          philosophy: '',
          themeColor: '#a04825',
          bgTint: '#fdf7f4',
        };

        const allTargets = [...(t.training_targets || []), ...(t.followups || [])];
        const matchedTargets: TeacherTarget[] = [];
        const matchedStrengths: Array<{ point: string; basis: string }> = [];

        allTargets.forEach(tgt => {
          const quote = (tgt.user_quote || tgt.student_span || '').trim();
          if (quote && quote.length >= 3 && pText.includes(quote)) {
            matchedTargets.push(tgt);
          } else if (quote && quote.length >= 4) {
            const sub = quote.slice(0, 8);
            if (pText.includes(sub)) {
              matchedTargets.push(tgt);
            }
          }
        });

        (t.strength || []).forEach(st => {
          const pt = (st.point || '').trim();
          if (pt && pt.length >= 4 && pText.includes(pt.slice(0, 6))) {
            matchedStrengths.push(st);
          }
        });

        // 若本段命中该老师的目标，或全篇只有一段且该老师有目标
        if (matchedTargets.length > 0 || matchedStrengths.length > 0 || (paragraphs.length === 1 && allTargets.length > 0)) {
          teachersForThisPara.push({
            teacherId: tid,
            teacherName: meta.name,
            meta,
            targets: matchedTargets.length > 0 ? matchedTargets : (paragraphs.length === 1 ? allTargets : []),
            strengths: matchedStrengths,
          });
        }
      });

      return {
        text: pText,
        pIdx,
        teachers: teachersForThisPara,
      };
    });
  }, [paragraphs, teacherList]);

  // 高亮片段（供全真 25 列红格纸展示）
  const gridHighlights = useMemo(() => {
    const list: Array<{ quote: string; type: 'target' | 'strength'; key?: string }> = [];
    teacherList.forEach(t => {
      [...(t.training_targets || []), ...(t.followups || [])].forEach(tgt => {
        const q = (tgt.user_quote || tgt.student_span || '').trim();
        if (q && q.length >= 2) {
          list.push({ quote: q, type: 'target', key: tgt.target_key || tgt.problem });
        }
      });
      (t.strength || []).forEach(st => {
        const pt = (st.point || '').trim();
        if (pt && pt.length >= 3) {
          list.push({ quote: pt.slice(0, 8), type: 'strength' });
        }
      });
    });
    return list;
  }, [teacherList]);

  return (
    <div className="teacher-model-panel" style={{ width: '100%' }}>
      {/* 顶部标题栏与模式切换 */}
      <div className="teacher-panel-head">
        <div>
          <strong style={{ fontSize: 18, color: '#a04825' }}>
            👨‍🏫 考生作答文段 · 多名师就地同屏会诊与改法对照
          </strong>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: '#555' }}>
            宽幅全景展开：所有名师意见直接依附在每个作答文段下方并列对比，绝不挤压侧边，原句与改法就地对照。
          </p>
        </div>

        {/* 过滤切换标签 */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: 13, color: '#666', fontWeight: 500 }}>名师视角切换：</span>
          <button
            type="button"
            className={`bank-filter-chip ${filterTeacherId === 'ALL' ? 'active' : ''}`}
            onClick={() => setFilterTeacherId('ALL')}
          >
            ✨ 全部名师同屏就地对比 ({teacherList.length}位)
          </button>
          {teacherList.map(t => {
            const tid = t.teacher_id || t.id;
            const meta = TEACHER_META[tid] || { name: t.teacher_name, avatar: '🎓' };
            return (
              <button
                key={tid}
                type="button"
                className={`bank-filter-chip ${filterTeacherId === tid ? 'active' : ''}`}
                onClick={() => {
                  setFilterTeacherId(tid);
                  onTeacherChange(tid);
                }}
              >
                {meta.avatar} {meta.name}
              </button>
            );
          })}
        </div>
      </div>

      {/* 汇总各名师的宏观指导心法胶囊卡 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14, marginBottom: 22 }}>
        {teacherList.map(t => {
          const tid = t.teacher_id || t.id;
          const meta = TEACHER_META[tid] || {
            name: t.teacher_name,
            shortTitle: '申论导师',
            avatar: '🎓',
            themeColor: '#a04825',
            specialty: '',
            philosophy: '',
          };
          if (filterTeacherId !== 'ALL' && filterTeacherId !== tid) return null;

          return (
            <div
              key={tid}
              style={{
                background: '#fff',
                border: `1.5px solid ${meta.themeColor}33`,
                borderLeft: `5px solid ${meta.themeColor}`,
                borderRadius: 6,
                padding: '12px 16px',
                fontSize: 13,
                boxShadow: '0 2px 6px rgba(0,0,0,0.02)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <span style={{ fontSize: 18 }}>{meta.avatar}</span>
                <strong style={{ color: meta.themeColor, fontSize: 14 }}>{meta.name}</strong>
                <span style={{ color: '#888', fontSize: 11 }}>({meta.shortTitle})</span>
              </div>
              <div style={{ color: '#444', lineHeight: 1.6 }}>
                {t.out_of_scope_rejected ? (
                  <span style={{ color: '#831843' }}>{t.coach_note || '本题超出专属文段分析边界，不强行评阅。'}</span>
                ) : (
                  <span><strong>名师总评：</strong>{t.coach_note || meta.philosophy}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* 全真 25 列红格纸展示（供查看排版与占格） */}
      <details style={{ marginBottom: 24 }} open={false}>
        <summary style={{ cursor: 'pointer', fontSize: 14, color: '#a04825', fontWeight: 600, padding: '10px 16px', background: '#faf6f0', borderRadius: 6, border: '1px solid #ebd9c8' }}>
          📑 点击展开/收起：考生作答全真 25 列红格答题纸版面（占格与标尺）
        </summary>
        <div style={{ marginTop: 14 }}>
          <ShenlunStandardGridPaper
            text={answerText}
            maxWords={maxWords}
            highlights={gridHighlights}
            title="公务员录用考试 · 申论作答卷面（全真 25 列红格纸）"
            subtitle="考生作答实测排版"
          />
        </div>
      </details>

      {/* ================= 核心：文段就地呈现多名师对比 ================= */}
      <div className="insitu-paragraphs-container">
        {paragraphInsituData.map(pa => {
          const teachersToShow = pa.teachers.filter(
            t => filterTeacherId === 'ALL' || t.teacherId === filterTeacherId
          );

          const allStrengths = teachersToShow.flatMap(t =>
            t.strengths.map(s => ({ ...s, teacherName: t.teacherName, themeColor: t.meta.themeColor }))
          );

          return (
            <div key={pa.pIdx} className="insitu-paragraph-block">
              {/* 段落信息抬头 */}
              <div className="insitu-paragraph-header">
                <div className="insitu-paragraph-tag">
                  <span>第 {pa.pIdx + 1} 自然段</span>
                  <span style={{ fontSize: 12, color: '#666', fontWeight: 400 }}>
                    （字数统计：{pa.text.length} 字）
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <span style={{ fontSize: 12, color: '#a04825', background: '#faeee9', border: '1px solid #e3b4a8', padding: '3px 10px', borderRadius: 4, fontWeight: 500 }}>
                    {teachersToShow.length} 位名师出具就地诊断
                  </span>
                </div>
              </div>

              {/* 学生段落原文（宽幅舒适展示） */}
              <div className="insitu-paragraph-text">
                {pa.text}
              </div>

              {/* 紧贴该段下方的【多名师就地同屏批评与改法对比卡】 */}
              <div className="insitu-consilium-panel">
                {/* 肯定亮点 */}
                {allStrengths.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 14 }}>
                    {allStrengths.map((st, sIdx) => (
                      <div
                        key={sIdx}
                        style={{
                          background: '#f2f8f4',
                          border: '1px solid #bbf7d0',
                          borderLeft: '4px solid #16a34a',
                          borderRadius: 4,
                          padding: '8px 14px',
                          fontSize: 13,
                          color: '#166534',
                          flex: 1,
                          minWidth: 260,
                        }}
                      >
                        <strong>✓ 【{st.teacherName}】采分点到位：</strong>
                        <span>{st.point}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* 各名师诊断与改法对比 */}
                <div className="insitu-consilium-title">
                  <span>⚖️ 多名师对本段诊断批评与建议改法对照：</span>
                  <span style={{ fontSize: 12, color: '#777', fontWeight: 400 }}>
                    直接对比不同名师对该段的修改思路
                  </span>
                </div>

                {teachersToShow.length === 0 ? (
                  <p style={{ margin: 0, fontSize: 13, color: '#888', fontStyle: 'italic' }}>
                    本段表述较为平稳，所选名师暂无突出问题标记。
                  </p>
                ) : (
                  <div className="insitu-teachers-grid">
                    {teachersToShow.map(tData => (
                      <div
                        key={tData.teacherId}
                        className="insitu-teacher-card"
                        style={{ borderTop: `4px solid ${tData.meta.themeColor}` }}
                      >
                        {/* 老师名头 */}
                        <div className="insitu-teacher-card-head">
                          <span style={{ fontSize: 20 }}>{tData.meta.avatar}</span>
                          <div>
                            <strong className="insitu-teacher-name" style={{ color: tData.meta.themeColor, fontSize: 14 }}>
                              {tData.meta.name}
                            </strong>
                            <div className="insitu-teacher-role">{tData.meta.shortTitle}</div>
                          </div>
                        </div>

                        {/* 该老师对本段的诊断与改法 */}
                        {tData.targets.map((tgt, tIdx) => {
                          const friendlyType = getFriendlyTypeName(tgt.type);
                          const problem = tgt.problem || tgt.reason;
                          const fix = tgt.suggested_fix || tgt.next_action?.instruction;

                          return (
                            <div key={tIdx} style={{ marginBottom: 14 }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                                <span className="comment-tag" style={{ color: tData.meta.themeColor, background: `${tData.meta.themeColor}15`, fontSize: 11 }}>
                                  {friendlyType}
                                </span>
                                {getSeverityBadge(tgt.severity)}
                              </div>

                              <div className="insitu-critique-problem">
                                <strong>批评诊断：</strong>{problem}
                              </div>

                              {fix && (
                                <div className="insitu-critique-fix" style={{ color: tData.meta.themeColor, borderLeftColor: tData.meta.themeColor }}>
                                  <strong>【{tData.meta.name}建议改法】：</strong>
                                  <div style={{ marginTop: 2 }}>{fix}</div>
                                </div>
                              )}

                              {tgt.material_quote && (
                                <div className="insitu-critique-evidence">
                                  <strong>材料线索：</strong>{tgt.material_quote}
                                  {tgt.material_point && <span style={{ color: '#555' }}>（{tgt.material_point}）</span>}
                                </div>
                              )}

                              {tgt.teacher_basis && tgt.teacher_basis.length > 0 && (
                                <div className="insitu-critique-basis">
                                  <strong>依据方法：</strong>{tgt.teacher_basis.map(b => b.title).join('、')}
                                </div>
                              )}
                            </div>
                          );
                        })}

                        {/* 追问按钮 */}
                        <button
                          type="button"
                          className="insitu-followup-btn"
                          onClick={() => {
                            const q = tData.targets[0]?.user_quote || pa.text;
                            onTeacherChange(tData.teacherId);
                            onObjectionSelect?.(q, tData.teacherId);
                          }}
                        >
                          💬 针对此段向【{tData.meta.name}】追问探讨
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ================= 独立全维深度解析阅读界面组件 (Dedicated In-Depth Reading View) =================
function DedicatedReadingView({
  material,
  teacherDiagnosis,
  onBack,
}: {
  material: ShenlunMaterial;
  teacherDiagnosis: TeacherDiagnosis | null;
  onBack: () => void;
}) {
  const [copied, setCopied] = useState(false);

  function copyAnswer() {
    if (!material.reference_answer) return;
    navigator.clipboard.writeText(material.reference_answer).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  const teacherList = teacherDiagnosis?.teachers || (teacherDiagnosis ? [teacherDiagnosis] : []);

  // 结构化解析：从参考答案智能解析出踩分要点列表
  const parsedScoringPoints = useMemo(() => {
    const raw = material.reference_answer || '';
    const lines = raw.split('\n').map(l => l.trim()).filter(Boolean);
    const points: Array<{ title: string; detail: string; category?: string }> = [];

    let currentCat = '核心要点';
    lines.forEach(line => {
      if (line.startsWith('一、') || line.startsWith('二、') || line.startsWith('三、') || line.includes('【主要问题】') || line.includes('【解决措施】')) {
        currentCat = line;
      } else {
        const cleaned = line.replace(/^\d+[、.．]\s*/, '').replace(/^[（(]\d+[)）]\s*/, '');
        const splitIdx = cleaned.indexOf('：');
        if (splitIdx > 0 && splitIdx < 15) {
          points.push({
            category: currentCat,
            title: cleaned.slice(0, splitIdx),
            detail: cleaned.slice(splitIdx + 1),
          });
        } else {
          points.push({
            category: currentCat,
            title: `踩分要点 ${points.length + 1}`,
            detail: cleaned,
          });
        }
      }
    });

    return points;
  }, [material.reference_answer]);

  return (
    <div className="shenlun-dedicated-reading-view">
      {/* 吸顶操作栏 */}
      <div className="reading-view-top-bar">
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <button type="button" className="reading-back-btn" onClick={onBack}>
            ← 返回实战作答/卷面批改
          </button>
          <strong style={{ fontSize: 16, color: '#222' }}>
            📖 申论真题试题全维深度解析 (独立研读界面)
          </strong>
        </div>

        <div style={{ display: 'flex', gap: 10 }}>
          <button
            type="button"
            className="shenlun-action-btn"
            style={{ fontSize: 12 }}
            onClick={copyAnswer}
          >
            {copied ? '✓ 已复制参考答案' : '📋 复制权威参考答案'}
          </button>
        </div>
      </div>

      {/* 题头元信息 */}
      <div style={{ textAlign: 'center', margin: '20px 0 28px' }}>
        <div style={{ fontSize: 13, color: '#8a6d3b', fontWeight: 600, letterSpacing: 1 }}>
          {material.exam_year} 年真题 · 官方标准采分深度剖析
        </div>
        <h1 className="reading-hero-title">{material.title}</h1>
        <div className="reading-hero-meta">
          <span>限字：不超过 <strong>{material.max_words}</strong> 字</span>
          <span>给定资料：{material.materials.length} 则</span>
          <span>排版制式：国考/省考标准 25 列红格规范</span>
        </div>
      </div>

      {/* 模块一：题目要求与审题深度透析 */}
      <section className="reading-card-section" aria-label="审题深度透析">
        <div className="reading-section-header">
          <h3>📌 模块一：【审题透析与作答逻辑建模】</h3>
          <span>审题先行 · 明确五大要素与分值结构</span>
        </div>

        <div style={{ background: '#faf6f0', padding: '18px 22px', borderRadius: 6, borderLeft: '4px solid #a04825', marginBottom: 18 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#a04825', marginBottom: 8 }}>
            【作答题目原文】：
          </div>
          <p style={{ margin: 0, fontSize: 16, lineHeight: 1.8, color: '#222', fontWeight: 500 }}>
            {material.question_stem}
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 14, fontFamily: 'system-ui, sans-serif' }}>
          <div style={{ background: '#f8f6f0', padding: 14, borderRadius: 6, border: '1px solid #ebd9c8' }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#a04825', marginBottom: 4 }}>
              🎯 作答任务要素与设问动词
            </div>
            <div style={{ fontSize: 13, color: '#444', lineHeight: 1.6 }}>
              聚焦题目设问核心动词，严格围绕材料提取客观事实，分清主要问题与应对解决措施两大维度。
            </div>
          </div>
          <div style={{ background: '#f8f6f0', padding: 14, borderRadius: 6, border: '1px solid #ebd9c8' }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#a04825', marginBottom: 4 }}>
              📏 篇幅字数配比精算
            </div>
            <div style={{ fontSize: 13, color: '#444', lineHeight: 1.6 }}>
              上限 {material.max_words} 字。问题与对策字数配比建议约为 1:2 或 1:3（问题约 80-90 字，对策约 180-210 字），严防超格。
            </div>
          </div>
          <div style={{ background: '#f8f6f0', padding: 14, borderRadius: 6, border: '1px solid #ebd9c8' }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#a04825', marginBottom: 4 }}>
              ⚠ 考场常见失分陷阱
            </div>
            <div style={{ fontSize: 13, color: '#444', lineHeight: 1.6 }}>
              忌抄材料背景大空话；忌将个案事例（如某人某数字）当措施；忌自撰空泛对策脱离材料。
            </div>
          </div>
        </div>
      </section>

      {/* 模块二：给定资料逐则逐段深度剖析与采分点线索追踪 */}
      <section className="reading-card-section" aria-label="资料逐段深度剖析">
        <div className="reading-section-header">
          <h3>📑 模块二：【给定资料逐则段落深度剖析与采分点线索追踪】</h3>
          <span>逐段研读 · 段旨归纳 · 核心采分词高亮与干扰信息剔除</span>
        </div>

        <div>
          {material.materials.map((m, mIdx) => (
            <div key={m.id} style={{ marginBottom: 30 }}>
              <h4 style={{ fontSize: 17, fontWeight: 700, color: '#a04825', paddingLeft: 10, borderLeft: '4px solid #a04825', margin: '0 0 16px' }}>
                {m.title}
              </h4>

              {m.content.split(/\n\s*\n/).filter(p => p.trim()).map((paragraph, pIdx) => {
                return (
                  <div key={pIdx} className="material-paragraph-card">
                    <div className="material-paragraph-head">
                      <span>资料 {mIdx + 1} · 第 {pIdx + 1} 自然段</span>
                      <span style={{ fontSize: 11, color: '#777' }}>段落长：{paragraph.length} 字</span>
                    </div>

                    <div className="material-paragraph-body">
                      {paragraph}
                    </div>

                    <div className="material-paragraph-analysis-box">
                      <div style={{ fontWeight: 700, color: '#0f6c8c', marginBottom: 4 }}>
                        🔍 本段深度剖析与采分归纳：
                      </div>
                      <div style={{ color: '#333' }}>
                        {pIdx === 0
                          ? '【段落功能：背景与宏观铺垫】本段主要交代政策与推进背景。答小题时不抄背景总括句，避免占用宝贵格子，重点关注后文转折出现的具体矛盾或首创做法。'
                          : pIdx === 1
                          ? '【段落功能：核心痛点与问题呈现】本段包含核心采分信息，重点提取主体困境、群众反映突出的矛盾词。修饰性副词与具体个案细节需在作答时予以概括提炼。'
                          : '【段落功能：对策落地与机制创新】包含关键做法要点，提取其中的机关实务动词，形成“动宾短语+具体举措”的标准表达。'}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </section>

      {/* 模块三：采分点清单与评分赋分细则表 */}
      <section className="reading-card-section" aria-label="采分点赋分细则">
        <div className="reading-section-header">
          <h3>📊 模块三：【采分点清单与评分赋分细则表】</h3>
          <span>踩点给分 · 关键词赋分表 · 扣分规约全解</span>
        </div>

        <table className="scoring-rubric-table">
          <thead>
            <tr>
              <th style={{ width: '15%' }}>类别</th>
              <th style={{ width: '25%' }}>采分要点小标题</th>
              <th style={{ width: '45%' }}>核心采分词与踩点细则（命中即得分）</th>
              <th style={{ width: '15%' }}>分值预估</th>
            </tr>
          </thead>
          <tbody>
            {parsedScoringPoints.map((pt, idx) => (
              <tr key={idx}>
                <td style={{ fontWeight: 600, color: '#a04825' }}>{pt.category}</td>
                <td style={{ fontWeight: 700 }}>{pt.title}</td>
                <td style={{ color: '#2c2c2c', lineHeight: 1.7 }}>{pt.detail}</td>
                <td style={{ color: '#166534', fontWeight: 600 }}>约 2~3 分</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div style={{ background: '#faf8f5', padding: '12px 16px', borderRadius: 6, border: '1px solid #ebd9c8', marginTop: 14, fontSize: 13, color: '#555', lineHeight: 1.7 }}>
          <strong>📋 卷面与规范扣分标准：</strong>
          <div>1. 错别字：每 3 个错别字扣 1 分，最多扣 2 分；</div>
          <div>2. 篇幅超限：超出规定字数或答题卡方格范围的文字不予扫描评分，且酌情扣 1~2 分；不足规定字数达 2 行以上的，每少 50 字扣 1 分；</div>
          <div>3. 结构条理：未分条列项、通篇一整段无标号者，扣 2 分结构条理分。</div>
        </div>
      </section>

      {/* 模块四：官方权威示范作答（全真 25 列红格纸展示） */}
      <section className="reading-card-section" aria-label="权威示范答案红格版">
        <div className="reading-section-header">
          <h3>🖋 模块四：【官方权威参考答案（全真 25 列红格纸版）】</h3>
          <span>真实答题卡排版 · 段首空两格 · 标点独占一格 · 标尺对照</span>
        </div>

        <div style={{ marginBottom: 18 }}>
          <ShenlunStandardGridPaper
            text={material.reference_answer || '暂无详细参考解析'}
            maxWords={material.max_words}
            title="公务员录用考试 · 官方示范作答（标准 25 列红格纸版本）"
            subtitle="标准答题卡排版"
          />
        </div>

        <div style={{ background: '#faf9f6', border: '1px solid #ebd9c8', borderRadius: 6, padding: '18px 22px' }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#a04825', marginBottom: 8 }}>
            【参考答案文本排印版】：
          </div>
          <div style={{ whiteSpace: 'pre-wrap', fontSize: 15, lineHeight: 2.0, color: '#2b2b2b' }}>
            {material.reference_answer || '暂无详细参考解析'}
          </div>
        </div>
      </section>

      {/* 模块五：四大名师破题思路与实战心法深度比对 */}
      {teacherList.length > 0 && (
        <section className="reading-card-section" aria-label="名师思路对比">
          <div className="reading-section-header">
            <h3>💡 模块五：【四大名师破题思路与实战心法深度比对】</h3>
            <span>横向比对名师破题视角 · 融会贯通提炼要点</span>
          </div>

          <div className="teacher-insights-grid">
            {teacherList.map(t => {
              const meta = TEACHER_META[t.teacher_id || ''] || {
                name: t.teacher_name,
                avatar: '🎓',
                themeColor: '#a04825',
                specialty: '申论实战解法',
                philosophy: '',
              };

              return (
                <div key={t.teacher_id || t.id} className="teacher-insight-card" style={{ borderTop: `3px solid ${meta.themeColor}` }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 22 }}>{meta.avatar}</span>
                    <div>
                      <strong style={{ fontSize: 14, color: meta.themeColor }}>{meta.name}</strong>
                      <div style={{ fontSize: 11, color: '#777' }}>{meta.specialty}</div>
                    </div>
                  </div>

                  <p style={{ margin: '6px 0 0', fontSize: 12, color: '#555', fontStyle: 'italic' }}>
                    {meta.philosophy}
                  </p>

                  <div style={{ marginTop: 8, fontSize: 13, lineHeight: 1.6, color: '#222' }}>
                    <strong>破题核心点拨：</strong>
                    {t.coach_note || '动笔前精算字数配额，提炼总结句作为首句主旨，动宾短语提纲挈领。'}
                  </div>

                  {t.matched_policies && t.matched_policies.length > 0 && (
                    <div style={{ marginTop: 8, fontSize: 11, color: '#777' }}>
                      <strong>方法论依据：</strong>
                      {t.matched_policies.map(p => p.name).slice(0, 3).join('、')}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* 底部返回操作 */}
      <div style={{ textAlign: 'center', margin: '40px 0 20px' }}>
        <button type="button" className="reading-back-btn" style={{ fontSize: 15, padding: '10px 28px' }} onClick={onBack}>
          ✍️ 返回实战作答/卷面批改工作台
        </button>
      </div>
    </div>
  );
}

// ================= 主页面组件 =================
export default function ShenlunPage() {
  const currentSessionId = useRef<string | null>(null);
  const diagnosisTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const [dailyGoal, setDailyGoal] = useState<DailyGoal | null>(null);
  const [session, setSession] = useState<{
    id: string;
    material: ShenlunMaterial;
    status: string;
    first_draft: string | null;
    final_answer: string | null;
    revision_diff: string | null;
    notes: Record<string, string>;
  } | null>(null);

  const [notes, setNotes] = useState({
    problem: '',
    cause: '',
    policy: '',
    example: '',
  });

  const [draftText, setDraftText] = useState('');
  const [busy, setBusy] = useState(false);
  const [assessmentPending, setAssessmentPending] = useState(false);
  const [error, setError] = useState('');
  const [savedMsg, setSavedMsg] = useState('');
  const [assessment, setAssessment] = useState<ShenlunAssessment | null>(null);
  const [assessmentError, setAssessmentError] = useState('');
  const [guidance, setGuidance] = useState<GuidanceState | null>(null);
  const [pointTrace, setPointTrace] = useState<PointTrace | null>(null);
  const [teacherDiagnosis, setTeacherDiagnosis] = useState<TeacherDiagnosis | null>(null);
  const [objectionQuote, setObjectionQuote] = useState<string | null>(null);

  // 核心功能模式：'workbench' (作答与批改) | 'reading' (独立全维深度解析阅读界面)
  const [viewMode, setViewMode] = useState<'workbench' | 'reading'>('workbench');

  // 未提交时作答纸视图模式：'editor' (快速文本编辑) | 'grid' (25列红格排版预览)
  const [practiceGridMode, setPracticeGridMode] = useState<'editor' | 'grid'>('editor');

  // 当前激活的名师模型 ID
  const [activeTeacherId, setActiveTeacherId] = useState<string>('teacher_feiyang');

  // 浮层/抽屉：给定资料对照抽屉（复盘时展开查看材料）
  const [showMaterialsDrawer, setShowMaterialsDrawer] = useState(false);

  // 独立入口 1：本题参考解析抽屉（保持对现有用例兼容）
  const [showExplanationDrawer, setShowExplanationDrawer] = useState(false);

  // 独立入口 2：申论题库弹窗
  const [showBankModal, setShowBankModal] = useState(false);
  const [bankList, setBankList] = useState<ShenlunMaterialSummary[]>([]);
  const [bankLoading, setBankLoading] = useState(false);
  const [selectedYear, setSelectedYear] = useState<number | 'ALL'>('ALL');
  const [bankPreviewItem, setBankPreviewItem] = useState<ShenlunMaterial | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // 轮询语义审查
  function pollTeacherDiagnosis(sessionId: string) {
    if (diagnosisTimer.current) clearInterval(diagnosisTimer.current);
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (currentSessionId.current !== sessionId || attempts > 18) {
        clearInterval(timer);
        return;
      }
      api<{ diagnosis: TeacherDiagnosis | null }>(`/shenlun/teacher/${sessionId}`)
        .then(fb => {
          if (currentSessionId.current !== sessionId || !fb.diagnosis) return;
          setTeacherDiagnosis(fb.diagnosis);
          const statuses = (fb.diagnosis.teachers || [fb.diagnosis]).map(d => d.review_status);
          if (statuses.length > 0 && statuses.every(s => s && s !== 'pending')) {
            clearInterval(timer);
          }
        })
        .catch(() => {});
    }, 8000);
    diagnosisTimer.current = timer;
  }

  async function loadDailyGoal() {
    try {
      setDailyGoal(await api<DailyGoal>('/daily-goal'));
    } catch {}
  }

  async function startSession(materialId?: string, nextTask = false) {
    setBusy(true);
    setError('');
    try {
      const res = await api<any>('/shenlun/session', {
        material_id: materialId,
        daily: !materialId,
        next_task: nextTask,
      });
      currentSessionId.current = res.id;
      if (diagnosisTimer.current) clearInterval(diagnosisTimer.current);

      setSession(res);
      setGuidance(res.guidance || null);
      setPointTrace(res.point_trace || null);
      setAssessment(res.assessment || null);
      setAssessmentError('');
      setSavedMsg('');
      setTeacherDiagnosis(res.teacher_diagnosis || null);
      if (res.teacher_diagnosis?.teachers?.[0]?.teacher_id) {
        setActiveTeacherId(res.teacher_diagnosis.teachers[0].teacher_id);
      }
      setDraftText(res.final_answer || res.first_draft || '');
      setNotes({
        problem: res.notes?.problem || '',
        cause: res.notes?.cause || '',
        policy: res.notes?.policy || '',
        example: res.notes?.example || '',
      });
      await loadDailyGoal();
    } catch (err: any) {
      setError(err.message || '加载申论试题失败');
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void startSession(new URLSearchParams(window.location.search).get('material') || undefined);
    return () => {
      currentSessionId.current = null;
      if (diagnosisTimer.current) clearInterval(diagnosisTimer.current);
    };
  }, []);

  async function saveDraft() {
    if (!session || busy) return;
    setBusy(true);
    setSavedMsg('');
    try {
      await api('/shenlun/draft', {
        session_id: session.id,
        draft_text: draftText,
        notes,
      });
      setSavedMsg('批注与初稿已保存到本地');
      setSession(prev => (prev ? { ...prev, first_draft: prev.first_draft || draftText } : null));
    } catch (err: any) {
      setError(err.message || '保存草稿失败');
    } finally {
      setBusy(false);
    }
  }

  async function submitFinal() {
    if (!session || !draftText.trim() || busy) return;
    setBusy(true);
    setAssessmentPending(true);
    setError('');
    setSavedMsg('');
    try {
      const res = await api<any>('/shenlun/submit', {
        session_id: session.id,
        final_answer: draftText,
      });
      setAssessment(res.assessment || null);
      setGuidance(res.guidance || null);
      setPointTrace(res.point_trace || null);
      setAssessmentError(res.assessment_error || '');
      if (res.teacher_diagnosis) {
        setTeacherDiagnosis(res.teacher_diagnosis);
        if (res.teacher_diagnosis.teachers?.[0]?.teacher_id) {
          setActiveTeacherId(res.teacher_diagnosis.teachers[0].teacher_id);
        }
      }
      setSession(prev =>
        prev
          ? {
              ...prev,
              status: 'completed',
              first_draft: res.first_draft,
              final_answer: res.final_answer,
              revision_diff: res.revision_diff,
              material: { ...prev.material, reference_answer: res.reference_answer || '' },
            }
          : null
      );
      pollTeacherDiagnosis(session.id);
    } catch (err: any) {
      setError(err.message || '提交评估失败');
      if (session?.id) {
        try {
          const fb = await api<{ diagnosis: TeacherDiagnosis | null }>(`/shenlun/teacher/${session.id}`);
          if (fb.diagnosis) {
            setTeacherDiagnosis(fb.diagnosis);
            if (fb.diagnosis.teachers?.[0]?.teacher_id) {
              setActiveTeacherId(fb.diagnosis.teachers[0].teacher_id);
            }
          }
        } catch {}
        pollTeacherDiagnosis(session.id);
      }
    } finally {
      await loadDailyGoal();
      setBusy(false);
      setAssessmentPending(false);
    }
  }

  // 加载题库列表
  async function openBankModal() {
    setShowBankModal(true);
    if (bankList.length > 0) return;
    setBankLoading(true);
    try {
      const res = await api<{ materials: ShenlunMaterialSummary[] }>('/shenlun/materials');
      setBankList(res.materials);
    } catch (e: any) {
      setError(e.message || '加载题库失败');
    } finally {
      setBankLoading(false);
    }
  }

  // 预览某题及其官方解析
  async function loadPreviewItem(id: string) {
    setPreviewLoading(true);
    try {
      const detail = await api<ShenlunMaterial>(`/shenlun/materials/${id}`);
      setBankPreviewItem(detail);
    } catch (e: any) {
      setError(e.message || '获取试题详情失败');
    } finally {
      setPreviewLoading(false);
    }
  }

  // 提取可用年份
  const availableYears = useMemo(() => {
    const s = new Set<number>();
    bankList.forEach(m => s.add(m.exam_year));
    return Array.from(s).sort((a, b) => b - a);
  }, [bankList]);

  // 过滤题库列表
  const filteredBankList = useMemo(() => {
    if (selectedYear === 'ALL') return bankList;
    return bankList.filter(m => m.exam_year === selectedYear);
  }, [bankList, selectedYear]);

  const wordCount = draftText.trim().length;
  const isCompleted = session?.status === 'completed';

  // 若处于独立全维深度解析阅读模式，直接渲染专属阅读视图
  if (viewMode === 'reading' && session?.final_answer) {
    return (
      <main className="shenlun-workbench">
        <DedicatedReadingView
          material={session.material}
          teacherDiagnosis={teacherDiagnosis}
          onBack={() => setViewMode('workbench')}
        />
      </main>
    );
  }

  return (
    <main className="shenlun-workbench">
      {/* 顶栏：导航与独立入口 */}
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18, flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <Link href="/dashboard" className="brand" style={{ fontSize: 16 }}>
            <span className="brand-icon">申</span>公考 Learning OS · 申论工作台
          </Link>
          <nav>
            <Link href="/dashboard">学习概览</Link>
            <Link href="/framework">知识框架</Link>
            <Link href="/quiz">行测训练</Link>
            <Link href="/review">到期复习</Link>
            <Link href="/exam">全真模考</Link>
            <Link href="/shenlun" className="active">申论工作台</Link>
            <Link href="/importer">题库导入</Link>
          <Link href="/settings">设置</Link></nav>
        </div>

        {/* 核心单独入口 */}
        <div className="shenlun-header-actions">
          {/* 模式切换：实战作答 vs 独立全维深度解析阅读 */}
          <button
            type="button"
            className={`shenlun-action-btn ${viewMode === 'reading' ? 'primary' : ''}`}
            onClick={() => setViewMode('reading')}
            disabled={!session?.final_answer}
            title="进入宽幅沉浸式独立阅读界面，完整研读审题透析、资料逐段剖析、评分细则与名师心法"
          >
            📖 试题全维深度解析 (独立研读界面)
          </button>
          <button
            type="button"
            className="shenlun-action-btn"
            onClick={openBankModal}
            title="浏览江苏省考历年申论真题并查阅完整解析"
          >
            📚 申论真题库
          </button>
          <button
            type="button"
            className="shenlun-action-btn primary"
            onClick={() => setShowExplanationDrawer(true)}
            disabled={!session?.final_answer}
            title="查看当前题目的官方权威参考答案与采分要点"
          >
            💡 本题参考解析
          </button>
        </div>
      </header>

      {/* 简明标题区 */}
      <div className="intro" style={{ margin: '8px 0 16px' }}>
        <h1 style={{ fontSize: 24, margin: '0 0 6px' }}>材料定位、要点提炼与名师批改</h1>
        <p style={{ margin: 0, color: '#666', fontSize: 13 }}>
          精读给定资料，在标准 25 列红格答题卡中限时书写。提交后各名师就地同屏对各文段批评与改法对照，点击右上角可进入全维独立深度解析阅读。
        </p>
      </div>

      {error && <div role="alert" className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {/* 每日任务 */}
      {dailyGoal?.shenlun && (
        <ShenlunDailyTaskCard
          task={dailyGoal.shenlun}
          workbench
          busy={busy}
          onNext={isCompleted ? () => void startSession(undefined, true) : undefined}
        />
      )}

      {/* =========================================================================
          核心工作台：区分【已提交复盘期（全幅宽屏主视图）】与【未提交作答期（平衡分栏）】
          彻底解决“作答文段挤在边上一点点”的痛点！
         ========================================================================= */}
      {session && isCompleted ? (
        /* ================= 批改复盘全幅主视图：1240px 居中宽幅舞台，彻底不再挤在侧边！ ================= */
        <div className="shenlun-review-workspace">
          {guidance && <ShenlunGuidance key={session.id} sessionId={session.id} state={guidance} onChange={setGuidance} />}
          {pointTrace && <ShenlunPointTrace report={pointTrace} sessionId={session.id} onChange={setPointTrace} />}
          {session.revision_diff && <details><summary>初稿与终稿 Revision Diff</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{session.revision_diff}</pre></details>}
          {/* 顶栏控制条：评分与核心操作 */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#fff', border: '1px solid #ded8cb', borderRadius: 8, padding: '14px 22px', flexWrap: 'wrap', gap: 12, boxShadow: '0 2px 8px rgba(0,0,0,0.03)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <strong style={{ fontSize: 17, color: '#a04825' }}>
                📝 {session.material.title} · 名师就地卷面会诊
              </strong>
              <span style={{ fontSize: 13, color: '#666' }}>
                篇幅限制：{session.material.max_words} 字 · 考生实际作答：{(session.final_answer || draftText).length} 字
              </span>
            </div>

            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <button
                type="button"
                className="shenlun-action-btn"
                style={{ fontSize: 12 }}
                onClick={() => setShowMaterialsDrawer(true)}
                title="展开题本原始给定资料进行对照比对"
              >
                📑 对照给定资料 (展开抽屉)
              </button>
              <button
                type="button"
                className="shenlun-action-btn primary"
                style={{ fontSize: 12 }}
                onClick={() => setViewMode('reading')}
                title="进入全维深度解析独立阅读界面"
              >
                📖 试题全维深度解析 (独立研读界面)
              </button>
              <button
                type="button"
                className="secondary"
                style={{ fontSize: 12, padding: '6px 14px' }}
                onClick={() => setSession(prev => prev ? { ...prev, status: 'active' } : null)}
              >
                ✏ 重新修改作答
              </button>
            </div>
          </div>

          {/* 五维评分胶囊条 */}
          {assessment && (
            <div className="shenlun-score-bar-container" style={{ margin: '4px 0 10px' }}>
              <div className="overall-score-pill">
                <span style={{ fontSize: 13, color: '#666' }}>综合得分</span>
                <strong>{assessment.overall_score}</strong>
                <span style={{ fontSize: 12, color: '#999' }}>分</span>
              </div>
              <div className="dimensions-capsules">
                <div className="dim-capsule">
                  <span>要点覆盖</span>
                  <strong>{Math.round(assessment.coverage * 100)}%</strong>
                </div>
                <div className="dim-capsule">
                  <span>概括提炼</span>
                  <strong>{Math.round(assessment.abstraction * 100)}%</strong>
                </div>
                <div className="dim-capsule">
                  <span>表述精准</span>
                  <strong>{Math.round(assessment.precision * 100)}%</strong>
                </div>
                <div className="dim-capsule">
                  <span>结构条理</span>
                  <strong>{Math.round(assessment.structure * 100)}%</strong>
                </div>
                <div className="dim-capsule">
                  <span>语言精炼</span>
                  <strong>{Math.round(assessment.conciseness * 100)}%</strong>
                </div>
              </div>
            </div>
          )}

          {/* 核心：1200px 宽幅舞台【作答文段 · 多名师就地同屏批评与改法对比】 */}
          <MultiTeacherReviewPaper
            answerText={session.final_answer || draftText}
            diagnosis={teacherDiagnosis}
            maxWords={session.material.max_words}
            onObjectionSelect={(quote, tid) => {
              setObjectionQuote(quote);
              if (tid) setActiveTeacherId(tid);
            }}
            activeTeacherId={activeTeacherId}
            onTeacherChange={tid => setActiveTeacherId(tid)}
          />

          {/* 名师在线追问与疑点复核 */}
          {teacherDiagnosis && (
            <div style={{ background: '#fff', border: '1px solid #e0dbce', borderRadius: 8, padding: 22, boxShadow: '0 2px 8px rgba(0,0,0,0.03)' }}>
              <div style={{ fontSize: 15, fontWeight: 700, color: '#a04825', marginBottom: 12 }}>
                💬 与【{TEACHER_META[activeTeacherId]?.name || '当前名师'}】探讨答题思路与异议复核
              </div>
              <TeacherFollowUpChat
                sessionId={session.id}
                teacherId={activeTeacherId}
                teacherName={TEACHER_META[activeTeacherId]?.name || '申论名师'}
                objectionTarget={objectionQuote || teacherDiagnosis.training_targets?.[0]?.user_quote}
              />
            </div>
          )}

          {/* 可折叠的草稿梳理（中间过程） */}
          <details className="shenlun-scratchpad" style={{ marginTop: 8 }}>
            <summary style={{ fontSize: 13, color: '#777', cursor: 'pointer', padding: '10px 14px' }}>
              📝 展开材料标记与草稿梳理（中间过程）
            </summary>
            <div style={{ padding: '12px 16px 18px' }}>
              <div style={{ display: 'grid', gap: 10 }}>
                <label style={{ fontSize: 12, fontWeight: 600 }}>
                  主要问题梳理：
                  <textarea
                    style={{ width: '100%', minHeight: 60, marginTop: 4, padding: 6, fontSize: 12, borderRadius: 4, border: '1px solid #ddd' }}
                    placeholder="材料中的问题与痛点..."
                    value={notes.problem}
                    onChange={e => setNotes({ ...notes, problem: e.target.value })}
                  />
                </label>
                <label style={{ fontSize: 12, fontWeight: 600 }}>
                  应对解决措施：
                  <textarea
                    style={{ width: '100%', minHeight: 60, marginTop: 4, padding: 6, fontSize: 12, borderRadius: 4, border: '1px solid #ddd' }}
                    placeholder="针对性对策与做法..."
                    value={notes.policy}
                    onChange={e => setNotes({ ...notes, policy: e.target.value })}
                  />
                </label>
              </div>
              <button
                type="button"
                className="secondary"
                style={{ width: '100%', marginTop: 10, fontSize: 12 }}
                disabled={busy}
                onClick={saveDraft}
              >
                保存梳理笔记
              </button>
            </div>
          </details>
        </div>
      ) : session && !isCompleted ? (
        /* ================= 书写作答阶段：作答区占主导宽度，不再局促！ ================= */
        <div className="shenlun-paper-layout">
          {/* 左栏：原始题本资料 */}
          <section className="shenlun-question-paper" aria-label="原始资料">
            <div className="shenlun-paper-meta">
              <span>申论 · 真题题本</span>
              <span>{session.material.exam_year} 年</span>
            </div>
            <h2 className="shenlun-paper-title">{session.material.title}</h2>

            {/* 作答题目与要求置顶展示，保障“审题先行” */}
            <section className="shenlun-question-instructions" aria-label="作答题目与要求">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: '#a04825' }}>📌 作答题目与要求</h3>
                <button
                  type="button"
                  style={{ fontSize: 11, color: '#a04825', background: '#faeee9', border: '1px solid #e3b4a8', padding: '2px 8px', borderRadius: 4, cursor: 'pointer' }}
                  onClick={() => setViewMode('reading')}
                  disabled={!session.final_answer}
                  title="前往独立阅读界面查看全维解析"
                >
                  📖 前往全维解析阅读
                </button>
              </div>
              <p>{session.material.question_stem}</p>
              <div className="shenlun-word-limit">
                篇幅要求：不超过 <strong>{session.material.max_words}</strong> 字
              </div>
            </section>

            <h3 className="shenlun-paper-section-title">给定资料</h3>

            <div className="materials-content">
              {session.material.materials.map(m => (
                <article key={m.id} className="shenlun-material-article">
                  <h4>{m.title}</h4>
                  {m.content.split(/\n\s*\n/).filter(p => p.trim()).map((paragraph, index) => (
                    <p key={index}>{paragraph}</p>
                  ))}
                </article>
              ))}
            </div>
          </section>

          {/* 右栏：作答纸（宽幅舒展展示） */}
          <div className="shenlun-answer-container">
            <section className="shenlun-answer-paper" aria-label="作答区">
              {guidance && <ShenlunGuidance key={session.id} sessionId={session.id} state={guidance} onChange={setGuidance} />}
              {/* 考场标准答题纸抬头与区域元信息 */}
              <div style={{ borderBottom: '2px solid #c25745', paddingBottom: 10, marginBottom: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <strong style={{ fontSize: 17, color: '#a04825', letterSpacing: 1 }}>
                    公务员录用考试 · 申论专用答题纸
                  </strong>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button
                      type="button"
                      style={{
                        fontSize: 11,
                        padding: '3px 8px',
                        borderRadius: 4,
                        cursor: 'pointer',
                        background: practiceGridMode === 'editor' ? '#a04825' : '#fff',
                        color: practiceGridMode === 'editor' ? '#fff' : '#666',
                        border: '1px solid #d58778',
                      }}
                      onClick={() => setPracticeGridMode('editor')}
                    >
                      📝 答题纸书写模式
                    </button>
                    <button
                      type="button"
                      style={{
                        fontSize: 11,
                        padding: '3px 8px',
                        borderRadius: 4,
                        cursor: 'pointer',
                        background: practiceGridMode === 'grid' ? '#a04825' : '#fff',
                        color: practiceGridMode === 'grid' ? '#fff' : '#666',
                        border: '1px solid #d58778',
                      }}
                      onClick={() => setPracticeGridMode('grid')}
                    >
                      📑 25列全真红格对照
                    </button>
                  </div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12, color: '#666' }}>
                  <span>第 1 题 作答区域（标准 25 格 / 行 · 标点占一格 · 段首空两格）</span>
                  <span>
                    已书写：
                    <strong style={{ color: wordCount > session.material.max_words ? '#b23b18' : 'var(--accent)', fontSize: 14 }}>
                      {wordCount}
                    </strong>{' '}
                    / {session.material.max_words} 字
                  </span>
                </div>
              </div>

              {/* 输入模式 vs 25列红格排版对照 */}
              {practiceGridMode === 'editor' ? (
                <textarea
                  className="shenlun-answer-sheet"
                  aria-label="申论正式作答"
                  value={draftText}
                  onChange={e => setDraftText(e.target.value)}
                />
              ) : (
                <div>
                  <ShenlunStandardGridPaper
                    text={draftText}
                    maxWords={session.material.max_words}
                    title="申论正式作答 · 全真 25 列红格排版对照"
                    subtitle="第 1 题 作答区域"
                  />
                  <button
                    type="button"
                    style={{ marginTop: 10, fontSize: 12, color: '#a04825', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}
                    onClick={() => setPracticeGridMode('editor')}
                  >
                    ← 返回文本框继续修改作答
                  </button>
                </div>
              )}

              <div className="submit-row" style={{ display: 'flex', gap: 12, marginTop: 16 }}>
                <button type="button" className="secondary" disabled={busy} onClick={saveDraft}>
                  保存草稿
                </button>
                <button
                  className="primary"
                  disabled={busy || !draftText.trim()}
                  onClick={submitFinal}
                  style={{ flex: 1 }}
                >
                  {assessmentPending ? '名师阅卷与评估中…' : '提交作答并批改'}
                </button>
              </div>

              {savedMsg && (
                <p role="status" style={{ fontSize: 12, color: 'var(--accent)', margin: '8px 0 0' }}>
                  {savedMsg}
                </p>
              )}
              {assessmentPending && (
                <p role="status" aria-live="polite" style={{ fontSize: 13, color: '#a04825', marginTop: 10 }}>
                  AI 名师模型正在独立审阅与批注，请稍候…
                </p>
              )}
            </section>

            {/* 可折叠草稿梳理笔记 */}
            <details className="shenlun-scratchpad" style={{ marginTop: 8 }}>
              <summary style={{ fontSize: 13, color: '#777', cursor: 'pointer', padding: '10px 14px' }}>
                📝 展开材料标记与草稿梳理（中间过程）
              </summary>
              <div style={{ padding: '12px 16px 18px' }}>
                <div style={{ display: 'grid', gap: 10 }}>
                  <label style={{ fontSize: 12, fontWeight: 600 }}>
                    主要问题梳理：
                    <textarea
                      style={{ width: '100%', minHeight: 60, marginTop: 4, padding: 6, fontSize: 12, borderRadius: 4, border: '1px solid #ddd' }}
                      placeholder="材料中的问题与痛点..."
                      value={notes.problem}
                      onChange={e => setNotes({ ...notes, problem: e.target.value })}
                    />
                  </label>
                  <label style={{ fontSize: 12, fontWeight: 600 }}>
                    应对解决措施：
                    <textarea
                      style={{ width: '100%', minHeight: 60, marginTop: 4, padding: 6, fontSize: 12, borderRadius: 4, border: '1px solid #ddd' }}
                      placeholder="针对性对策与做法..."
                      value={notes.policy}
                      onChange={e => setNotes({ ...notes, policy: e.target.value })}
                    />
                  </label>
                </div>
                <button
                  type="button"
                  className="secondary"
                  style={{ width: '100%', marginTop: 10, fontSize: 12 }}
                  disabled={busy}
                  onClick={saveDraft}
                >
                  保存梳理笔记
                </button>
              </div>
            </details>
          </div>
        </div>
      ) : null}

      {/* ================= 给定资料对照抽屉 (复盘时按需呼出，绝不挤压主版面) ================= */}
      {showMaterialsDrawer && session && (
        <div className="shenlun-drawer-backdrop" onClick={() => setShowMaterialsDrawer(false)}>
          <div className="shenlun-drawer-content" style={{ width: 680 }} onClick={e => e.stopPropagation()}>
            <div className="drawer-header">
              <h3>📑 题本原始给定资料对照</h3>
              <button
                type="button"
                className="drawer-close-btn"
                onClick={() => setShowMaterialsDrawer(false)}
              >
                ✕
              </button>
            </div>
            <div className="drawer-body materials-content" style={{ padding: '20px 24px' }}>
              <div style={{ background: '#faf6f0', padding: 12, borderRadius: 6, marginBottom: 16, borderLeft: '3px solid #a04825' }}>
                <strong style={{ color: '#a04825' }}>📌 作答题目与要求：</strong>
                <p style={{ margin: '4px 0 0', fontSize: 13, lineHeight: 1.6, color: '#333' }}>
                  {session.material.question_stem}
                </p>
                <div style={{ fontSize: 12, color: '#888', marginTop: 4 }}>
                  篇幅要求：不超过 {session.material.max_words} 字
                </div>
              </div>

              {session.material.materials.map(m => (
                <article key={m.id} className="shenlun-material-article">
                  <h4>{m.title}</h4>
                  {m.content.split(/\n\s*\n/).filter(p => p.trim()).map((paragraph, index) => (
                    <p key={index}>{paragraph}</p>
                  ))}
                </article>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ================= 独立入口 1：本题权威参考解析抽屉（兼容已有用例） ================= */}
      {showExplanationDrawer && session?.final_answer && (
        <div className="shenlun-drawer-backdrop" onClick={() => setShowExplanationDrawer(false)}>
          <div className="shenlun-drawer-content" onClick={e => e.stopPropagation()}>
            <div className="drawer-header">
              <h3>💡 本题官方权威参考解析</h3>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <button
                  type="button"
                  className="shenlun-action-btn"
                  style={{ fontSize: 11, padding: '2px 8px' }}
                  onClick={() => {
                    setShowExplanationDrawer(false);
                    setViewMode('reading');
                  }}
                >
                  📖 切换至全维深度解析独立阅读界面
                </button>
                <button
                  type="button"
                  className="drawer-close-btn"
                  onClick={() => setShowExplanationDrawer(false)}
                >
                  ✕
                </button>
              </div>
            </div>
            <div className="drawer-body explanation-viewer">
              <div style={{ padding: '10px 14px', background: '#faf6f0', borderRadius: 6, marginBottom: 18, borderLeft: '3px solid #a04825' }}>
                <strong style={{ color: '#a04825' }}>{session.material.title}</strong>
                <p style={{ margin: '6px 0 0', fontSize: 13, color: '#555', lineHeight: 1.6 }}>
                  {session.material.question_stem}
                </p>
                <div style={{ fontSize: 12, color: '#888', marginTop: 4 }}>
                  字数要求：不超过 {session.material.max_words} 字
                </div>
              </div>

              <h4>权威示范作答与采分要点</h4>
              <div className="explanation-content-box">
                {session.material.reference_answer || '暂无详细参考解析'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ================= 独立入口 2：申论全真题库模态浏览器 ================= */}
      {showBankModal && (
        <div className="shenlun-drawer-modal" onClick={() => setShowBankModal(false)}>
          <div className="shenlun-modal-content" onClick={e => e.stopPropagation()}>
            <div className="drawer-header">
              <h3>📚 江苏省考历年申论真题库与权威解析（2017-2023）</h3>
              <button
                type="button"
                className="drawer-close-btn"
                onClick={() => setShowBankModal(false)}
              >
                ✕
              </button>
            </div>

            <div className="drawer-body" style={{ display: 'grid', gridTemplateColumns: bankPreviewItem ? '1.1fr 1.2fr' : '1fr', gap: 20 }}>
              {/* 左侧：题库列表与年份过滤 */}
              <div>
                <div className="bank-filter-bar">
                  <button
                    type="button"
                    className={`bank-filter-chip ${selectedYear === 'ALL' ? 'active' : ''}`}
                    onClick={() => setSelectedYear('ALL')}
                  >
                    全部年份 ({bankList.length})
                  </button>
                  {availableYears.map(yr => (
                    <button
                      key={yr}
                      type="button"
                      className={`bank-filter-chip ${selectedYear === yr ? 'active' : ''}`}
                      onClick={() => setSelectedYear(yr)}
                    >
                      {yr}年
                    </button>
                  ))}
                </div>

                {bankLoading ? (
                  <p style={{ color: '#888', fontSize: 13 }}>加载题库目录中…</p>
                ) : (
                  <div className="bank-list-grid" style={{ maxHeight: '65vh', overflowY: 'auto' }}>
                    {filteredBankList.map(item => (
                      <div
                        key={item.id}
                        className={`bank-item-card ${bankPreviewItem?.id === item.id ? 'current' : ''}`}
                        onClick={() => void loadPreviewItem(item.id)}
                      >
                        <div className="bank-item-title">{item.title}</div>
                        <div className="bank-item-stem">{item.question_stem}</div>
                        <div className="bank-item-meta">
                          <span>限 {item.max_words} 字</span>
                          <span style={{ color: item.has_reference_answer ? '#16a34a' : '#888' }}>
                            {item.has_reference_answer ? '✓ 含官方解析' : '待补充'}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* 右侧：试题与解析详情预览 */}
              {bankPreviewItem && (
                <div style={{ borderLeft: '1px solid #eee', paddingLeft: 20, maxHeight: '65vh', overflowY: 'auto' }}>
                  {previewLoading ? (
                    <p style={{ color: '#888', fontSize: 13 }}>加载试题与解析详情中…</p>
                  ) : (
                    <div className="explanation-viewer">
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <h3 style={{ margin: '0 0 10px', fontSize: 18, color: '#a04825' }}>
                          {bankPreviewItem.title}
                        </h3>
                        <div style={{ display: 'flex', gap: 8 }}>
                          <button
                            type="button"
                            className="shenlun-action-btn"
                            style={{ padding: '4px 10px', fontSize: 12 }}
                            onClick={() => {
                              setShowBankModal(false);
                              void startSession(bankPreviewItem.id);
                              setViewMode('reading');
                            }}
                          >
                            📖 进入全维独立深度解析
                          </button>
                          <button
                            type="button"
                            className="shenlun-action-btn primary"
                            style={{ padding: '4px 10px', fontSize: 12 }}
                            onClick={() => {
                              setShowBankModal(false);
                              void startSession(bankPreviewItem.id);
                            }}
                          >
                            前往练习此题
                          </button>
                        </div>
                      </div>

                      <div style={{ background: '#faf6f0', padding: 12, borderRadius: 6, margin: '10px 0' }}>
                        <strong style={{ fontSize: 13 }}>作答要求：</strong>
                        <p style={{ margin: '4px 0 0', fontSize: 13, lineHeight: 1.6 }}>
                          {bankPreviewItem.question_stem}
                        </p>
                        <small style={{ color: '#8a6d3b', display: 'block', marginTop: 4 }}>
                          篇幅：不超过 {bankPreviewItem.max_words} 字
                        </small>
                      </div>

                      <h4>官方权威参考答案与采分解析</h4>
                      <div className="explanation-content-box" style={{ maxHeight: 380, overflowY: 'auto' }}>
                        {bankPreviewItem.reference_answer || '暂无详细参考解析'}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
