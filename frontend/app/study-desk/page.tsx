'use client';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../../lib/api';

type MasteryNode = { id: string; name: string; module: string | null };
type Note = { id: string; content: string; created_at: string; metadata?: Record<string, any> };

const POS_KEY = (video: string) => `gongkao-desk:pos:${video}`;

function fmt(seconds: number): string {
  const s = Math.floor(seconds);
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

export default function StudyDeskPage() {
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoName, setVideoName] = useState('');
  const [nodes, setNodes] = useState<MasteryNode[]>([]);
  const [moduleFilter, setModuleFilter] = useState('');
  const [search, setSearch] = useState('');
  const [selectedNode, setSelectedNode] = useState<MasteryNode | null>(null);
  const [noteText, setNoteText] = useState('');
  const [notes, setNotes] = useState<Note[]>([]);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [resumed, setResumed] = useState<number | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const lastSave = useRef(0);

  useEffect(() => {
    api<{ mastery: { nodes: MasteryNode[] } }>('/mastery')
      .then(d => setNodes(d.mastery.nodes.filter(n => n.module)))
      .catch(() => setMsg({ type: 'err', text: '知识节点读取失败，请确认后端已启动。' }));
  }, []);

  const loadNotes = useCallback(async (nodeId: string) => {
    try {
      const d = await api<{ notes: Note[] }>(`/notes?knowledge_node_id=${encodeURIComponent(nodeId)}&limit=50`);
      setNotes(d.notes || []);
    } catch { setNotes([]); }
  }, []);

  useEffect(() => {
    if (selectedNode) loadNotes(selectedNode.id);
  }, [selectedNode, loadNotes]);

  const pickVideo = (file: File | null) => {
    if (!file) return;
    if (videoUrl) URL.revokeObjectURL(videoUrl);
    setVideoName(file.name);
    setVideoUrl(URL.createObjectURL(file));
    setResumed(null);
  };

  // 续播：同名单视频恢复上次位置（localStorage，本机优先）
  const onLoadedMetadata = () => {
    const saved = Number(localStorage.getItem(POS_KEY(videoName)) || 0);
    const v = videoRef.current;
    if (v && saved > 5 && Number.isFinite(saved)) {
      v.currentTime = saved;
      setResumed(saved);
    }
  };

  // 播放位置节流保存（每 5 秒）
  const onTimeUpdate = () => {
    const v = videoRef.current;
    if (!v || !videoName) return;
    const now = Date.now();
    if (now - lastSave.current < 5000) return;
    lastSave.current = now;
    localStorage.setItem(POS_KEY(videoName), String(Math.floor(v.currentTime)));
  };

  const saveNote = async () => {
    const v = videoRef.current;
    if (!selectedNode) { setMsg({ type: 'err', text: '先选择要关联的知识点。' }); return; }
    const text = noteText.trim();
    if (!text) { setMsg({ type: 'err', text: '笔记内容不能为空。' }); return; }
    setSaving(true);
    try {
      await api('/notes', {
        note_type: 'knowledge_node',
        knowledge_node_id: selectedNode.id,
        module: selectedNode.module,
        content: v ? `[${fmt(v.currentTime)}] ${text}` : text,
        metadata: { origin: 'course_desk', video: videoName || null, position_seconds: v ? Math.floor(v.currentTime) : null },
      });
      setNoteText('');
      setMsg({ type: 'ok', text: `已保存到「${selectedNode.name}」的考点笔记。` });
      loadNotes(selectedNode.id);
    } catch (exc) {
      setMsg({ type: 'err', text: exc instanceof ApiError ? exc.message : '保存失败，请重试。' });
    } finally { setSaving(false); }
  };

  const modules = Array.from(new Set(nodes.map(n => n.module).filter(Boolean) as string[]));
  const filtered = nodes
    .filter(n => !moduleFilter || n.module === moduleFilter)
    .filter(n => !search.trim() || n.name.includes(search.trim()))
    .slice(0, 120);
  const deskNotes = notes.filter(n => n.metadata?.origin === 'course_desk' || true).slice().reverse();

  return (
    <main>
      <header>
        <Link href="/dashboard" className="brand"><span className="brand-icon">学</span>公考 Learning OS</Link>
        <nav>
          <Link href="/dashboard">学习概览</Link><Link href="/framework">知识框架</Link><Link href="/study">学习任务</Link><Link href="/study-desk" className="active">看课工作台</Link><Link href="/teaching">自适应教学</Link><Link href="/review">到期复习</Link><Link href="/notes">我的笔记</Link><Link href="/settings">系统设置</Link>
        </nav>
        <span className="local">● 本地学习空间</span>
      </header>

      <section className="dashboard-section">
        <div className="section-heading"><h2>看课工作台</h2></div>
        <p className="intro">
          打开本地课程视频，边看边记：笔记自动带时间点并关联知识点；下次打开同名单视频自动从上次位置继续。
          视频只在你的浏览器里播放，不上传。
        </p>
        {msg && <div className={msg.type === 'err' ? 'error' : 'feedback-card'} style={{ marginBottom: 12 }}>{msg.text}</div>}

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 3fr) minmax(280px, 2fr)', gap: 16, alignItems: 'start' }}>
          <div className="card" style={{ padding: 14 }}>
            <label style={{ display: 'block', marginBottom: 10 }}>
              <span style={{ fontSize: 13, opacity: 0.8 }}>本地视频文件</span>
              <input type="file" accept="video/*" onChange={e => pickVideo(e.target.files?.[0] || null)} style={{ display: 'block', marginTop: 6 }} />
            </label>
            {videoUrl ? (
              <>
                {resumed !== null && <p className="feedback-card" style={{ fontSize: 12 }}>已从 {fmt(resumed)} 续播（上次观看位置）。</p>}
                <video
                  ref={videoRef}
                  src={videoUrl}
                  controls
                  style={{ width: '100%', borderRadius: 10, background: '#000', maxHeight: 420 }}
                  onLoadedMetadata={onLoadedMetadata}
                  onTimeUpdate={onTimeUpdate}
                />
                <div style={{ fontSize: 12, opacity: 0.7, marginTop: 6 }}>{videoName}</div>
              </>
            ) : (
              <div className="empty-state" style={{ padding: 28 }}>选择一个本地视频开始看课（支持 mp4/webm 等浏览器可播格式）。</div>
            )}

            <div style={{ marginTop: 14, borderTop: '1px solid var(--line)', paddingTop: 12 }}>
              <strong style={{ fontSize: 13 }}>在当前时间点记笔记</strong>
              <div style={{ fontSize: 12, opacity: 0.75, margin: '4px 0 6px' }}>
                {selectedNode ? `关联知识点：${selectedNode.name}（${selectedNode.module}）` : '先在右侧选择知识点'}
              </div>
              <textarea value={noteText} onChange={e => setNoteText(e.target.value)} rows={3}
                placeholder="这一段讲了什么要点 / 我的疑问…" style={{ width: '100%', boxSizing: 'border-box', padding: 8 }} />
              <button className="primary" disabled={saving || !selectedNode} onClick={() => void saveNote()} style={{ marginTop: 6 }}>
                {saving ? '保存中…' : videoRef.current ? `保存笔记 [${fmt(videoRef.current.currentTime || 0)}]` : '保存笔记'}
              </button>
            </div>
          </div>

          <div className="card" style={{ padding: 12 }}>
            <h3 style={{ margin: '0 0 8px' }}>关联知识点</h3>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
              <select value={moduleFilter} onChange={e => setModuleFilter(e.target.value)} style={{ padding: '6px 8px' }}>
                <option value="">全部模块</option>
                {modules.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
              <input placeholder="搜索考点…" value={search} onChange={e => setSearch(e.target.value)} style={{ padding: '6px 8px', minWidth: 120 }} />
            </div>
            <div style={{ maxHeight: 200, overflowY: 'auto', border: '1px solid var(--line)', borderRadius: 8 }}>
              {filtered.map(n => (
                <button key={n.id} onClick={() => setSelectedNode(n)}
                  style={{ display: 'block', width: '100%', textAlign: 'left', padding: '7px 10px', border: 0, borderBottom: '1px solid var(--line)', background: selectedNode?.id === n.id ? 'var(--accent)' : 'transparent', color: selectedNode?.id === n.id ? '#fff' : 'inherit', fontSize: 13 }}>
                  {n.name} <span style={{ opacity: 0.6 }}>· {n.module}</span>
                </button>
              ))}
            </div>
            {selectedNode && (
              <>
                <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
                  <Link href="/framework" className="primary-link">到知识框架学这个考点</Link>
                  <Link href="/study" className="primary-link">生成学习任务</Link>
                </div>
                <h4 style={{ margin: '12px 0 6px' }}>该考点笔记（最近 {deskNotes.length} 条）</h4>
                <div style={{ maxHeight: 240, overflowY: 'auto', fontSize: 13 }}>
                  {deskNotes.length === 0 && <div className="empty-state">还没有笔记。</div>}
                  {deskNotes.map(n => (
                    <div key={n.id} style={{ padding: 8, border: '1px solid var(--line)', borderRadius: 8, marginBottom: 6 }}>
                      <div style={{ whiteSpace: 'pre-wrap' }}>{n.content.slice(0, 160)}</div>
                      <div style={{ fontSize: 11, opacity: 0.6, marginTop: 4 }}>
                        {n.metadata?.origin === 'course_desk' && n.metadata?.video ? `${n.metadata.video} · ` : ''}{n.created_at?.slice(0, 16).replace('T', ' ')}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
