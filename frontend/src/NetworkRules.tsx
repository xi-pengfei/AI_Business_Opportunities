import {useEffect,useRef,useState} from 'react';
import type {Me,Rule} from './types';

type Draft={id?:string;name:string;synonyms:string;actions:string;regions:string;enabled:boolean};
type Stats={id:string;created_at:number;started_at:number|null;searches:number;succeeded:number;items:number;items_total:number};
const empty:Draft={name:'',synonyms:'',actions:'采购公告\n招标公告\n采购意向',regions:'',enabled:false};

const PlusIcon=()=><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><path d="M12 5v14M5 12h14"/></svg>;

const stamp=(t?:number)=>t?new Date(t*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}):'—';
function span(seconds:number){
  if(seconds<3600)return `${Math.max(1,Math.round(seconds/60))} 分钟`;
  if(seconds<86400)return `${(seconds/3600).toFixed(1)} 小时`;
  return `${Math.floor(seconds/86400)} 天`;
}

export function NetworkRules({rules,request,onSaved,liveTasks=0,me=null}:{rules:Rule[];request:(path:string,options?:RequestInit)=>Promise<any>;onSaved:()=>Promise<void>;liveTasks?:number;me:Me|null}) {
  const canManage=(r:Rule)=>me?.role==='admin'||!!me&&r.owner_user_id===me.id;
  const [draft,setDraft]=useState<Draft>(empty);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
  const [open,setOpen]=useState(false);
  const [stats,setStats]=useState<Record<string,Stats>>({});
  const [page,setPage]=useState(1);
  const [pageSize,setPageSize]=useState(10);
  const form=useRef<HTMLFormElement>(null);
  const heading=useRef<HTMLHeadingElement>(null);
  const card=useRef<HTMLDivElement>(null);
  const rows=rules.filter(r=>r.provider!=='demo'&&r.provider!=='xiaohongshu'&&!r.search_spec?.retired);
  const running=rows.filter(r=>r.enabled).length;
  const collected=rows.reduce((sum,r)=>sum+(stats[r.id]?.items||0),0);
  useEffect(()=>{
    let alive=true;
    request('/network-rules/stats').then((list:Stats[])=>{
      if(!alive||!Array.isArray(list))return;
      setStats(Object.fromEntries(list.map(s=>[s.id,s])));
    }).catch(()=>{});
    return()=>{alive=false;};
  },[rules]);
  // 每页条数跟随视口高度：按表格实际起点算可用高度，保证整页不出现纵向滚动条
  useEffect(()=>{
    const calc=()=>{
      const top=card.current?.getBoundingClientRect().top;
      if(!top)return;
      setPageSize(Math.max(4,Math.floor((window.innerHeight-top-194)/47)));
    };
    calc();
    addEventListener('resize',calc);
    const observer=new ResizeObserver(calc);
    if(card.current)observer.observe(card.current);
    return()=>{removeEventListener('resize',calc);observer.disconnect();};
  },[]);
  const pages=Math.max(1,Math.ceil(rows.length/pageSize));
  const current=Math.min(page,pages);
  const pageRows=rows.slice((current-1)*pageSize,current*pageSize);
  function focus(){requestAnimationFrame(()=>{heading.current?.focus();});}
  function fromRule(r:Rule):Draft{return {id:r.id,name:r.search_spec?.product||r.name,synonyms:(r.search_spec?.synonyms||[]).join("\n"),actions:(r.search_spec?.actions||["采购公告","招标公告","采购意向"]).join("\n"),regions:(r.search_spec?.regions||[]).join(" "),enabled:r.enabled};}
  function newRule(){setDraft(empty);setError('');setMessage('');setOpen(true);focus();}
  function edit(r:Rule){setDraft(fromRule(r));setError('');setMessage('');setOpen(true);focus();}
  function cancel(){setDraft(empty);setError('');setMessage('');setOpen(false);}
  useEffect(()=>{
    if(!open)return;
    const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape'&&!busy)cancel();};
    addEventListener('keydown',onKey);
    return()=>removeEventListener('keydown',onKey);
  });
  function change(next:Draft){setDraft(next);setError('');}
  async function save(){
    if(!form.current?.reportValidity())return;
    const values={product:draft.name,synonyms:draft.synonyms,actions:draft.actions,regions:draft.regions};
    const enabled=draft.enabled;
    setBusy(true);setError('');
    try{const saved=await request(draft.id?`/network-rules/${draft.id}`:'/network-rules',{method:draft.id?'PATCH':'POST',body:JSON.stringify({...values,enabled})});
      setDraft(empty);setOpen(false);
      const dups=saved?.duplicates||[];
      setMessage('已保存。'+(enabled?'保持运行，新批次使用新配置。':'保持停止，需要时点击开始采集。')
        +(dups.length?` 注意：与已有词条关键词重叠（${dups.map((d:any)=>`${d.name}（${d.owner}）`).join('、')}），可能产生重复采集。`:''));
      await onSaved();
    }catch(e){setError(e instanceof Error?e.message:'保存失败');}finally{setBusy(false);}
  }
  async function toggle(r:Rule){setBusy(true);setError('');try{await request(`/rules/${r.id}`,{method:'PATCH',body:JSON.stringify({enabled:!r.enabled})});if(draft.id===r.id)setDraft(d=>({...d,enabled:!r.enabled}));setMessage(r.enabled?'已停止后续采集，当前批次继续完成。':'已开始按保存的配置采集。');await onSaved();}catch(e){setError(e instanceof Error?e.message:'停止失败');}finally{setBusy(false);}}
  return <>
    {error&&<p className="error" role="alert">{error}</p>}
    {message&&<p className="success" role="status">{message}</p>}
    <div className="page-head">
      <div>
        <h1 className="page-title">网络商机</h1>
        <p className="page-sub">按「产品／业务名词」定义采集主题：填写名称、行为词与地区，保存后从公开网络持续捕获商机信号。</p>
      </div>
      <div className="page-actions">
        <button type="button" className="btn btn-primary" onClick={newRule}><PlusIcon/>新建网络商机</button>
      </div>
    </div>

    <div className="kpis">
      <div className="kpi"><div className="kpi-l">业务名称</div><div className="kpi-v num">{rows.length}<small>个</small></div><div className="kpi-d">累计创建的采集主题</div></div>
      <div className="kpi"><div className="kpi-l">信息采集</div><div className="kpi-v num c-blue">{collected}<small>条</small></div><div className="kpi-d">累计有效条数</div></div>
      <div className="kpi"><div className="kpi-l">运行中</div><div className="kpi-v num c-green">{running}<small>个</small></div><div className="kpi-d">{liveTasks>0?`正在执行任务 ${liveTasks} 个`:'等待执行新任务'}</div></div>
      <div className="kpi"><div className="kpi-l">已停止</div><div className="kpi-v num c-amber">{rows.length-running}<small>个</small></div><div className="kpi-d">停止后不再自动采集</div></div>
    </div>

    <div className="table-card" ref={card}>
      <div className="table-scroll no-fade">
        <table className="rule-table fit">
          <thead>
            <tr>
              <th style={{width:'5%'}}>序号</th>
              <th style={{width:'18%'}}>业务名称</th>
              <th style={{width:'15%'}}>同义词</th>
              <th style={{width:'7%'}}>地区</th>
              <th style={{width:'11%'}}>状态</th>
              <th style={{width:'10%'}}>创建时间</th>
              <th style={{width:'9%'}}>已运行</th>
              <th style={{width:'8%'}}>采集条数</th>
              <th style={{width:'6%'}}>成功率</th>
              <th style={{width:'11%'}}>操作</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((r,i)=>{
              const syn=r.search_spec?.synonyms||[];
              const region=(r.search_spec?.regions||[]).join('、')||'全国';
              const s=stats[r.id];
              const rate=s&&s.items_total>0?Math.round(s.items/s.items_total*100):null;
              const startedAt=s?.started_at||s?.created_at||null;
              const uptime=r.enabled&&startedAt?Date.now()/1000-startedAt:null;
              return <tr key={r.id}>
                <td className="idx-cell">{(current-1)*pageSize+i+1}</td>
                <td><button type="button" className="cell-link" disabled={busy||!canManage(r)} onClick={()=>edit(r)} title={canManage(r)?'打开并修改这个业务名称':'他人创建的词条，仅可查看'}>{r.search_spec?.product||r.name}</button></td>
                <td title={syn.length?syn.join('、'):'暂无同义词'}><div className="chip-row">{syn.length>0&&<span className="chip">{syn[0]}</span>}{syn.length>1&&<span className="chip">+{syn.length-1}</span>}{!syn.length&&<span className="muted">无</span>}</div></td>
                <td title={region}>{region}</td>
                <td><span className={'st '+(r.enabled?'st-on':'st-off')}>{r.enabled?'运行中':'已停止'}</span></td>
                <td className="muted" title={s?.created_at?new Date(s.created_at*1000).toLocaleString('zh-CN',{hour12:false}):''}>{stamp(s?.created_at)}</td>
                <td className="muted" title={uptime!=null?`已运行 ${span(uptime)}`:'尚未开始采集'}>{uptime!=null?span(uptime):'—'}</td>
                <td className="num-cell" title={s?`有效 ${s.items} / 采集 ${s.items_total} 条`:'暂无采集'}>
                  {s?s.items:'—'}
                </td>
                <td className="num-cell" title="有效条数 ÷ 采集到的总条数">{rate!=null?`${rate}%`:'—'}</td>
                <td><div className="actions">
                  {canManage(r)
                    ? (r.enabled
                        ? <button className="btn btn-sm btn-stop" disabled={busy} onClick={()=>toggle(r)}>停止</button>
                        : <button className="btn btn-sm btn-start" disabled={busy} onClick={()=>toggle(r)}>开始采集</button>)
                    : <span className="muted" title="他人创建的词条，仅可查看">—</span>}
                </div></td>
              </tr>;
            })}
          </tbody>
        </table>
      </div>
      {rows.length>0&&<div className="table-foot">
        <span>共 {rows.length} 条 · 第 {current} / {pages} 页 · 每页 {pageSize} 条</span>
        <div className="chart-pager">
          <button className="btn btn-sm" disabled={current<=1} onClick={()=>setPage(current-1)}>上一页</button>
          <button className="btn btn-sm" disabled={current>=pages} onClick={()=>setPage(current+1)}>下一页</button>
        </div>
      </div>}
      {!rows.length&&<div className="empty">还没有业务名称。点击右上角「新建网络商机」，填写业务名称与行为词即可保存并开始采集。</div>}
    </div>

    {open&&<div className="drawer-layer">
      <div className="drawer-backdrop" onClick={cancel}/>
      <aside className="console-drawer" role="dialog" aria-modal="true" aria-labelledby="network-editor-title">
        <button type="button" className="dr-close" onClick={cancel} aria-label="关闭编辑器">✕</button>
        <div className="dr-head">
          <div className="dr-eyebrow">{draft.id?'修改':'新建'} · 网络商机主题</div>
          <h2 className="dr-title" id="network-editor-title" tabIndex={-1} ref={heading}>{draft.id?'修改网络商机':'新建网络商机'}</h2>
          <p className="dr-sub">填写产品名与行为词，同义词按需补充，保存后即按这些词组合采集。</p>
        </div>
        <div className="dr-body">
          <form ref={form} id="network-rule-form" aria-labelledby="network-editor-title" onSubmit={e=>{e.preventDefault();void save();}}>
            <label htmlFor="network-name">产品／业务名称 <span className="opt">必填</span></label>
            <input id="network-name" name="name" required maxLength={80} value={draft.name} disabled={busy} onChange={e=>change({...draft,name:e.target.value})}/>
            <label htmlFor="network-synonyms">同义词 <span className="opt">选填，每行一个，也可用逗号分隔</span></label>
            <textarea id="network-synonyms" name="synonyms" rows={3} maxLength={1600} value={draft.synonyms} disabled={busy} onChange={e=>change({...draft,synonyms:e.target.value})} placeholder="例如 MES 的同义词：制造执行系统"/>
            <label htmlFor="network-actions">行为词 <span className="opt">必填，决定「什么信号算商机」</span></label>
            <textarea id="network-actions" name="actions" rows={3} required maxLength={1600} value={draft.actions} disabled={busy} onChange={e=>change({...draft,actions:e.target.value})}/>
            <label htmlFor="network-regions">地区 <span className="opt">选填，留空为全国</span></label>
            <textarea id="network-regions" name="regions" rows={2} maxLength={2050} value={draft.regions} disabled={busy} aria-describedby="network-regions-help" onChange={e=>change({...draft,regions:e.target.value})} placeholder="陕西 西安 安康 汉中 河南 新疆"/>
            <p id="network-regions-help" className="hint">留空为全国，不加地区词。多个地区用空格、逗号或换行分隔，每次只组合一个地区。</p>
            <p className="hint">搜索服务：SearXNG 开源搜索。按「名称／同义词 × 行为词 × 地区」组合检索，同义词越多覆盖越广。</p>
          </form>
        </div>
        <div className="dr-foot">
          <button type="button" className="btn" onClick={cancel} disabled={busy}>取消</button>
          <button type="submit" form="network-rule-form" className="btn btn-primary" disabled={busy}>{busy?'保存中…':'保存'}</button>
        </div>
      </aside>
    </div>}
  </>;
}
