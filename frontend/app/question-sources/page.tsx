'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import styles from './page.module.css';

type Source = { source: string; reference_count: number; unique_question_count: number; sets: number[] };
type Item = { reference_id: string; question_id: string; source: string; source_locator: string; stem: string; shared: boolean; option_map: Record<string, string> };

export default function QuestionSources() {
  const [sources, setSources] = useState<Source[]>([]);
  const [source, setSource] = useState('');
  const [setNumber, setSetNumber] = useState('');
  const [questionNumber, setQuestionNumber] = useState('');
  const [search, setSearch] = useState('');
  const [items, setItems] = useState<Item[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const selectedSource = sources.find(s => s.source === source);

  useEffect(() => {
    api<{ sources: Source[] }>('/question-sources').then(r => setSources(r.sources)).catch(e => setError(e.message));
  }, []);

  useEffect(() => {
    let active = true;
    const params = new URLSearchParams({ offset: String(offset), limit: '50', search });
    if (source) params.set('source', source);
    if (setNumber) params.set('set_number', setNumber);
    if (questionNumber) params.set('question_number', questionNumber);
    api<{ total: number; items: Item[] }>(`/question-sources/questions?${params}`)
      .then(r => { if (active) { setItems(r.items); setTotal(r.total); setError(''); } })
      .catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [source, setNumber, questionNumber, search, offset]);

  async function practice(referenceId?: string) {
    setBusy(true); setError('');
    try {
      const body = referenceId ? { reference_id: referenceId } : { source, set_number: setNumber ? Number(setNumber) : undefined };
      const session = await api<{ id: string }>('/question-sources/practice', { method: 'POST', body: JSON.stringify(body) });
      window.location.href = `/quiz?session=${encodeURIComponent(session.id)}`;
    } catch (e) { setError(e instanceof Error ? e.message : '暂时无法开始练习'); setBusy(false); }
  }

  return <main className={styles.page}>
    <header><Link className="brand" href="/dashboard">公考 Learning OS</Link><nav><Link href="/dashboard">学习概览</Link><Link href="/quiz">行测训练</Link><Link className="active" href="/question-sources">按原书找题</Link><Link href="/settings">设置</Link></nav></header>
    <section className="intro"><h1>按原书找题</h1><p>按试卷、练习套号和原题号查找。同一道题共用作答、笔记与复习记录。</p></section>
    <section className="card" style={{ padding: 24, marginBottom: 20 }}>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'end' }}>
        <label>试卷或题本<select aria-label="试卷或题本" value={source} onChange={e => { setSource(e.target.value); setSetNumber(''); setOffset(0); }}><option value="">全部来源</option>{sources.map(s => <option key={s.source} value={s.source}>{s.source}（{s.reference_count} 个题号）</option>)}</select></label>
        {Boolean(selectedSource?.sets.length) && <label>练习套号<select aria-label="练习套号" value={setNumber} onChange={e => { setSetNumber(e.target.value); setOffset(0); }}><option value="">全部套号</option>{selectedSource?.sets.map(n => <option key={n} value={n}>第 {n} 套</option>)}</select></label>}
        <label>原题号<input aria-label="原题号" type="number" min={1} value={questionNumber} onChange={e => { setQuestionNumber(e.target.value); setOffset(0); }} style={{ width: 100 }} /></label>
        <label>查找文字或原编号<input aria-label="查找文字或原编号" value={search} onChange={e => { setSearch(e.target.value); setOffset(0); }} placeholder="输入题干关键词" /></label>
        <button disabled={busy || !source || (!setNumber && (selectedSource?.unique_question_count || 0) > 200)} onClick={() => practice()}>练习所选试卷／套题</button>
      </div>
      {selectedSource && <p className="muted">本来源 {selectedSource.reference_count} 个原题号，共用 {selectedSource.unique_question_count} 道题。{selectedSource.sets.length > 0 && '整本练习请先选套号。'}作答时选项顺序以系统展示为准。</p>}
      {error && <p role="alert">{error}</p>}
    </section>
    <p>找到 {total} 个来源题号</p>
    <section style={{ display: 'grid', gap: 12 }}>
      {items.map(item => <article className="card" key={item.reference_id} style={{ padding: 20 }}>
        <strong>{item.source} · {item.source_locator}</strong>
        <p style={{ whiteSpace: 'pre-wrap' }}>{item.stem}</p>
        {item.shared && <p className="muted">此题与已收录题目共用内容，学习记录统一保存。</p>}
        {Object.entries(item.option_map).some(([a, b]) => a !== b) && <p className="muted">原卷选项对应当前选项：{Object.entries(item.option_map).map(([a, b]) => `${a}→${b}`).join('，')}</p>}
        <button disabled={busy} onClick={() => practice(item.reference_id)}>练这道题</button>
      </article>)}
      {!items.length && !error && <p>没有找到对应题号，请检查来源、套号或搜索条件。</p>}
    </section>
    <div style={{ display: 'flex', gap: 16, padding: '24px 0' }}><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>上一页</button><span>第 {Math.floor(offset / 50) + 1} 页</span><button disabled={offset + 50 >= total} onClick={() => setOffset(offset + 50)}>下一页</button></div>
  </main>;
}
