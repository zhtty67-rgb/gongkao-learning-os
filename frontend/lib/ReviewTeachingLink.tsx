'use client';
import {useEffect,useState} from 'react';
import Link from 'next/link';
import {api} from './api';
export function ReviewTeachingLink({attemptId}:{attemptId:string}){
  const [goals,setGoals]=useState<{id:string;name:string}[]>([]);
  useEffect(()=>{let active=true;api<{goals:{id:string;name:string}[]}>(`/teaching/review/${attemptId}`).then(r=>{if(active)setGoals(r.goals)}).catch(()=>{});return()=>{active=false}},[attemptId]);
  if(!goals.length)return null;
  return <section><h3>重新检查知识边界</h3><p>这次复习未通过，可以先定位前置缺口，再补一个节点。</p>{goals.map(g=><p key={g.id}><Link href={`/teaching?review_attempt_id=${encodeURIComponent(attemptId)}&skill_id=${encodeURIComponent(g.id)}`}>针对“{g.name}”开始补救教学</Link></p>)}</section>;
}
