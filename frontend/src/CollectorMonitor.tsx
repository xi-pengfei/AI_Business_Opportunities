import { useRef } from 'react';
import {rotateRows, useUpwardLoop} from './useUpwardLoop';
import type { Snapshot } from './types';
import { errors, fullTime } from './types';

type Collector = Snapshot['collectors'][number];
const time = (stamp: number) => new Date(stamp * 1000).toLocaleTimeString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false});
const platform = (c: Collector) => c.search_engine || ({searxng:'SearXNG',xiaohongshu:'小红书',tavily:'Tavily',demo:'演示服务'}[c.provider] || c.provider || '等待选择入口');
function state(c: Collector): [string,string] {
  if (['retry_wait','failed','action_required'].includes(c.state)) {
    if (/rate_limited|verification/.test(c.error_code || '')) return ['failure','限流 / 待验证'];
    if (c.state === 'action_required') return ['warning','等待配置 / 授权'];
    return ['warning',c.state === 'retry_wait' ? '等待重试' : '等待恢复'];
  }
  if (c.waiting_recheck) return ['waiting','等待复查'];
  if (c.state === 'running') return ['success','正在搜索'];
  if (c.state === 'queued') return ['waiting',c.rounds ? '排队中' : '等待首次运行'];
  if (c.search_outcome === 'empty') return ['waiting','本轮无结果'];
  if (c.search_outcome === 'partial_results') return ['warning','部分入口异常'];
  return ['success',c.state === 'cleaning' ? '清洗入库' : '搜索成功'];
}
function next(c: Collector) {
  if(c.state === 'running') return '等待返回';
  if(c.state === 'cleaning') return '等待入库完成';
  if(c.state === 'action_required') return '等待人工处理';
  if(c.state === 'queued') return '等待调度';
  if(c.state === 'retry_wait') return c.next_action_at ? `${time(c.next_action_at)} 重试` : '等待重试';
  if(c.waiting_recheck) return `${time(c.next_action_at)} 复查`;
  return c.continuous ? '继续下一项' : `${time(c.next_action_at)} 再搜`;
}
export function CollectorMonitor({collectors = [], stale}: {collectors: Collector[]; stale: boolean}) {
  const scroll = useRef<HTMLDivElement>(null);
  const heat = useRef<HTMLDivElement>(null);
  const offset = useUpwardLoop(scroll, 'tbody > tr', !stale, heat);
  const rows = rotateRows(collectors, offset);
  const history = collectors[0]?.history || [];
  return <div className="collector-monitor">
    <section className="collector-heat">
      <div className="cm-axis"><span>{history.length ? time(history[0].start).slice(0,5) : '—'}</span><span>{history.length ? time(history[12].start).slice(0,5) : '—'}</span><span>当前时段</span></div>
      <div className="cm-heat-scroll" ref={heat} tabIndex={0} role="region" aria-label="采集运行历史" onScroll={e=>{if(scroll.current && e.currentTarget.matches(':hover, :focus-within')) scroll.current.scrollTop=e.currentTarget.scrollTop;}}>
        {rows.map(c=><div className="cm-heat-row" key={c.id}><span title={c.name}>{c.name}</span><div className="cm-cells">
          {(c.history || []).map(b=>{
            const tone=b.results !== null && b.results > 0 ? 'hit' : b.failures ? 'failure' : b.warnings ? 'warning' : b.successes ? (b.results === 0 ? 'zero' : 'unknown') : b.running ? 'running' : 'idle';
            const label=`${c.name} · ${time(b.start)}–${time(b.start+150)} · ${b.results === null ? '无结果数量记录' : `返回 ${b.results} 条`} · 成功 ${b.successes} 次 · 异常 ${b.failures} 次 · 警告 ${b.warnings} 次${!b.successes&&!b.failures&&!b.warnings ? b.running ? ' · 已启动，尚无结束记录' : ' · 无执行事件' : ''}`;
            return <span key={b.start} className={`cm-cell ${tone}`} title={label} aria-label={label}>{b.results ?? ''}{b.results !== null && (b.failures>0||b.warnings>0) && <i className={b.failures ? 'failure' : 'warning'} aria-hidden="true"/>}</span>;
          })}
        </div></div>)}
        {!collectors.length && <p className="cm-empty">暂无启用的采集规则，等待任务</p>}
      </div>
    </section>
    <section className="collector-current">
      <div className="cm-table-scroll" ref={scroll} tabIndex={0} role="region" aria-label="当前采集状态表" onScroll={e=>{if(heat.current) heat.current.scrollTop=e.currentTarget.scrollTop;}}>
        <table><thead><tr>{['采集词条','搜索入口','当前状态','最近搜索成功','下次动作'].map(label=><th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>
          {rows.map(c=>{const [tone,label]=state(c);return <tr key={c.id}><th scope="row" title={c.name}>{c.name}</th><td title={platform(c)}>{platform(c)}</td><td className={`cm-state-${tone}`} title={c.error_code ? errors[c.error_code] || c.error_code : label}>{label}</td><td title={fullTime(c.last_success_at || undefined)}>{c.last_success_at ? time(c.last_success_at) : '等待首次成功'}</td><td title={next(c)}>{next(c)}</td></tr>})}
          {!collectors.length && <tr><td colSpan={5}>暂无启用的采集规则</td></tr>}
        </tbody></table>
      </div>
    </section>
  </div>;
}
