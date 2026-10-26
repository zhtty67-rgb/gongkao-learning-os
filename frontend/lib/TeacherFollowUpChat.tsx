'use client';

import React, { useEffect, useRef, useState } from 'react';
import { api } from './api';
import { TeachingContent } from './TeachingContent';

type FollowUpMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: { kind: string; ref: string; title: string }[];
  kind?: string; // question | objection
  target_key?: string; // 异议回复：持久化的 "条目:动作" 修订摘要
  revisions?: { target_key: string; action: string }[];
  created_at?: string;
};

const OBJECTION_ACTIONS: Record<string, { label: string; color: string }> = {
  maintain: { label: '维持原判', color: '#9a6700' },
  adjust: { label: '已调整', color: '#0f6c8c' },
  withdraw: { label: '已撤回', color: '#b23b18' },
};

/**
 * 申论教师追问对话组件：挂在每位教师的诊断卡片下。
 * 对话按 (session_id, teacher_id) 持久化，刷新后仍在。
 * 质疑类消息（含"为什么错/不是这样/我的意思是…"）触发对原诊断的重审：
 * AI 可维持/调整/撤回诊断条目；用户可附带自己的最终错因归属，与 AI 判断分开记录。
 */
export function TeacherFollowUpChat({
  sessionId,
  teacherId,
  teacherName,
  objectionTarget,
}: {
  sessionId: string;
  teacherId: string;
  teacherName: string;
  objectionTarget?: string; // 可选：要质疑的诊断条目原句，用于预填异议
}) {
  const [messages, setMessages] = useState<FollowUpMessage[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const loadedRef = useRef(false);

  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    api<{ messages: FollowUpMessage[] }>(`/shenlun/${sessionId}/teacher/${teacherId}/followups`)
      .then(res => setMessages(res.messages || []))
      .catch(() => {});
  }, [sessionId, teacherId]);

  async function send(question: string, userAttribution?: string, intent: string = 'auto') {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setError('');
    setInput('');
    // 乐观插入用户消息
    const optimistic: FollowUpMessage = { id: `tmp-${Date.now()}`, role: 'user', content: q };
    setMessages(prev => [...prev, optimistic]);
    try {
      const reply = await api<FollowUpMessage>(
        `/shenlun/${sessionId}/teacher/${teacherId}/followup`,
        { question: q, user_attribution: userAttribution || '', intent },
      );
      setMessages(prev => [...prev, reply]);
    } catch (err: any) {
      setError(err.message || '追问失败，请重试');
      setMessages(prev => prev.filter(m => m.id !== optimistic.id));
      setInput(q);
    } finally {
      setBusy(false);
    }
  }


  return (
    <div style={{ marginTop: 12, borderTop: '1px dashed #e3d5c8', paddingTop: 10 }}>
      <div style={{ maxHeight: 320, overflowY: 'auto', marginBottom: 10 }}>
        {messages.length === 0 && (
          <p style={{ fontSize: 12, color: 'var(--muted)', margin: '4px 0 8px' }}>
            💬 可以追问：为什么这样改、这个点怎么提炼……回答只引用{teacherName}的规则库与语料，检索不到会明说。
            对某条诊断有异议时直接质疑（如"这条为什么算错？我的意思是……"），系统会带着材料重新审查，可撤回误判。
          </p>
        )}
        {messages.map(m => (
          <div
            key={m.id}
            style={{
              display: 'flex',
              justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start',
              margin: '6px 0',
            }}
          >
            <div
              style={{
                maxWidth: '88%',
                padding: '8px 12px',
                borderRadius: 10,
                fontSize: 13,
                lineHeight: 1.7,
                background: m.role === 'user' ? '#e8f0e8' : '#faf6f0',
                border: m.role === 'user' ? '1px solid #d5e3d5' : '1px solid #eadfd2',
              }}
            >
              {m.role === 'assistant' && (
                <div style={{ fontSize: 11, color: '#a04825', fontWeight: 700, marginBottom: 4 }}>
                  {m.kind === 'objection' ? '复核结果' : teacherName}
                </div>
              )}
              {m.role === 'user' && m.kind === 'objection' && (
                <div style={{ fontSize: 10, color: '#b23b18', fontWeight: 700, marginBottom: 2 }}>
                  我的异议
                </div>
              )}
              <TeachingContent text={m.content} />
              {m.role === 'assistant' && m.kind === 'objection' && (() => {
                // 修订徽章：优先用响应中的 revisions；刷新后从持久化的 target_key 恢复
                const revs = (m.revisions && m.revisions.length > 0)
                  ? m.revisions
                  : (m.target_key || '').split(';').filter(Boolean).map(s => {
                      const [tk, act] = s.split(':');
                      return { target_key: tk, action: act || '' };
                    }).filter(r => r.target_key);
                if (revs.length === 0) return null;
                return (
                  <div style={{ marginTop: 6, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {revs.map(r => {
                      const meta = OBJECTION_ACTIONS[r.action] || { label: r.action, color: '#555' };
                      return (
                        <span key={r.target_key + r.action} style={{
                          fontSize: 10, fontWeight: 700, padding: '1px 8px', borderRadius: 10,
                          background: '#f0f0eb', color: meta.color,
                        }}>
                          {r.target_key} · {meta.label}
                        </span>
                      );
                    })}
                  </div>
                );
              })()}
              {m.role === 'assistant' && m.citations && m.citations.length > 0 && (
                <div style={{ marginTop: 6, fontSize: 10, color: 'var(--muted)' }}>
                  依据：{m.citations.map(c => `${c.ref} ${c.title}`.trim()).join('；')}
                </div>
              )}
            </div>
          </div>
        ))}
        {busy && (
          <p role="status" aria-live="polite" style={{ fontSize: 12, color: 'var(--muted)' }}>
            {teacherName}正在查阅自己的规则库作答…
          </p>
        )}
        {error && <p style={{ fontSize: 12, color: '#b23b18' }}>{error}</p>}
      </div>

      {objectionTarget && (
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => {
            const text = `「${objectionTarget.slice(0, 40)}」这条为什么算问题？我的意思是……`;
            setInput(text);
            void send(text, undefined, 'objection');
          }}
          style={{ marginBottom: 8, fontSize: 12 }}
        >
          ⚡ 对此诊断提出异议（复核）
        </button>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) void send(input, undefined, 'auto');
          }}
          placeholder={`向${teacherName}的教学体系追问或提出异议…`}
          disabled={busy}
          style={{
            flex: 1, padding: '8px 12px', fontSize: 13,
            borderRadius: 8, border: '1px solid var(--line)',
          }}
        />
        <button
          type="button"
          className="secondary"
          disabled={busy || !input.trim()}
          onClick={() => void send(input, undefined, 'auto')}
          style={{ whiteSpace: 'nowrap' }}
        >
          发送
        </button>
      </div>
      <small style={{ color: 'var(--muted)', fontSize: 10, display: 'block', marginTop: 6 }}>
        回答由依据{teacherName}课程资料的 AI 辅助生成，不代表{teacherName}本人批改，也不是官方评分标准。
      </small>
    </div>
  );
}
