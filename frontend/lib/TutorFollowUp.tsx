'use client';
import { TeachingContent } from './TeachingContent';

import React, { useEffect, useRef, useState } from 'react';
import { api, ApiError, DiagnosisOutput, FollowUpHistory, FollowUpMessage } from './api';

interface TutorFollowUpProps {
  attemptId: string;
  selectedAnswer?: string | null;
  correctAnswer: string;
  isCorrect?: boolean;
  diagnosis?: DiagnosisOutput | null;
}

export function TutorFollowUp({
  attemptId,
  selectedAnswer,
  correctAnswer,
  isCorrect,
  diagnosis,
}: TutorFollowUpProps) {
  const [messages, setMessages] = useState<FollowUpMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [fetchingHistory, setFetchingHistory] = useState(true);
  const [error, setError] = useState('');
  const [isExpanded, setIsExpanded] = useState(true);

  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Load existing follow-up history for this attempt
  useEffect(() => {
    let active = true;
    setMessages([]);
    setInput('');
    setError('');
    setFetchingHistory(true);

    api<FollowUpHistory>(`/attempts/${attemptId}/followups`)
      .then(res => {
        if (active && res && Array.isArray(res.messages)) {
          setMessages(res.messages);
        }
      })
      .catch(err => {
        if (active) {
          console.warn('Failed to load follow-up history:', err);
        }
      })
      .finally(() => {
        if (active) setFetchingHistory(false);
      });

    return () => {
      active = false;
    };
  }, [attemptId]);

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    if (messages.length > 0 && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  async function handleSend(textToSend?: string) {
    const questionText = (textToSend ?? input).trim();
    if (!questionText || loading) return;

    setError('');
    setLoading(true);

    const tempUserMsg: FollowUpMessage = {
      id: `temp-${Date.now()}`,
      attempt_id: attemptId,
      role: 'user',
      content: questionText,
      created_at: new Date().toISOString(),
    };
    setMessages(prev => [...prev, tempUserMsg]);
    if (!textToSend) {
      setInput('');
    }

    try {
      const reply = await api<FollowUpMessage>(`/attempts/${attemptId}/followup`, {
        question: questionText,
        diagnosis: diagnosis || undefined,
      });
      setMessages(prev => {
        return prev
          .map(m => (m.id === tempUserMsg.id ? { ...m, id: reply.user_message_id || m.id } : m))
          .concat(reply);
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '追问请求失败，请检查网络或后端状态');
      setMessages(prev => prev.filter(m => m.id !== tempUserMsg.id));
      setInput(questionText);
    } finally {
      setLoading(false);
      if (textareaRef.current) {
        textareaRef.current.focus();
      }
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  }

  // Generate contextual quick-prompt chips based on diagnosis and attempt facts
  const quickChips: string[] = [];
  if (diagnosis && diagnosis.error_label) {
    quickChips.push(`💡 为什么诊断我是「${diagnosis.error_label}」？`);
    quickChips.push(`🎯 针对「${diagnosis.error_label}」，做题时有什么防错技巧？`);
    if (selectedAnswer && selectedAnswer !== correctAnswer) {
      quickChips.push(`🔍 为什么不选 ${selectedAnswer}？请指出我的审题卡点`);
    }
    quickChips.push(`📚 这类题有什么针对性的巩固建议？`);
  } else {
    if (isCorrect === false && selectedAnswer && selectedAnswer !== correctAnswer) {
      quickChips.push(`💡 为什么不能选 ${selectedAnswer}？`);
    }
    quickChips.push('⚡ 这道题有什么快速秒杀/排除技巧？');
    quickChips.push('📝 能否更详细地拆解核心解题步骤？');
    quickChips.push('⚠️ 这类题型通常有哪些易错陷阱？');
  }

  const isDiagMode = Boolean(diagnosis);

  return (
    <div
      className="tutor-followup-container"
      style={{
        marginTop: 10,
        background: isDiagMode ? '#ffffff' : '#ffffff',
        border: isDiagMode ? '1px solid #eedfd4' : '1px solid #e2e8f0',
        borderRadius: 8,
        overflow: 'hidden',
        boxShadow: isDiagMode ? '0 1px 4px rgba(160, 72, 37, 0.08)' : '0 1px 3px rgba(0, 0, 0, 0.04)',
      }}
    >
      {/* Header bar */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '9px 12px',
          background: isDiagMode ? '#fdf8f5' : '#f8fafc',
          borderBottom: isExpanded ? (isDiagMode ? '1px solid #eedfd4' : '1px solid #e2e8f0') : 'none',
          cursor: 'pointer',
          userSelect: 'none',
        }}
        onClick={() => setIsExpanded(prev => !prev)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 15 }}>💬</span>
          <h4 style={{ margin: 0, fontSize: 13, fontWeight: 700, color: isDiagMode ? '#9a3412' : '#1e293b' }}>
            {isDiagMode ? `追问错因诊断（${diagnosis?.error_label || '深度答疑'}）` : 'AI 助教答疑追问'}
          </h4>
          <span
            style={{
              fontSize: 11,
              color: isDiagMode ? '#9a3412' : '#475569',
              background: isDiagMode ? '#ffedd5' : '#e2e8f0',
              padding: '1px 6px',
              borderRadius: 10,
              fontWeight: 600,
            }}
          >
            {messages.length > 0 ? `${Math.ceil(messages.length / 2)} 轮问答` : (isDiagMode ? '已关联本次诊断' : '随题解答')}
          </span>
        </div>
        <button
          type="button"
          style={{
            background: 'none',
            border: 'none',
            fontSize: 12,
            color: isDiagMode ? '#9a3412' : 'var(--muted)',
            cursor: 'pointer',
            fontWeight: 500,
          }}
          aria-label={isExpanded ? '收起追问' : '展开追问'}
        >
          {isExpanded ? '收起 ▲' : '展开追问 ▼'}
        </button>
      </div>

      {isExpanded && (
        <div style={{ padding: 12 }}>
          {/* Quick-Prompt Chips */}
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 11, color: isDiagMode ? '#9a3412' : '#64748b', marginBottom: 6, fontWeight: 600 }}>
              {isDiagMode ? '针对本次错因快捷追问：' : '快捷追问：'}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {quickChips.map((chip, idx) => (
                <button
                  key={idx}
                  type="button"
                  disabled={loading}
                  onClick={() => void handleSend(chip)}
                  style={{
                    background: isDiagMode ? '#fff7ed' : '#f1f5f9',
                    border: isDiagMode ? '1px solid #fed7aa' : '1px solid #cbd5e1',
                    borderRadius: 14,
                    padding: '3px 10px',
                    fontSize: 11,
                    color: isDiagMode ? '#9a3412' : '#334155',
                    cursor: loading ? 'not-allowed' : 'pointer',
                    transition: 'all 0.15s ease',
                    textAlign: 'left',
                    fontWeight: 500,
                  }}
                  onMouseEnter={e => {
                    if (!loading) {
                      e.currentTarget.style.background = isDiagMode ? '#ffedd5' : '#e2e8f0';
                      e.currentTarget.style.borderColor = isDiagMode ? '#f97316' : '#94a3b8';
                    }
                  }}
                  onMouseLeave={e => {
                    if (!loading) {
                      e.currentTarget.style.background = isDiagMode ? '#fff7ed' : '#f1f5f9';
                      e.currentTarget.style.borderColor = isDiagMode ? '#fed7aa' : '#cbd5e1';
                    }
                  }}
                >
                  {chip}
                </button>
              ))}
            </div>
          </div>

          {/* Conversation history area */}
          {fetchingHistory ? (
            <div style={{ fontSize: 12, color: 'var(--muted)', padding: '12px 0', textAlign: 'center' }}>
              正在加载历史答疑…
            </div>
          ) : messages.length === 0 ? (
            <div
              style={{
                fontSize: 12,
                color: isDiagMode ? '#9a3412' : '#64748b',
                background: isDiagMode ? '#fffaf5' : '#f8fafc',
                padding: '10px 12px',
                borderRadius: 6,
                border: isDiagMode ? '1px dashed #fed7aa' : '1px dashed #cbd5e1',
                marginBottom: 10,
                textAlign: 'center',
              }}
            >
              {isDiagMode
                ? `对「${diagnosis?.error_label}」的判定依据、思维误区或巩固方法存疑？点击上方气泡或直接输入追问。`
                : '对题目推导、选项差异或公式有任何疑问？随时在下方输入或点击快捷追问。'}
            </div>
          ) : (
            <div
              ref={scrollRef}
              style={{
                maxHeight: 280,
                overflowY: 'auto',
                display: 'flex',
                flexDirection: 'column',
                gap: 10,
                padding: '6px 4px',
                marginBottom: 10,
              }}
            >
              {messages.map((m, idx) => {
                const isUser = m.role === 'user';
                return (
                  <div
                    key={m.id || idx}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: isUser ? 'flex-end' : 'flex-start',
                    }}
                  >
                    <div
                      style={{
                        fontSize: 11,
                        color: isUser ? '#15803d' : (isDiagMode ? '#9a3412' : '#64748b'),
                        marginBottom: 2,
                        padding: '0 4px',
                        fontWeight: 600,
                      }}
                    >
                      {isUser ? '👤 你的追问' : '🤖 AI 助教解答'}
                    </div>
                    <div
                      style={{
                        maxWidth: '92%',
                        background: isUser ? '#ecfdf5' : '#f8fafc',
                        border: isUser ? '1px solid #a7f3d0' : '1px solid #e2e8f0',
                        color: isUser ? '#065f46' : '#1e293b',
                        borderRadius: isUser ? '10px 10px 2px 10px' : '10px 10px 10px 2px',
                        padding: '8px 12px',
                        boxShadow: '0 1px 2px rgba(0,0,0,0.03)',
                      }}
                    >
                      {isUser ? (
                        <div style={{ fontSize: 13, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
                          {m.content}
                        </div>
                      ) : (
                        <TeachingContent text={m.content} />
                      )}
                    </div>
                  </div>
                );
              })}

              {loading && (
                <div
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                  }}
                >
                  <div style={{ fontSize: 11, color: isDiagMode ? '#9a3412' : '#64748b', marginBottom: 2, padding: '0 4px', fontWeight: 600 }}>
                    🤖 AI 助教
                  </div>
                  <div
                    style={{
                      background: '#f8fafc',
                      border: '1px solid #e2e8f0',
                      borderRadius: '10px 10px 10px 2px',
                      padding: '8px 14px',
                      fontSize: 12,
                      color: '#475569',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                    }}
                  >
                    <span style={{ display: 'inline-block' }}>⏳</span>
                    <span>AI 助教正在结合错因深度思考解答…</span>
                  </div>
                </div>
              )}
            </div>
          )}

          {error && (
            <div
              style={{
                fontSize: 12,
                color: '#b91c1c',
                background: '#fef2f2',
                border: '1px solid #fecaca',
                padding: '6px 10px',
                borderRadius: 4,
                marginBottom: 8,
              }}
            >
              {error}
            </div>
          )}

          {/* Input & Action area */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <textarea
              ref={textareaRef}
              value={input}
              disabled={loading}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={isDiagMode ? `输入你想对「${diagnosis?.error_label || '错因'}」追问的问题（Enter 发送）…` : '输入你想追问的问题（Enter 发送）…'}
              rows={2}
              style={{
                flex: 1,
                padding: '8px 10px',
                fontSize: 13,
                lineHeight: 1.5,
                border: isDiagMode ? '1px solid #fed7aa' : '1px solid #cbd5e1',
                borderRadius: 6,
                resize: 'none',
                outline: 'none',
                fontFamily: 'inherit',
                transition: 'border-color 0.15s ease',
              }}
              onFocus={e => {
                e.currentTarget.style.borderColor = isDiagMode ? '#f97316' : 'var(--accent, #2563eb)';
              }}
              onBlur={e => {
                e.currentTarget.style.borderColor = isDiagMode ? '#fed7aa' : '#cbd5e1';
              }}
            />
            <button
              type="button"
              className="primary"
              disabled={loading || !input.trim()}
              onClick={() => void handleSend()}
              style={{
                height: 48,
                padding: '0 16px',
                fontSize: 13,
                fontWeight: 600,
                borderRadius: 6,
                cursor: loading || !input.trim() ? 'not-allowed' : 'pointer',
                whiteSpace: 'nowrap',
                background: isDiagMode ? '#ea580c' : undefined,
                borderColor: isDiagMode ? '#c2410c' : undefined,
              }}
            >
              {loading ? '思考中…' : '发送追问'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
