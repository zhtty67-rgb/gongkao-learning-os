'use client';

import { useEffect, useState } from 'react';
import { listNotes, saveNote, deleteNote, associateNoteWithNode, UserNote, ApiError } from './api';

interface QuestionNoteBoxProps {
  questionId: string;
  attemptId?: string | null;
  module?: string | null;
  knowledgeNodeId?: string | null;
  knowledgeNodeCode?: string | null;
}

export function QuestionNoteBox({
  questionId,
  attemptId,
  module,
  knowledgeNodeId,
  knowledgeNodeCode,
}: QuestionNoteBoxProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [notes, setNotes] = useState<UserNote[]>([]);
  const [loading, setLoading] = useState(false);
  const [content, setContent] = useState('');
  const [title, setTitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null);
  const [editingVersion, setEditingVersion] = useState<number | null>(null);
  const [conflictNote, setConflictNote] = useState<UserNote | null>(null);

  const fetchNotes = async () => {
    if (!questionId) return;
    setLoading(true);
    setError('');
    try {
      const res = await listNotes({ question_id: questionId });
      setNotes(res.items || []);
    } catch (err: any) {
      setError(err?.message || '加载笔记失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (questionId) {
      fetchNotes();
    }
  }, [questionId]);

  const handleSave = async (overrideVersion?: number) => {
    if (!content.trim()) {
      setError('笔记内容不能为空');
      return;
    }
    setSaving(true);
    setError('');
    setConflictNote(null);
    try {
      const verToUse = overrideVersion !== undefined ? overrideVersion : (editingVersion ?? undefined);
      if (editingNoteId) {
        await saveNote({
          note_id: editingNoteId,
          expected_version: verToUse,
          content: content.trim(),
          title: title.trim() || "", // 允许显式清空标题
        });
        setEditingNoteId(null);
        setEditingVersion(null);
      } else {
        await saveNote({
          note_type: 'question',
          content: content.trim(),
          title: title.trim() || undefined,
          question_id: questionId,
          attempt_id: attemptId || undefined,
          knowledge_node_id: knowledgeNodeId || undefined,
          knowledge_node_code: knowledgeNodeCode || undefined,
          module: module || undefined,
          source_type: 'manual',
        });
      }
      setContent('');
      setTitle('');
      await fetchNotes();
    } catch (err: any) {
      // 保留用户输入，避免输入丢失
      if ((err?.isConflict || err?.status === 409 || err instanceof ApiError && err.isConflict) && err?.currentNote) {
        setConflictNote(err.currentNote);
        setError('⚠️ 该笔记已在其他页面更新，为防止覆盖，当前编辑已暂停。请核对下方最新内容。');
      } else {
        setError(err?.message || '保存失败，已保留您的输入内容');
      }
    } finally {
      setSaving(false);
    }
  };

  const handleStartEdit = (note: UserNote) => {
    setEditingNoteId(note.id);
    setEditingVersion(note.version);
    setContent(note.content);
    setTitle(note.title || '');
    setConflictNote(null);
    setIsOpen(true);
  };

  const handleDelete = async (noteId: string) => {
    if (!window.confirm('确定要删除这条笔记吗？')) return;
    try {
      await deleteNote(noteId);
      setNotes(prev => prev.filter(n => n.id !== noteId));
      if (editingNoteId === noteId) {
        setEditingNoteId(null);
        setEditingVersion(null);
        setContent('');
        setTitle('');
        setConflictNote(null);
      }
    } catch (err: any) {
      alert(err?.message || '删除失败');
    }
  };

  const handleAssociateNode = async (noteId: string, targetNodeId: string | null) => {
    try {
      const targetNote = notes.find(n => n.id === noteId);
      await associateNoteWithNode(noteId, targetNodeId, targetNote?.version);
      await fetchNotes();
      if (targetNodeId) {
        alert('已成功同步关联至考点笔记！在考点详情页也可查看。');
      } else {
        alert('已取消考点关联。');
      }
    } catch (err: any) {
      alert(err?.message || '关联考点失败');
    }
  };

  return (
    <div style={{ marginTop: 14, background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '12px 14px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: '#1e293b' }}>
            📝 我的心得与备忘
          </span>
          <span style={{ fontSize: 11, padding: '1px 6px', background: notes.length > 0 ? '#fef3c7' : '#f1f5f9', color: notes.length > 0 ? '#b45309' : '#64748b', borderRadius: 10 }}>
            {notes.length} 条
          </span>
        </div>
        <button
          type="button"
          onClick={() => {
            setIsOpen(!isOpen);
            if (!isOpen && editingNoteId) {
              setEditingNoteId(null);
              setEditingVersion(null);
              setContent('');
              setTitle('');
              setConflictNote(null);
            }
          }}
          style={{
            fontSize: 12,
            padding: '3px 10px',
            background: isOpen ? '#f1f5f9' : '#fff7ed',
            color: isOpen ? '#475569' : '#ea580c',
            border: isOpen ? '1px solid #cbd5e1' : '1px solid #fdba74',
            borderRadius: 6,
            cursor: 'pointer',
            fontWeight: 600,
          }}
        >
          {isOpen ? '收起输入' : '+ 记一笔'}
        </button>
      </div>

      {/* 笔记编辑框 */}
      {isOpen && (
        <div style={{ marginTop: 10, padding: 10, background: '#f8fafc', borderRadius: 6, border: '1px solid #cbd5e1' }}>
          <div style={{ marginBottom: 6 }}>
            <input
              type="text"
              placeholder="心得主题（可选，清空则删除标题）"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              style={{
                width: '100%',
                padding: '6px 8px',
                fontSize: 12,
                border: '1px solid #cbd5e1',
                borderRadius: 4,
                boxSizing: 'border-box',
                outline: 'none',
              }}
            />
          </div>
          <div>
            <textarea
              rows={3}
              placeholder="写下你当时怎么想的、学到了什么技巧、下次做这类题要注意什么..."
              value={content}
              onChange={(e) => setContent(e.target.value)}
              style={{
                width: '100%',
                padding: '6px 8px',
                fontSize: 12.5,
                lineHeight: 1.6,
                border: '1px solid #cbd5e1',
                borderRadius: 4,
                boxSizing: 'border-box',
                outline: 'none',
                resize: 'vertical',
              }}
            />
          </div>

          {/* 冲突解决面板 */}
          {conflictNote && (
            <div style={{ marginTop: 8, padding: 8, background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 6, fontSize: 12 }}>
              <div style={{ fontWeight: 700, color: '#991b1b', marginBottom: 4 }}>
                ⚠️ 远端最新版本（更新于 {new Date(conflictNote.updated_at).toLocaleTimeString('zh-CN')}）：
              </div>
              <div style={{ color: '#450a0a', whiteSpace: 'pre-wrap', maxHeight: 90, overflowY: 'auto', background: '#fff', padding: 6, borderRadius: 4, border: '1px solid #fee2e2' }}>
                {conflictNote.content}
              </div>
              <div style={{ marginTop: 6, display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  onClick={() => {
                    setContent(conflictNote.content);
                    setTitle(conflictNote.title || '');
                    setEditingVersion(conflictNote.version);
                    setConflictNote(null);
                    setError('');
                  }}
                  style={{ padding: '3px 8px', fontSize: 11, background: '#fff', border: '1px solid #cbd5e1', borderRadius: 4, cursor: 'pointer' }}
                >
                  放弃我的修改，载入最新版
                </button>
                <button
                  type="button"
                  onClick={() => handleSave(conflictNote.version)}
                  style={{ padding: '3px 8px', fontSize: 11, background: '#dc2626', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontWeight: 600 }}
                >
                  以我的修改强制覆盖
                </button>
              </div>
            </div>
          )}

          {error && !conflictNote && <div style={{ fontSize: 11, color: '#dc2626', marginTop: 4 }}>⚠️ {error}</div>}

          <div style={{ marginTop: 8, display: 'flex', gap: 6, justifyContent: 'flex-end', alignItems: 'center' }}>
            {editingNoteId && (
              <button
                type="button"
                onClick={() => {
                  setEditingNoteId(null);
                  setEditingVersion(null);
                  setContent('');
                  setTitle('');
                  setConflictNote(null);
                  setError('');
                }}
                style={{
                  padding: '4px 10px',
                  fontSize: 11.5,
                  background: '#fff',
                  border: '1px solid #cbd5e1',
                  borderRadius: 4,
                  cursor: 'pointer',
                  color: '#475569',
                }}
              >
                取消编辑
              </button>
            )}
            <button
              type="button"
              disabled={saving || !content.trim()}
              onClick={() => handleSave()}
              style={{
                padding: '4px 14px',
                fontSize: 12,
                background: saving ? '#94a3b8' : '#ea580c',
                color: '#fff',
                border: 'none',
                borderRadius: 4,
                cursor: saving ? 'not-allowed' : 'pointer',
                fontWeight: 600,
              }}
            >
              {saving ? '保存中…' : editingNoteId ? '更新笔记' : '保存心得'}
            </button>
          </div>
        </div>
      )}

      {/* 已有笔记展示列表 */}
      {notes.length > 0 && (
        <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {notes.map(note => {
            const isClipping = note.source_type === 'review_ai_message' || note.source_type === 'review_user_message';
            return (
              <div
                key={note.id}
                style={{
                  padding: '8px 10px',
                  background: isClipping ? '#f0fdf4' : '#fafafa',
                  border: isClipping ? '1px solid #bbf7d0' : '1px solid #e5e7eb',
                  borderRadius: 6,
                  fontSize: 12.5,
                  lineHeight: 1.6,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {isClipping ? (
                      <span style={{ fontSize: 10, padding: '1px 5px', background: '#dcfce7', color: '#15803d', borderRadius: 4, fontWeight: 600 }}>
                        📌 复盘收藏
                      </span>
                    ) : (
                      <span style={{ fontSize: 10, padding: '1px 5px', background: '#ffedd5', color: '#c2410c', borderRadius: 4, fontWeight: 600 }}>
                        💡 本题心得
                      </span>
                    )}
                    {note.title && <strong style={{ color: '#1e293b' }}>{note.title}</strong>}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#94a3b8' }}>
                    <span>v{note.version} · {new Date(note.updated_at).toLocaleDateString('zh-CN')}</span>
                    <button
                      type="button"
                      onClick={() => handleStartEdit(note)}
                      title="编辑"
                      style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#0284c7', fontSize: 11 }}
                    >
                      编辑
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(note.id)}
                      title="删除"
                      style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#ef4444', fontSize: 11 }}
                    >
                      删除
                    </button>
                  </div>
                </div>

                <div style={{ color: '#334155', whiteSpace: 'pre-wrap' }}>
                  {note.content}
                </div>

                {/* 关联考点信息 */}
                <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11, borderTop: '1px dashed #e2e8f0', paddingTop: 4 }}>
                  <div style={{ color: '#64748b' }}>
                    {note.node_name ? (
                      <span>🔗 关联考点：<strong style={{ color: '#0369a1' }}>{note.node_name}</strong></span>
                    ) : (
                      <span>未关联具体考点</span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 4 }}>
                    {!note.knowledge_node_id && knowledgeNodeId ? (
                      <button
                        type="button"
                        onClick={() => handleAssociateNode(note.id, knowledgeNodeId)}
                        style={{
                          padding: '1px 6px',
                          fontSize: 10.5,
                          background: '#e0f2fe',
                          color: '#0369a1',
                          border: '1px solid #bae6fd',
                          borderRadius: 3,
                          cursor: 'pointer',
                        }}
                      >
                        同步到本题考点
                      </button>
                    ) : note.knowledge_node_id ? (
                      <button
                        type="button"
                        onClick={() => handleAssociateNode(note.id, null)}
                        style={{
                          padding: '1px 6px',
                          fontSize: 10.5,
                          background: '#f1f5f9',
                          color: '#64748b',
                          border: '1px solid #cbd5e1',
                          borderRadius: 3,
                          cursor: 'pointer',
                        }}
                      >
                        取消考点关联
                      </button>
                    ) : null}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
