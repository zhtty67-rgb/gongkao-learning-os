'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { listNotes, saveNote, deleteNote, UserNote, ApiError } from '../../lib/api';

const MODULE_OPTIONS = ['全部', '资料分析', '数量关系', '言语理解', '判断推理', '政治理论', '常识判断', '申论'];

export default function NotesPage() {
  const [notes, setNotes] = useState<UserNote[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selectedModule, setSelectedModule] = useState('全部');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedType, setSelectedType] = useState('all');

  // 新建/编辑笔记弹窗状态
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingNote, setEditingNote] = useState<UserNote | null>(null);
  const [modalTitle, setModalTitle] = useState('');
  const [modalContent, setModalContent] = useState('');
  const [modalModule, setModalModule] = useState('资料分析');
  const [modalSaving, setModalSaving] = useState(false);
  const [modalError, setModalError] = useState('');
  const [modalConflictNote, setModalConflictNote] = useState<UserNote | null>(null);

  const fetchNotes = async (queryOverride?: string) => {
    setLoading(true);
    try {
      const params: any = { limit: 100 };
      if (selectedModule !== '全部') {
        params.module = selectedModule;
      }
      if (selectedType !== 'all') {
        params.note_type = selectedType;
      }
      const effectiveQuery = queryOverride !== undefined ? queryOverride : searchQuery;
      if (effectiveQuery.trim()) {
        params.query = effectiveQuery.trim();
      }
      const res = await listNotes(params);
      let combined = [...(res.items || [])];
      if (res.shenlun_notes && (selectedModule === '全部' || selectedModule === '申论')) {
        combined = [...combined, ...res.shenlun_notes];
      }
      setNotes(combined);
      setTotalCount(combined.length);
    } catch (err) {
      console.error('Failed to load notes', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchNotes();
  }, [selectedModule, selectedType]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchNotes();
  };

  const handleOpenCreate = () => {
    setEditingNote(null);
    setModalTitle('');
    setModalContent('');
    setModalModule(selectedModule === '全部' ? '资料分析' : selectedModule);
    setModalError('');
    setModalConflictNote(null);
    setShowCreateModal(true);
  };

  const handleOpenEdit = (note: UserNote) => {
    if (note.is_shenlun_live) {
      alert('本条为申论练习实时梳理笔记，请在申论工作台中直接修改。');
      return;
    }
    setEditingNote(note);
    setModalTitle(note.title || '');
    setModalContent(note.content || '');
    setModalModule(note.module || '资料分析');
    setModalError('');
    setModalConflictNote(null);
    setShowCreateModal(true);
  };

  const handleSaveModal = async (overrideVersion?: number) => {
    if (!modalContent.trim()) {
      setModalError('笔记内容不能为空');
      return;
    }
    setModalSaving(true);
    setModalError('');
    setModalConflictNote(null);
    try {
      const verToUse = overrideVersion !== undefined ? overrideVersion : editingNote?.version;
      if (editingNote) {
        await saveNote({
          note_id: editingNote.id,
          expected_version: verToUse,
          title: modalTitle.trim() || "",
          content: modalContent.trim(),
          module: modalModule,
        });
      } else {
        await saveNote({
          note_type: 'knowledge_node',
          title: modalTitle.trim() || undefined,
          content: modalContent.trim(),
          module: modalModule,
          source_type: 'manual',
        });
      }
      setShowCreateModal(false);
      await fetchNotes();
    } catch (err: any) {
      if ((err?.isConflict || err?.status === 409 || err instanceof ApiError && err.isConflict) && err?.currentNote) {
        setModalConflictNote(err.currentNote);
        setModalError('⚠️ 该笔记已在其他页面更新，为防止覆盖，当前编辑已暂停。请核对下方最新内容。');
      } else {
        setModalError(err?.message || '保存失败，已保留输入内容');
      }
    } finally {
      setModalSaving(false);
    }
  };

  const handleDelete = async (note: UserNote) => {
    if (note.is_shenlun_live) {
      alert('申论练习梳理笔记请在申论工作台完成修改或清空。');
      return;
    }
    if (!window.confirm('确定要删除这条笔记吗？')) return;
    try {
      await deleteNote(note.id);
      await fetchNotes();
    } catch (err: any) {
      alert(err?.message || '删除失败');
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
          <Link href="/notes" className="active">我的笔记</Link>
          <Link href="/exam">全真模考</Link>
          <Link href="/shenlun">申论工作台</Link>
          <Link href="/importer">题库导入</Link>
        <Link href="/settings">设置</Link></nav>
        <span className="local">● 本地学习空间</span>
      </header>

      <div className="intro" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <span className="eyebrow">NOTES / 我的笔记与感悟</span>
            <h1 style={{ margin: '4px 0 8px 0', fontSize: 24 }}>随时沉淀，化做题为内功。</h1>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: 13.5 }}>
              汇总你的本题心得、名师复盘切片收藏、考点精要与申论梳理，与题目和知识树多端同步。
            </p>
          </div>
          <button
            type="button"
            onClick={handleOpenCreate}
            style={{
              padding: '8px 18px',
              fontSize: 13,
              borderRadius: 8,
              background: '#ea580c',
              color: '#fff',
              border: 'none',
              fontWeight: 700,
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              boxShadow: '0 2px 4px rgba(234, 88, 12, 0.2)',
            }}
          >
            <span>+</span> 记一笔心得
          </button>
        </div>
      </div>

      {/* 模块筛选胶囊栏 */}
      <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 6, marginBottom: 14 }}>
        {MODULE_OPTIONS.map((mod) => {
          const isSelected = selectedModule === mod;
          return (
            <button
              key={mod}
              type="button"
              onClick={() => setSelectedModule(mod)}
              style={{
                padding: '6px 14px',
                fontSize: 12.5,
                borderRadius: 20,
                border: isSelected ? '1.5px solid #ea580c' : '1px solid #cbd5e1',
                background: isSelected ? '#ffedd5' : '#fff',
                color: isSelected ? '#9a3412' : '#475569',
                fontWeight: isSelected ? 700 : 500,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              {mod}
            </button>
          );
        })}
      </div>

      {/* 搜索与分类栏 */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 16 }}>
        <form onSubmit={handleSearchSubmit} style={{ flex: 1, minWidth: 260, display: 'flex', gap: 6 }}>
          <input
            type="text"
            placeholder="搜索心得感悟、解题突破口、错因备忘..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              flex: 1,
              padding: '7px 12px',
              fontSize: 13,
              borderRadius: 6,
              border: '1px solid #cbd5e1',
              outline: 'none',
            }}
          />
          <button
            type="submit"
            style={{
              padding: '7px 14px',
              fontSize: 12.5,
              borderRadius: 6,
              background: '#0284c7',
              color: '#fff',
              border: 'none',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            搜索
          </button>
          {searchQuery && (
            <button
              type="button"
              onClick={() => { setSearchQuery(''); fetchNotes(''); }}
              style={{
                padding: '7px 10px',
                fontSize: 12,
                borderRadius: 6,
                background: '#f1f5f9',
                color: '#64748b',
                border: '1px solid #cbd5e1',
                cursor: 'pointer',
              }}
            >
              重置
            </button>
          )}
        </form>

        <select
          value={selectedType}
          onChange={(e) => setSelectedType(e.target.value)}
          style={{
            padding: '7px 10px',
            fontSize: 12.5,
            borderRadius: 6,
            border: '1px solid #cbd5e1',
            background: '#fff',
            color: '#334155',
            outline: 'none',
          }}
        >
          <option value="all">全部笔记类型</option>
          <option value="question">本题心得</option>
          <option value="dialogue_clipping">复盘切片收藏</option>
          <option value="knowledge_node">考点笔记</option>
          <option value="shenlun_summary">申论梳理</option>
        </select>
      </div>

      {/* 笔记卡片列表 */}
      {loading ? (
        <div style={{ padding: 40, textAlign: 'center', color: '#94a3b8' }}>正在读取笔记…</div>
      ) : notes.length === 0 ? (
        <div style={{ padding: '48px 24px', textAlign: 'center', background: '#fff', borderRadius: 12, border: '1px dashed #cbd5e1' }}>
          <div style={{ fontSize: 32, marginBottom: 8 }}>📝</div>
          <h3 style={{ margin: '0 0 6px 0', fontSize: 16, color: '#334155' }}>暂无相关笔记记录</h3>
          <p style={{ margin: 0, fontSize: 13, color: '#64748b' }}>
            在行测训练、到期复习或错题复盘中点击“记一笔”或“📌 收藏”，随时沉淀你的解题思考。
          </p>
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 12 }}>
          {notes.map((note) => {
            const isClip = note.source_type === 'review_ai_message' || note.source_type === 'review_user_message';
            const isShenlun = note.note_type === 'shenlun_summary';

            let typeBadgeBg = '#ffedd5';
            let typeBadgeColor = '#c2410c';
            let typeLabel = '💡 本题心得';

            if (isClip) {
              typeBadgeBg = '#dcfce7';
              typeBadgeColor = '#15803d';
              typeLabel = note.source_type === 'review_ai_message' ? '📌 名师点拨收藏' : '📌 自述记录收藏';
            } else if (isShenlun) {
              typeBadgeBg = '#e0e7ff';
              typeBadgeColor = '#4338ca';
              typeLabel = '📑 申论梳理';
            } else if (note.note_type === 'knowledge_node') {
              typeBadgeBg = '#e0f2fe';
              typeBadgeColor = '#0369a1';
              typeLabel = '🎯 考点笔记';
            }

            return (
              <div
                key={note.id}
                style={{
                  background: '#fff',
                  border: isClip ? '1px solid #bbf7d0' : isShenlun ? '1px solid #c7d2fe' : '1px solid #e2e8f0',
                  borderRadius: 10,
                  padding: '14px 16px',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.02)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8, flexWrap: 'wrap', gap: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ fontSize: 11, padding: '2px 7px', background: typeBadgeBg, color: typeBadgeColor, borderRadius: 4, fontWeight: 700 }}>
                      {typeLabel}
                    </span>
                    {note.module && (
                      <span style={{ fontSize: 11, padding: '2px 6px', background: '#f1f5f9', color: '#475569', borderRadius: 4 }}>
                        {note.module}
                      </span>
                    )}
                    {note.title && (
                      <strong style={{ fontSize: 13.5, color: '#0f172a' }}>
                        {note.title}
                      </strong>
                    )}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: '#94a3b8' }}>
                    <span>{new Date(note.updated_at).toLocaleDateString('zh-CN')}</span>
                    {!isShenlun && (
                      <>
                        <button
                          type="button"
                          onClick={() => handleOpenEdit(note)}
                          style={{ background: 'none', border: 'none', color: '#0284c7', cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
                        >
                          编辑
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(note)}
                          style={{ background: 'none', border: 'none', color: '#ef4444', cursor: 'pointer', fontSize: 12 }}
                        >
                          删除
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {/* 笔记正文 */}
                <div style={{ fontSize: 13.5, lineHeight: 1.7, color: '#334155', whiteSpace: 'pre-wrap', marginBottom: 8 }}>
                  {note.content}
                </div>

                {/* 来源题目 / 考点追溯 */}
                {(note.question_stem || note.node_name || note.source_quote) && (
                  <div style={{ background: '#f8fafc', borderRadius: 6, padding: '8px 10px', fontSize: 11.5, color: '#64748b', display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {note.question_stem && (
                      <div>
                        <strong style={{ color: '#475569' }}>来源题目：</strong>
                        <span>{note.question_stem.slice(0, 90)}...</span>
                      </div>
                    )}
                    {note.node_name && (
                      <div>
                        <strong style={{ color: '#475569' }}>关联考点：</strong>
                        <span style={{ color: '#0284c7', fontWeight: 600 }}>{note.node_name}</span>
                      </div>
                    )}
                    {isShenlun && note.source_quote && (
                      <div>
                        <strong style={{ color: '#475569' }}>申论篇目：</strong>
                        <span>{note.source_quote}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 新建/编辑笔记弹窗 Modal */}
      {showCreateModal && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            width: '100vw',
            height: '100vh',
            background: 'rgba(15, 23, 42, 0.45)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 999,
            padding: 16,
          }}
        >
          <div
            style={{
              background: '#fff',
              borderRadius: 12,
              width: '100%',
              maxWidth: 520,
              padding: 20,
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: '#0f172a' }}>
                {editingNote ? '编辑感悟笔记' : '记一笔新心得'}
              </h3>
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                style={{ background: 'none', border: 'none', fontSize: 18, color: '#94a3b8', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', gap: 8 }}>
                <select
                  value={modalModule}
                  onChange={(e) => setModalModule(e.target.value)}
                  style={{
                    padding: '7px 10px',
                    fontSize: 12.5,
                    border: '1px solid #cbd5e1',
                    borderRadius: 6,
                    background: '#fff',
                    outline: 'none',
                  }}
                >
                  <option value="资料分析">资料分析</option>
                  <option value="数量关系">数量关系</option>
                  <option value="言语理解">言语理解</option>
                  <option value="判断推理">判断推理</option>
                  <option value="政治理论">政治理论</option>
                  <option value="常识判断">常识判断</option>
                  <option value="申论">申论</option>
                </select>

                <input
                  type="text"
                  placeholder="心得主题（可选，如：两期比重快速秒杀技巧）"
                  value={modalTitle}
                  onChange={(e) => setModalTitle(e.target.value)}
                  style={{
                    flex: 1,
                    padding: '7px 10px',
                    fontSize: 12.5,
                    border: '1px solid #cbd5e1',
                    borderRadius: 6,
                    outline: 'none',
                  }}
                />
              </div>

              <textarea
                rows={5}
                placeholder="记录做题时的思维过程、踩坑教训、核心公式速算备忘..."
                value={modalContent}
                onChange={(e) => setModalContent(e.target.value)}
                style={{
                  width: '100%',
                  padding: '10px',
                  fontSize: 13,
                  lineHeight: 1.6,
                  border: '1px solid #cbd5e1',
                  borderRadius: 6,
                  outline: 'none',
                  boxSizing: 'border-box',
                  resize: 'vertical',
                }}
              />

              {modalConflictNote && (
                <div style={{ padding: 10, background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 6, fontSize: 12 }}>
                  <div style={{ fontWeight: 700, color: '#991b1b', marginBottom: 4 }}>
                    ⚠️ 该笔记已在其他页面更新，为防止覆盖，当前编辑已暂停。远端最新版本（v{modalConflictNote.version} · 更新于 {new Date(modalConflictNote.updated_at).toLocaleTimeString('zh-CN')}）：
                  </div>
                  <div style={{ color: '#450a0a', whiteSpace: 'pre-wrap', maxHeight: 90, overflowY: 'auto', background: '#fff', padding: 6, borderRadius: 4, border: '1px solid #fee2e2' }}>
                    {modalConflictNote.content}
                  </div>
                  <div style={{ marginTop: 8, display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                    <button
                      type="button"
                      onClick={() => {
                        setModalContent(modalConflictNote.content);
                        setModalTitle(modalConflictNote.title || '');
                        setEditingNote(modalConflictNote);
                        setModalConflictNote(null);
                        setModalError('');
                      }}
                      style={{ padding: '3px 8px', fontSize: 11, background: '#fff', border: '1px solid #cbd5e1', borderRadius: 4, cursor: 'pointer' }}
                    >
                      放弃我的修改，载入最新版
                    </button>
                    <button
                      type="button"
                      onClick={() => handleSaveModal(modalConflictNote.version)}
                      style={{ padding: '3px 8px', fontSize: 11, background: '#dc2626', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontWeight: 600 }}
                    >
                      以我的修改强制覆盖
                    </button>
                  </div>
                </div>
              )}

              {modalError && !modalConflictNote && <div style={{ fontSize: 12, color: '#dc2626' }}>⚠️ {modalError}</div>}
            </div>

            <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                style={{
                  padding: '7px 14px',
                  fontSize: 12.5,
                  borderRadius: 6,
                  background: '#f1f5f9',
                  color: '#475569',
                  border: '1px solid #cbd5e1',
                  cursor: 'pointer',
                }}
              >
                取消
              </button>
              <button
                type="button"
                disabled={modalSaving || !modalContent.trim()}
                onClick={() => handleSaveModal()}
                style={{
                  padding: '7px 18px',
                  fontSize: 12.5,
                  borderRadius: 6,
                  background: modalSaving ? '#94a3b8' : '#ea580c',
                  color: '#fff',
                  border: 'none',
                  fontWeight: 600,
                  cursor: modalSaving ? 'not-allowed' : 'pointer',
                }}
              >
                {modalSaving ? '保存中…' : '保存笔记'}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
