'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { createRequestId } from '../../lib/requestId';
import { FormattedStem } from '../../lib/FormattedStem';
import styles from './teaching.module.css';

type Goal = {id:string;name:string;ready:boolean};
type Check = {skill_id:string;attempt_id:string;format:string;prompt:string;options:Record<string,string>;stem_assets:string[];option_assets:Record<string,string[]>;passage:{content:string;assets:string[]}|null};
type Session = {id:string;goal:string;phase:string;revision:number;current_skill_id:string|null;nodes:{id:string;name:string;boundary:string;mastery:{mastery_score:number;attempt_count:number}}[];return_stack:string[];check:Check|null;lesson:{core_concept:string;example:string;source_basis?:string;citation?:string|null}|null;hint:Record<string,unknown>|null;last_result:{passed:boolean;correct:boolean;feedback:string;review_due:string|null;assessment_provider:string}|null;message:string};
const labels:Record<string,string>={PROBE:'知识边界验证',PLAN:'安排学习路径',TEACH_NODE:'学习一个节点',CHECK:'独立检查',UPDATE:'更新与补救',COMPLETE:'本次路径完成'};
const boundaries:Record<string,string>={verified:'已通过边界检查',provisional:'待第二种方式验证',needs_learning:'需要学习',unknown:'尚未验证'};

