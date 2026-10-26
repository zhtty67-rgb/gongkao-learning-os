'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { api, DashboardData, ErrorAnalytics, MasteryData } from '../../lib/api';
import { confidenceLabel } from '../../lib/confidence';
import { InteractiveReviewCard } from '../../lib/InteractiveReviewCard';
import { ShenlunDailyTaskCard } from '../../lib/ShenlunDailyTaskCard';

function percent(value: number | null) { return value === null ? '—' : `${Math.round(value * 100)}%`; }
function duration(value: number | null) { if (value === null) return '—'; const seconds = Math.round(value / 1000); return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)}分 ${seconds % 60}秒`; }

export default function Dashboard() {
  type TodayView = { as_of: string; daily_goal: any; due_reviews: { count: number; active_session_id: string | null }; plan_today: { exists: boolean; allocation: Record<string, number> | null; question_count: number }; study_tasks: { pending: number; teaching_pending: number }; teaching_sessions: { active_nodes: number } };
  const [data, setData] = useState<{ dashboard: DashboardData; mastery: MasteryData; errors: ErrorAnalytics } | null>(null);
  const [today, setToday] = useState<TodayView | null>(null);
  const [error, setError] = useState('');
  const [expandedErrorReview, setExpandedErrorReview] = useState<Record<string, boolean>>({});
  const [expandedFramework, setExpandedFramework] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let active = true;
    Promise.all([api<DashboardData>('/dashboard'), api<MasteryData>('/mastery'), api<ErrorAnalytics>('/analytics/errors'), api<TodayView>('/today').catch(() => null)])
      .then(([dashboard, mastery, errors, todayView]) => { if (active) { setData({ dashboard, mastery, errors }); setToday(todayView); } })
      .catch(() => { if (active) setError('暂时无法读取学习数据，请确认后端已启动后刷新页面。'); });
    return () => { active = false; };
  }, []);

  // 提取大框架模型（仅保留模块根节点与直属核心分类大框架，不平铺底层细碎考点）
  const moduleFrameworks = (() => {
    if (!data?.mastery?.nodes) return [];

    const MODULE_ORDER = [
      '言语理解', '数量关系', '判断推理', '图形推理', '立体图推', '定义判断', '类比推理', '逻辑判断', '资料分析', '政治理论', '常识判断', '申论'
    ];

    const nodesByModule = Object.groupBy(data.mastery.nodes, n => n.module);
    const result = [];

    for (const [module, mNodes] of Object.entries(nodesByModule)) {
      if (!mNodes || mNodes.length === 0) continue;

      const rootNode = mNodes.find(n => n.parent_id === null) || mNodes[0];
      const directChildren = rootNode ? mNodes.filter(n => n.parent_id === rootNode.id) : [];

      const subFrameworks = directChildren.length > 0
        ? directChildren
        : mNodes.slice(0, 4);

      const totalNodes = mNodes.length;
      const practicedNodes = mNodes.filter(n => (n.attempt_count || 0) > 0).length;
      const totalAttempts = mNodes.reduce((acc, n) => acc + (n.attempt_count || 0), 0);
      const masteryScore = rootNode?.mastery_score ?? (
        mNodes.reduce((acc, n) => acc + n.mastery_score, 0) / mNodes.length
      );

      result.push({
        module,
        rootNode,
        masteryScore,
        totalNodes,
        practicedNodes,
        totalAttempts,
        subFrameworks
      });
    }

    result.sort((a, b) => {
      const idxA = MODULE_ORDER.indexOf(a.module);
      const idxB = MODULE_ORDER.indexOf(b.module);
      return (idxA !== -1 ? idxA : 99) - (idxB !== -1 ? idxB : 99);
    });

    return result;
  })();
  return <main>
    <header><Link href="/dashboard" className="brand"><span className="brand-icon">学</span>公考 Learning OS</Link><nav><Link href="/dashboard" className="active">学习概览</Link><Link href="/framework">知识框架</Link><Link href="/study">学习任务</Link><Link href="/teaching">自适应教学</Link><Link href="/quiz">行测训练</Link><Link href="/review">到期复习</Link><Link href="/notes">我的笔记</Link><Link href="/exam">全真模考</Link><Link href="/shenlun">申论工作台</Link><Link href="/importer">题库导入</Link><Link href="/settings">设置</Link></nav><span className="local">● 本地学习空间</span></header>
    <div className="intro dashboard-intro"><span className="eyebrow">DASHBOARD / 学习概览</span><h1>用真实作答，看见下一步。</h1><p>所有指标都由本机保存的作答记录计算，可以随时重新生成。 <Link href="/question-sources">按原书、原卷题号找题 →</Link></p></div>
    {error && <div role="alert" className="error">{error}</div>}
    {!data && !error && <p role="status">正在计算学习状态…</p>}
    {data && <>
      {today && (
        <section className="dashboard-section" style={{ marginBottom: 16 }}>
          <div className="card" style={{ padding: 16, display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'center' }}>
            <strong style={{ marginRight: 4 }}>今日学习一览</strong>
            <Link href="/review" className="primary-link">到期复习 {today.due_reviews.count} 题{today.due_reviews.active_session_id ? '（有进行中会话）' : ''}</Link>
            <Link href="/quiz" className="primary-link">今日计划 {today.plan_today.exists ? `${today.plan_today.question_count} 题` : '不可用'}</Link>
            <Link href="/study" className="primary-link">待办学习任务 {today.study_tasks.pending} 项{today.study_tasks.teaching_pending ? `（含教学疑点 ${today.study_tasks.teaching_pending}）` : ''}</Link>
            {today.teaching_sessions.active_nodes > 0 && <Link href="/framework" className="primary-link">进行中教学 · {today.teaching_sessions.active_nodes} 个考点</Link>}
          </div>
        </section>
      )}
      {data.dashboard.daily_goal && (
        <section className="daily-goal-card" style={{
          background: 'linear-gradient(135deg, #245539 0%, #16301f 100%)',
          color: '#fff',
          borderRadius: 16,
          padding: '22px 26px',
          marginBottom: 20,
          boxShadow: '0 2px 6px rgba(20,47,34,.25), 0 16px 36px rgba(20,47,34,.22)'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 20 }}>🎯</span>
                <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0, color: '#f4f8f3' }}>
                  今日刷题目标：500 题
                </h2>
                <span style={{
                  background: data.dashboard.daily_goal.completed >= 500 ? '#3ecf8e' : '#e8a83c',
                  color: '#fff',
                  fontSize: 11,
                  fontWeight: 700,
                  padding: '2px 8px',
                  borderRadius: 12
                }}>
                  {data.dashboard.daily_goal.completed >= 500 ? '🎉 今日已达成' : `进行中 ${data.dashboard.daily_goal.progress_percent}%`}
                </span>
              </div>
              <p style={{ margin: 0, fontSize: 13, color: '#a9c2ae' }}>
                今日已完成 <strong style={{ color: '#fff', fontSize: 16 }}>{data.dashboard.daily_goal.completed}</strong> / 500 题 · 
                包含日常训练 <strong style={{ color: '#9fd8b6' }}>{data.dashboard.daily_goal.practice_count}</strong> 题 + 
                到期复习 <strong style={{ color: '#f0c97f' }}>{data.dashboard.daily_goal.review_count}</strong> 题
                {data.dashboard.daily_goal.remaining > 0 && `（还剩 ${data.dashboard.daily_goal.remaining} 题）`}
              </p>
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <Link href="/quiz" className="primary" style={{ padding: '8px 18px', textDecoration: 'none', borderRadius: 6, fontSize: 13, fontWeight: 600 }}>
                继续训练
              </Link>
              <Link href="/review" className="secondary" style={{ padding: '8px 16px', textDecoration: 'none', borderRadius: 8, fontSize: 13, color: '#e8f0e6', background: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.22)' }}>
                到期复习
              </Link>
            </div>
          </div>

          <div style={{
            marginTop: 16,
            background: 'rgba(255,255,255,0.15)',
            borderRadius: 8,
            height: 10,
            overflow: 'hidden',
            display: 'flex'
          }}>
            <div style={{
              width: `${Math.min(100, (data.dashboard.daily_goal.practice_count / 500) * 100)}%`,
              background: '#6fbf8f',
              transition: 'width 0.4s ease'
            }} title={`日常训练 ${data.dashboard.daily_goal.practice_count} 题`} />
            <div style={{
              width: `${Math.min(100, (data.dashboard.daily_goal.review_count / 500) * 100)}%`,
              background: '#e8a83c',
              transition: 'width 0.4s ease'
            }} title={`到期复习 ${data.dashboard.daily_goal.review_count} 题`} />
          </div>
        </section>
      )}
      {data.dashboard.daily_goal?.shenlun && <ShenlunDailyTaskCard task={data.dashboard.daily_goal.shenlun} />}
      {data.dashboard.credibility_audit && (
        <section className="credibility-audit-card" style={{
          background: '#f8faf9',
          border: '1px solid #d2e4d6',
          borderRadius: 14,
          padding: '18px 22px',
          marginBottom: 20
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 18 }}>📋</span>
              <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0, color: '#1f4530' }}>
                学习记录真实性与统计口径审计
              </h3>
              <span style={{ fontSize: 12, background: '#e2f0e6', color: '#245539', padding: '2px 8px', borderRadius: 10, fontWeight: 600 }}>
                有效样本 {data.dashboard.credibility_audit.valid_stats_count} 题
              </span>
            </div>
            <small style={{ color: '#688272' }}>集中统一统计口径 · 历史记录未知诚实呈现</small>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 14 }}>
            <div style={{ background: '#fff', padding: '10px 14px', borderRadius: 8, border: '1px solid #e1ebe3' }}>
              <div style={{ fontSize: 12, color: '#666' }}>系统内作答分布</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#16301f', marginTop: 4 }}>
                首答 {data.dashboard.credibility_audit.first_time_count} · 重复 {data.dashboard.credibility_audit.repeat_count}
              </div>
              <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>首答指系统内首次作答</div>
            </div>

            <div style={{ background: '#fff', padding: '10px 14px', borderRadius: 8, border: '1px solid #e1ebe3' }}>
              <div style={{ fontSize: 12, color: '#666' }}>辅助曝光分布</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#16301f', marginTop: 4 }}>
                未记辅助 {data.dashboard.credibility_audit.unassisted_count} · 有提示 {data.dashboard.credibility_audit.assisted_count} · 未知 {data.dashboard.credibility_audit.unknown_exposure_count}
              </div>
              <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>未记系统辅助不等于未用外部帮助</div>
            </div>

            <div style={{ background: '#fff', padding: '10px 14px', borderRadius: 8, border: '1px solid #e1ebe3' }}>
              <div style={{ fontSize: 12, color: '#666' }}>计时测定与估算分布</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#16301f', marginTop: 4 }}>
                实测 {data.dashboard.credibility_audit.measured_timing_count} · 组题均分 {data.dashboard.credibility_audit.estimated_timing_count} · 异常 {data.dashboard.credibility_audit.invalid_timing_count}
              </div>
              <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>组题估算不混入单题速度指标，正误保留</div>
            </div>

            <div style={{ background: '#fff', padding: '10px 14px', borderRadius: 8, border: '1px solid #e1ebe3' }}>
              <div style={{ fontSize: 12, color: '#666' }}>记录来源构成</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#16301f', marginTop: 4 }}>
                真实 {data.dashboard.credibility_audit.real_study_count} · 未知 {data.dashboard.credibility_audit.unknown_source_count} · 测试 {data.dashboard.credibility_audit.excluded_test_count}
              </div>
              <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>已确认测试已完全排除出正式数据</div>
            </div>
          </div>

          <details style={{ fontSize: 12, color: '#4d6957', cursor: 'pointer' }}>
            <summary style={{ fontWeight: 600 }}>查看本轮统计采用的口径与排除规则</summary>
            <ul style={{ margin: '8px 0 0 16px', padding: 0, lineHeight: 1.6 }}>
              {data.dashboard.credibility_audit.rules_explanation.map((rule, idx) => (
                <li key={idx}>{rule}</li>
              ))}
            </ul>
          </details>
        </section>
      )}
      <section className="metric-grid" aria-label="核心指标">
        <article><small>总正确率</small><strong>{percent(data.dashboard.metrics.accuracy)}</strong><span>{data.dashboard.metrics.attempt_count} 次作答</span></article>
        <article><small>限时正确率</small><strong>{percent(data.dashboard.metrics.timed_accuracy)}</strong><span>在建议时间内完成</span></article>
        <article><small>平均耗时</small><strong>{duration(data.dashboard.metrics.average_elapsed_ms)}</strong><span>基于可用单题实测样本</span></article>
        <article className="featured"><small>综合 Mastery</small><strong>{percent(data.dashboard.metrics.mastery)}</strong><span>Beta-Bernoulli 证据模型</span></article>
        <article><small>高信心错误</small><strong>{data.dashboard.metrics.high_confidence_errors}</strong><span>信心 ≥ 80% 但答错</span></article>
        <article><small>提示依赖</small><strong>{percent(data.dashboard.metrics.hint_dependency)}</strong><span>Phase 2 暂无提示功能</span></article>
      </section>
      <section className="decision-grid">
        <article className="focus-card"><span className="eyebrow">NEXT ACTION</span><h2>{data.dashboard.weakest ? `当前优先：${data.dashboard.weakest.name}` : '先完成一轮行测训练'}</h2><p>{data.dashboard.recommendation}</p><Link href="/quiz" className="primary-link">开始训练</Link></article>
        <article className="evidence-card"><h2>为什么？</h2>{data.dashboard.weakest ? <><p>该能力点当前是已练习内容中掌握度最低的一项。</p><dl><div><dt>作答证据</dt><dd>{data.dashboard.weakest.attempt_count} 次</dd></div><div><dt>近期正确率</dt><dd>{percent(data.dashboard.weakest.recent_accuracy)}</dd></div><div><dt>平均用时比</dt><dd>{data.dashboard.weakest.avg_time_ratio === null ? '—' : `${data.dashboard.weakest.avg_time_ratio.toFixed(2)}×`}</dd></div></dl></> : <p>现在还没有正式作答。完成训练后，系统会给出证据和建议。</p>}</article>
      </section>
      <section className="dashboard-section">
        <div className="section-heading">
          <div>
            <span className="eyebrow">KNOWLEDGE FRAMEWORK</span>
            <h2>知识大框架与掌握度</h2>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <span style={{ fontSize: 12, color: 'var(--muted)' }}>
              已简化为模块与核心大分类框架 · 深入研读请查阅知识框架
            </span>
            <Link
              href="/framework"
              className="secondary"
              style={{
                fontSize: 12,
                padding: '4px 12px',
                borderRadius: 6,
                textDecoration: 'none',
                color: 'var(--accent)',
                border: '1px solid var(--line)',
                background: '#fbfcfb',
                fontWeight: 600
              }}
            >
              查看完整知识地图 →
            </Link>
          </div>
        </div>

        <div className="framework-groups" style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
          gap: 16
        }}>
          {moduleFrameworks.map(fw => {
            const isExp = !!expandedFramework[fw.module];
            return (
              <article
                key={fw.module}
                style={{
                  border: '1px solid var(--line)',
                  borderRadius: 12,
                  padding: '18px 20px',
                  background: '#fff',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 12,
                  boxShadow: 'var(--shadow-sm)'
                }}
              >
                {/* 顶部标题与掌握度 */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <h3 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 4px', color: '#16301f' }}>
                      {fw.module}
                    </h3>
                    <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                      {fw.practicedNodes > 0
                        ? `已练习 ${fw.practicedNodes} / ${fw.totalNodes} 考点 · ${fw.totalAttempts} 次证据`
                        : `共 ${fw.totalNodes} 个细分考点 · 尚未练习`}
                    </span>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <strong style={{ fontSize: 20, fontWeight: 700, color: 'var(--accent)' }}>
                      {percent(fw.masteryScore)}
                    </strong>
                    <div style={{ fontSize: 10, color: 'var(--muted)' }}>模块掌握度</div>
                  </div>
                </div>

                {/* 整体掌握度条 */}
                <div className="mastery-bar" style={{ height: 8, borderRadius: 4 }} aria-label={`${fw.module} 掌握度 ${Math.round(fw.masteryScore * 100)}%`}>
                  <i style={{ width: `${Math.round(fw.masteryScore * 100)}%`, background: 'var(--accent)' }} />
                </div>

                {/* 核心大分类骨架 */}
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: '#4d6957', marginBottom: 6 }}>
                    核心大分类框架 ({fw.subFrameworks.length})：
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {fw.subFrameworks.map(sub => (
                      <span
                        key={sub.id}
                        style={{
                          fontSize: 11,
                          padding: '3px 8px',
                          borderRadius: 6,
                          background: (sub.attempt_count || 0) > 0 ? '#eaf4ee' : '#f3f4f1',
                          color: (sub.attempt_count || 0) > 0 ? '#1b4d2e' : '#555',
                          border: '1px solid #dfe5dc'
                        }}
                      >
                        {sub.name}
                      </span>
                    ))}
                  </div>
                </div>

                {/* 轻量折叠查看大分类掌握度 */}
                <div style={{ marginTop: 'auto', paddingTop: 8, borderTop: '1px dashed #e8ebe5' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <button
                      type="button"
                      style={{
                        background: 'none',
                        border: 'none',
                        padding: 0,
                        fontSize: 11,
                        color: 'var(--accent)',
                        cursor: 'pointer',
                        fontWeight: 600
                      }}
                      onClick={() => setExpandedFramework(prev => ({ ...prev, [fw.module]: !prev[fw.module] }))}
                    >
                      {isExp ? '收起大类掌握度 ▲' : '查看大类掌握度 ▼'}
                    </button>
                    <Link
                      href="/framework"
                      style={{ fontSize: 11, color: 'var(--muted)', textDecoration: 'none' }}
                    >
                      在知识树中查看 →
                    </Link>
                  </div>

                  {isExp && (
                    <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {fw.subFrameworks.map(sub => (
                        <div
                          key={sub.id}
                          style={{
                            display: 'grid',
                            gridTemplateColumns: 'minmax(120px, 1fr) 70px 36px',
                            gap: 8,
                            alignItems: 'center',
                            fontSize: 11
                          }}
                        >
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={sub.name}>
                            {sub.name}
                          </span>
                          <div className="mastery-bar" style={{ height: 6 }}>
                            <i style={{ width: `${Math.round(sub.mastery_score * 100)}%` }} />
                          </div>
                          <span style={{ textAlign: 'right', fontWeight: 600 }}>
                            {percent(sub.mastery_score)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </section>
      <section className="dashboard-section">
        <div className="section-heading">
          <div><span className="eyebrow">ERROR TRACKING</span><h2>错因记录与复盘</h2></div>
          <span>{data.errors.undiagnosed_count} 道错题尚未归因</span>
        </div>
        {data.errors.events.length ? (
          <div className="error-list">
            {data.errors.events.slice(0, 6).map(event => {
              const isExpanded = !!expandedErrorReview[event.id];
              return (
                <article key={event.id} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 6 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span className="pill">{event.error_label}</span>
                      {event.has_review && (
                        <span style={{
                          fontSize: 11,
                          padding: '1px 8px',
                          borderRadius: 10,
                          background: event.review_is_user_confirmed ? '#e2f0e6' : '#ffedd5',
                          color: event.review_is_user_confirmed ? '#166534' : '#c2410c',
                          fontWeight: 600,
                        }}>
                          {event.review_is_user_confirmed ? '✓ 已复盘确认' : '💬 已有复盘记录'}
                        </span>
                      )}
                    </div>
                    <button
                      type="button"
                      className="secondary"
                      style={{ padding: '3px 10px', fontSize: 12, borderRadius: 4 }}
                      onClick={() => setExpandedErrorReview(prev => ({ ...prev, [event.id]: !prev[event.id] }))}
                    >
                      {isExpanded ? '收起复盘' : event.has_review ? '查看复盘对话' : '开启互动复盘'}
                    </button>
                  </div>
                  <h3>{event.stem}</h3>
                  <p>{event.explanation || '未填写补充说明'}</p>
                  {event.review_summary && !isExpanded && (
                    <div style={{ fontSize: 12, color: '#64748b', background: '#f8fafc', padding: '4px 8px', borderRadius: 4 }}>
                      💡 <strong>复盘摘要：</strong>{event.review_summary}
                    </div>
                  )}
                  <small>{event.module} · 信心 {confidenceLabel(event.confidence)}</small>
                  {isExpanded && (
                    <div style={{ marginTop: 8 }}>
                      <InteractiveReviewCard
                        attemptId={event.attempt_id}
                        isCorrect={false}
                        confidence={event.confidence}
                        stem={event.stem}
                        module={event.module}
                      />
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        ) : (
          <div className="empty-state"><p>还没有错因记录。答错后选择原因，这里会保留最新判断。</p></div>
        )}
      </section>
    </>}
    <footer>PHASE 2 · 可追溯的学习状态<span>知识树 / 掌握度 / 错因 / Dashboard</span></footer>
  </main>;
}
