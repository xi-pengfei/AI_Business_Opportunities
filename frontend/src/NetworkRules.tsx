import {useEffect,useRef,useState} from 'react';
import type {Rule} from './types';

type Draft={id?:string;name:string;synonyms:string;actions:string;regions:string;enabled:boolean};
type Review={product:string;synonyms:string[];actions:string[];regions:string[];queries:string[];notes:string[];model:string};
const empty:Draft={name:'',synonyms:'',actions:'采购公告\n招标公告\n采购意向',regions:'',enabled:false};

const PlusIcon=()=><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><path d="M12 5v14M5 12h14"/></svg>;

function freq(seconds:number){return seconds>=3600?`每 ${Math.round(seconds/3600)} 小时`:seconds>0?`每 ${Math.round(seconds/60)} 分钟`:'手动触发';}

export function NetworkRules({rules,request,onSaved}:{rules:Rule[];request:(path:string,options?:RequestInit)=>Promise<any>;onSaved:()=>Promise<void>}) {
  const [draft,setDraft]=useState<Draft>(empty),[checked,setChecked]=useState<Review|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
  const [open,setOpen]=useState(false);
  const form=useRef<HTMLFormElement>(null);
  const heading=useRef<HTMLHeadingElement>(null);
  const rows=rules.filter(r=>r.provider!=='demo'&&r.provider!=='xiaohongshu'&&!r.search_spec?.retired);
  const running=rows.filter(r=>r.enabled).length;
  function focus(){requestAnimationFrame(()=>{heading.current?.focus();});}
  function fromRule(r:Rule):Draft{return {id:r.id,name:r.search_spec?.product||r.name,synonyms:(r.search_spec?.synonyms||[]).join("\n"),actions:(r.search_spec?.actions||["采购公告","招标公告","采购意向"]).join("\n"),regions:(r.search_spec?.regions||[]).join(" "),enabled:r.enabled};}
  function newRule(){setDraft(empty);setChecked(null);setError('');setMessage('');setOpen(true);focus();}
  function edit(r:Rule){setDraft(fromRule(r));setChecked(null);setError('');setMessage('');setOpen(true);focus();}
  function cancel(){setChecked(null);setDraft(empty);setError('');setMessage('');setOpen(false);}
  useEffect(()=>{
    if(!open)return;
    const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape'&&!busy)cancel();};
    addEventListener('keydown',onKey);
    return()=>removeEventListener('keydown',onKey);
  });
  async function check(value:Draft=draft){
    setDraft(value);setBusy(true);setError('');setMessage('');setChecked(null);focus();
    try{setChecked(await request('/network-rules/review',{method:'POST',signal:AbortSignal.timeout(60000),body:JSON.stringify({product:value.name,synonyms:value.synonyms,actions:value.actions,regions:value.regions})}));}
    catch(e){setError(e instanceof Error?e.message:'AI检查失败，尚未保存或启动');}
    finally{setBusy(false);}
  }
  function change(next:Draft){setDraft(next);setChecked(null);setError('');}
  async function save(adopt:boolean){
    if(!form.current?.reportValidity() || (adopt&&!checked))return;
    const values=adopt&&checked?{product:checked.product,synonyms:checked.synonyms,actions:checked.actions,regions:checked.regions}:{product:draft.name,synonyms:draft.synonyms,actions:draft.actions,regions:draft.regions};
    const enabled=draft.enabled;
    setBusy(true);setError('');
    try{await request(draft.id?`/network-rules/${draft.id}`:'/network-rules',{method:draft.id?'PATCH':'POST',body:JSON.stringify({...values,enabled})});
      setChecked(null);setDraft(empty);setOpen(false);setMessage((adopt?'已采纳 AI 建议并保存。':'已保留你的内容并保存。')+(enabled?'保持运行，新批次使用新配置。':'保持停止，需要时点击开始采集。'));await onSaved();
    }catch(e){setError(e instanceof Error?e.message:'保存失败');}finally{setBusy(false);}
  }
  async function toggle(r:Rule){setBusy(true);setError('');try{await request(`/rules/${r.id}`,{method:'PATCH',body:JSON.stringify({enabled:!r.enabled})});if(draft.id===r.id)setDraft(d=>({...d,enabled:!r.enabled}));setMessage(r.enabled?'已停止后续采集，当前批次继续完成。':'已开始按保存的配置采集。');await onSaved();}catch(e){setError(e instanceof Error?e.message:'停止失败');}finally{setBusy(false);}}
  return <>
    {error&&<p className="error" role="alert">{error}</p>}
    {message&&<p className="success" role="status">{message}</p>}
    <div className="page-head">
      <div>
        <h1 className="page-title">网络商机</h1>
        <p className="page-sub">按「产品／业务名词」定义采集主题：填写名称与行为词，AI 检查后生成同义词与搜索组合，从公开网络持续捕获商机信号。</p>
      </div>
      <div className="page-actions">
        <button type="button" className="btn btn-primary" onClick={newRule}><PlusIcon/>新建网络商机</button>
      </div>
    </div>

    <div className="kpis">
      <div className="kpi"><div className="kpi-l">商机主题</div><div className="kpi-v num">{rows.length}<small>个</small></div><div className="kpi-d">{running} 个运行中 · {rows.length-running} 个停止</div></div>
      <div className="kpi"><div className="kpi-l">持续采集</div><div className="kpi-v num">{running}<small>个</small></div><div className="kpi-d"><span className="chip brand">按各自频率自动运行</span></div></div>
      <div className="kpi"><div className="kpi-l">搜索服务</div><div className="kpi-v">SearXNG<small>开源搜索</small></div><div className="kpi-d">全部主题共用同一入口</div></div>
    </div>

    <div className="table-card">
      <div className="table-scroll">
        <table className="rule-table">
          <thead>
            <tr>
              <th style={{minWidth:240}}>商机 / 产品</th>
              <th style={{minWidth:260}}>行为词</th>
              <th>地区</th>
              <th>状态</th>
              <th>采集频率</th>
              <th style={{width:150}}>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r=>{
              const acts=r.search_spec?.actions||[];
              const syn=r.search_spec?.synonyms||[];
              return <tr key={r.id}>
                <td><div className="cell-main">
                  <div className="cell-name">{r.search_spec?.product||r.name}</div>
                  <div className="cell-meta">同义词 {syn.length} 个<span className="sep">·</span>{r.search_spec?.regions?.length||0} 个地区</div>
                </div></td>
                <td><div className="chip-row">{acts.slice(0,2).map(a=><span className="chip" key={a}>{a}</span>)}{acts.length>2&&<span className="chip">+{acts.length-2}</span>}{!acts.length&&<span className="muted">待配置</span>}</div></td>
                <td>{r.search_spec?.regions?.join('、')||'全国'}</td>
                <td><span className={'st '+(r.enabled?'st-on':'st-off')}>{r.enabled?'运行中':'已停止'}</span></td>
                <td className="muted">{freq(r.interval_seconds)}</td>
                <td><div className="actions">
                  <button className="btn btn-sm" disabled={busy} onClick={()=>edit(r)}>修改</button>
                  <button className="btn btn-sm btn-quiet" disabled={busy} onClick={()=>toggle(r)}>{r.enabled?'停止':'开始采集'}</button>
                </div></td>
              </tr>;
            })}
          </tbody>
        </table>
      </div>
      {!rows.length&&<div className="empty">还没有商机主题。点击右上角「新建网络商机」，填写产品名与行为词，AI 会帮你生成搜索组合。</div>}
    </div>

    {open&&<div className="drawer-layer">
      <div className="drawer-backdrop" onClick={cancel}/>
      <aside className="console-drawer" role="dialog" aria-modal="true" aria-labelledby="network-editor-title">
        <button type="button" className="dr-close" onClick={cancel} aria-label="关闭编辑器">✕</button>
        <div className="dr-head">
          <div className="dr-eyebrow">{draft.id?'修改':'新建'} · 网络商机主题</div>
          <h2 className="dr-title" id="network-editor-title" tabIndex={-1} ref={heading}>{draft.id?'修改网络商机':'新建网络商机'}</h2>
          <p className="dr-sub">只需产品名与行为词，同义词可以交给 AI 扩展。</p>
        </div>
        <div className="dr-body">
          <form ref={form} id="network-rule-form" aria-labelledby="network-editor-title" onSubmit={e=>{e.preventDefault();void check();}}>
            <label htmlFor="network-name">产品／业务名称 <span className="opt">必填</span></label>
            <input id="network-name" name="name" required maxLength={80} value={draft.name} disabled={busy} onChange={e=>change({...draft,name:e.target.value})}/>
            <label htmlFor="network-synonyms">同义词 <span className="opt">选填，每行一个，也可用逗号分隔</span></label>
            <textarea id="network-synonyms" name="synonyms" rows={3} maxLength={1600} value={draft.synonyms} disabled={busy} onChange={e=>change({...draft,synonyms:e.target.value})} placeholder="例如 MES 的同义词：制造执行系统"/>
            <label htmlFor="network-actions">行为词 <span className="opt">必填，决定「什么信号算商机」</span></label>
            <textarea id="network-actions" name="actions" rows={3} required maxLength={1600} value={draft.actions} disabled={busy} onChange={e=>change({...draft,actions:e.target.value})}/>
            <label htmlFor="network-regions">地区 <span className="opt">选填，留空为全国</span></label>
            <textarea id="network-regions" name="regions" rows={2} maxLength={2050} value={draft.regions} disabled={busy} aria-describedby="network-regions-help" onChange={e=>change({...draft,regions:e.target.value})} placeholder="陕西 西安 安康 汉中 河南 新疆"/>
            <p id="network-regions-help" className="hint">留空为全国，不加地区词。多个地区用空格、逗号或换行分隔，每次只组合一个地区。</p>
            <p className="hint">搜索服务：SearXNG 开源搜索。AI 只提供建议，不会覆盖上面的内容；修改输入后旧建议会清除。</p>
          </form>
          {checked&&<section className="keyword-review" aria-labelledby="suggestion-title">
            <h3 id="suggestion-title">AI 建议 · {checked.model}</h3>
            <p>产品／业务名称：{checked.product}</p>
            <p>同义词：{checked.synonyms.join('、')||'无'}</p>
            <p>行为词：{checked.actions.join('、')}</p>
            <p>地区：{checked.regions.join('、')||'全国（不加地区词）'}</p>
            {checked.notes.length>0&&<ul>{checked.notes.map((n,i)=><li key={i}>{n}</li>)}</ul>}
            <details><summary>建议的搜索组合 · {checked.queries.length} 条</summary><p className="rule-keywords">{checked.queries.join('\n')}</p></details>
            <div className="actions" style={{marginTop:6}}>
              <button type="button" className="btn btn-primary" disabled={busy} onClick={()=>save(true)}>采纳建议并保存</button>
              <button type="button" className="btn" disabled={busy} onClick={()=>save(false)}>保留我的内容并保存</button>
            </div>
            <p className="hint">两种保存方式都会保持当前{draft.enabled?'运行':'停止'}状态。</p>
          </section>}
          {!checked&&error&&<button type="button" className="btn" disabled={busy} onClick={()=>save(false)}>保留我的内容并保存</button>}
        </div>
        <div className="dr-foot">
          <button type="button" className="btn" onClick={cancel} disabled={busy}>取消</button>
          <button type="submit" form="network-rule-form" className="btn btn-primary" disabled={busy}>{busy?'正在 AI 检查…':'AI 检查'}</button>
        </div>
      </aside>
    </div>}
  </>;
}