export default function TeachingPage(){
  const [goals,setGoals]=useState<Goal[]>([]);const [skill,setSkill]=useState('two_period');
  const [goal,setGoal]=useState('理解两期比重的比较方法，并独立应用');
  const [session,setSession]=useState<Session|null>(null);const [answer,setAnswer]=useState('');
  const [confidence,setConfidence]=useState(0.5);const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  const [reviewAttempt,setReviewAttempt]=useState<string|null>(null);
  useEffect(()=>{let active=true;
    const params=new URLSearchParams(window.location.search);const reviewed=params.get('review_attempt_id');
    if(reviewed){setReviewAttempt(reviewed);if(params.get('skill_id'))setSkill(params.get('skill_id')!);}
    api<{goals:Goal[]}>('/teaching/goals').then(r=>{if(active)setGoals(r.goals)}).catch(e=>{if(active)setError(e.message)});
    const id=window.localStorage.getItem('adaptive-teaching-session');
    if(id&&!reviewed)api<Session>(`/teaching/sessions/${id}`).then(s=>{if(active)setSession(s)}).catch(e=>{if(active)setError(e.message)});
    return()=>{active=false};
  },[]);
  async function start(){setBusy(true);setError('');try{
    const s=await api<Session>('/teaching/sessions',{skill_id:skill,goal,review_attempt_id:reviewAttempt});
    setSession(s);window.localStorage.setItem('adaptive-teaching-session',s.id);setAnswer('');
  }catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function act(action:string,hintLevel=1){if(!session)return;setBusy(true);setError('');try{
    const s=await api<Session>(`/teaching/sessions/${session.id}/actions`,{action,revision:session.revision,request_id:createRequestId(),answer,confidence,hint_level:hintLevel});
    setSession(s);setAnswer('');
  }catch(e){setError((e as Error).message);try{setSession(await api<Session>(`/teaching/sessions/${session.id}`))}catch{}}
  finally{setBusy(false)}}
  return <main className={styles.page}>
    <nav><Link href="/dashboard">学习首页</Link> · <Link href="/quiz">行测训练</Link> · <Link href="/review">到期复习</Link> · <Link href="/settings">设置</Link></nav>
    <h1>自适应教学</h1><p>先确认知识边界，每次学习一个节点，用独立检查决定下一步。</p>
    {error&&<p role="alert" className={styles.error}>{error.includes('EXAM_MODE_LOCKED')?<>仍有进行中的模考，请先在<Link href="/exam">模考页面</Link>完成或结束会话，再刷新开始教学。</>:error}</p>}
    {(!session||session.phase==='COMPLETE')&&<section className={styles.card}>
      <label>目标技能<select aria-label="目标技能" value={skill} onChange={e=>setSkill(e.target.value)}>{goals.map(g=><option key={g.id} value={g.id} disabled={!g.ready}>{g.name}{!g.ready?'（核验题池不足）':''}</option>)}</select></label>
      <label>学习目标<textarea aria-label="学习目标" value={goal} onChange={e=>setGoal(e.target.value)}/></label>
      {reviewAttempt&&<p>将依据这次复习失败重新检查前置知识。</p>}
      <button disabled={busy||!goal.trim()||!goals.find(g=>g.id===skill)?.ready} onClick={start}>开始自适应学习</button>
    </section>}
    {session&&<>
      <section className={styles.card}><h2>{labels[session.phase]}</h2><p>{session.goal}</p><p role="status">{session.message}</p>
        <ul>{session.nodes.map(n=><li key={n.id} data-testid={`node-${n.id}`}><strong>{n.name}</strong>：{boundaries[n.boundary]||n.boundary}{session.current_skill_id===n.id?' · 当前节点':''}<small>正式掌握度 {Math.round(n.mastery.mastery_score*100)}% · {n.mastery.attempt_count} 条证据</small></li>)}</ul>
        {session.return_stack.length>0&&<p>补救后返回：{session.return_stack.map(id=>session.nodes.find(n=>n.id===id)?.name||id).join(' → ')}</p>}
      </section>
      {session.lesson&&<section className={styles.card} data-testid="micro-lesson"><h2>本轮一个核心概念</h2><p>{session.lesson.core_concept}</p><h3>一个示例</h3><p>{session.lesson.example}</p><small>{session.lesson.source_basis}</small>{session.lesson.citation&&<p>{session.lesson.citation}</p>}</section>}
      {session.last_result&&<section className={styles.card}><h3>{session.last_result.passed?'独立检查通过':session.last_result.correct?'辅助完成，仍需独立验证':'检查未通过'}</h3><p>{session.last_result.feedback}</p>{session.last_result.assessment_provider==='mock'&&<p>当前为模拟评估，不作为真实能力证据。</p>}{session.last_result.review_due&&<p>已进入正式复习队列：{new Date(session.last_result.review_due).toLocaleString()}</p>}</section>}
      {session.check&&<section className={styles.card} data-testid="teaching-check"><h2>{session.check.format==='choice'?'选择题':session.check.format==='recall'?'自由回忆':'应用题：请给出结论和理由'}</h2>
        {session.check.passage&&<div><p>{session.check.passage.content}</p>{session.check.passage.assets.map(src=><img key={src} src={src} alt="题目材料"/>)}</div>}
        <p><FormattedStem text={session.check.prompt}/></p>{session.check.stem_assets.map(src=><img key={src} src={src} alt="题目图示"/>)}
        {session.check.format==='choice'?<fieldset><legend>选择答案</legend>{Object.entries(session.check.options).map(([k,v])=><label key={k}><input type="radio" name="answer" value={k} checked={answer===k} onChange={()=>setAnswer(k)}/>{k}．{v}{session.check!.option_assets[k]?.map(src=><img key={src} src={src} alt={`选项${k}`}/>)}</label>)}</fieldset>:<textarea aria-label="检查答案与理由" value={answer} onChange={e=>setAnswer(e.target.value)} placeholder="先独立回忆，再写下理由"/>}
        <label>作答信心<select aria-label="作答信心" value={confidence} onChange={e=>setConfidence(Number(e.target.value))}>{[[0.2,'纯蒙题'],[0.5,'半猜'],[0.9,'有信心']].map(([v,label])=><option key={v} value={v}>{label}</option>)}</select></label>
        <button disabled={busy||!answer.trim()} onClick={()=>act('answer')}>提交检查</button>
        {session.phase==='CHECK'&&<button disabled={busy} onClick={()=>act('hint',Math.min(4,Number(session.hint?.hint_level||0)+1))}>请求下一层提示</button>}
        {session.hint&&<p>{['direction','method','partial_step','full_explanation'].map(k=>String(session.hint?.[k]||'')).join('\n')}</p>}
      </section>}
      {['PLAN','TEACH_NODE','UPDATE'].includes(session.phase)&&<button disabled={busy} onClick={()=>act('advance')}>{session.phase==='PLAN'?'确认学习路径':session.phase==='TEACH_NODE'?'开始本节点教学':'应用检查结果'}</button>}
      {session.phase==='COMPLETE'&&<p><Link href="/review">查看到期复习</Link> · <Link href="/dashboard">查看正式学习统计</Link></p>}
    </>}{busy&&<p role="status">正在处理，请稍候…</p>}
  </main>
}
