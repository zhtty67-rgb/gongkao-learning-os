import Link from 'next/link';
import { ShenlunDailyTask } from './api';

export function ShenlunDailyTaskCard({ task, workbench = false, onNext, busy = false }: { task: ShenlunDailyTask; workbench?: boolean; onNext?: () => void; busy?: boolean }) {
  return <section className="card" aria-label="申论每日任务" style={{ marginBottom: 20, minHeight: 0, height: 'auto' }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
      <div>
        <h2 style={{ margin: '0 0 8px', fontSize: 18 }}>今日申论任务：完成 {task.target} 道小题</h2>
        <p style={{ margin: 0 }}><strong>{task.completed} / {task.target}</strong> 道 · {task.remaining === 0 ? '今日已完成' : '待完成'}</p>
        <p style={{ margin: '8px 0 0', color: 'var(--muted)', fontSize: 13 }}>逐题阅读材料、提炼要点并提交，再集中复盘。保存草稿不计完成，同题重复提交只计一次，大作文另练。</p>
        {!task.available && <p role="status">暂无申论材料，请先补充题目。</p>}
        {task.available && task.remaining > 0 && task.next_available === false && <p role="status">今日可用小题已练完，还差 {task.remaining} 道；请补充题目或复盘已完成的作答。</p>}
      </div>
      {!workbench && task.available && <Link className="primary" href="/shenlun?daily=1" style={{ display: 'inline-block', padding: '10px 18px', borderRadius: 8, textDecoration: 'none' }}>{task.remaining ? '开始今日申论' : '查看今日作答'}</Link>}
      {workbench && onNext && task.next_available && <button className="primary" disabled={busy} onClick={onNext}>{task.remaining ? '继续下一道小题' : '额外练一道小题'}</button>}
    </div>
    <progress aria-label="今日申论进度" value={Math.min(task.completed, task.target)} max={task.target} style={{ width: '100%', marginTop: 14 }} />
  </section>;
}
