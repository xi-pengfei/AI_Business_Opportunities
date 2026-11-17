import { useCallback, useEffect, useRef, useState } from "react";
import { errors } from "./types";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type Customer = { id: string; name: string; aliases: string[]; website?: string; reference_urls?:string[]; rule_id: string; enabled: boolean; query?: string; state: string; error_code?: string; last_search_at?: number; last_found_at?: number; signal_count?: number; owner_user_id?: string | null; owner_name?: string | null; next_run_at: number };
type UserRow = { id: string; display_name: string; username: string; is_active: boolean };
type Signal = { id: string; customer_name: string; title: string; url?: string; topic: string; fragments?: {text:string}[]; published_at?: string; created_at: number; matched_name?: string; content_kind?: string };
type Draft = { id?: string; name: string; aliases: string; urls: string };
const empty: Draft = { name: "", aliases: "", urls: "" };
const dateTime = (value?: number) => value ? new Date(value * 1000).toLocaleString("zh-CN", {timeZone:"Asia/Shanghai", hour12:false}) : "—";
const PlusIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><path d="M12 5v14M5 12h14"/></svg>;
const EditIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>;

type Status = { cls: string; text: string; note?: string; tab: "on" | "attention" | "off" };
function statusOf(c: Customer): Status {
  if (!c.enabled) return { cls: "st-off", text: "已停止", tab: "off" };
  if (c.error_code) return { cls: "st-failed", text: "搜索异常", note: errors[c.error_code] || "搜索入口等待恢复", tab: "attention" };
  if (c.state === "running") return { cls: "st-on", text: "正在搜索", tab: "on" };
  if (!c.last_search_at) return { cls: "st-wait", text: "等待首次搜索", tab: "attention" };
  // 监测中即可：检索心跳放进悬浮提示，不占一列
  return { cls: "st-on", text: "监测中", note: `上次自动检索 ${dateTime(c.last_search_at)} · 下次复查 ${dateTime(c.next_run_at)}`, tab: "on" };
}

type Tab = "all" | "on" | "attention" | "off";
const TABS: { key: Tab; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "on", label: "监测中" },
  { key: "attention", label: "需要关注" },
  { key: "off", label: "已停止" },
];

export function Customers({request, manage = false}: {request: Request; manage?: boolean}) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [signalsTotal, setSignalsTotal] = useState<number | null>(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(() => setRevision(n=>n+1), []);
  // 顶部状态菜单 + 模糊搜索
  const [tab, setTab] = useState<Tab>("all");
  const [query, setQuery] = useState("");
  // 列表分页（跟随视口高度，同网络商机页）
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const card = useRef<HTMLDivElement>(null);
  // 新建 / 修改抽屉
  const [draft, setDraft] = useState<Draft>(empty);
  const [open, setOpen] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  // 动向明细抽屉
  const [detailOf, setDetailOf] = useState<{customer: Customer; signals: Signal[]; total: number; offset: number; loading: boolean} | null>(null);
  const detailTitle = useRef<HTMLHeadingElement>(null);
  const [evidence, setEvidence] = useState<{id: string; title: string; raw_content: string; content_kind: string} | null>(null);
  // 批量指定对接人
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [users, setUsers] = useState<UserRow[]>([]);
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignTarget, setAssignTarget] = useState<string>("");

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        if (manage) {
          const [rows, sigs] = await Promise.all([
            request("/customers"),
            request("/customer-signals?offset=0"),
          ]);
          if (alive) { setCustomers(rows); setSignalsTotal(sigs.total); setError(""); }
        }
      } catch(e) { if(alive) setError(e instanceof Error ? e.message : "客户动向读取失败"); }
      finally { if(alive) timer=setTimeout(load, 15000); }
    };
    void load();
    return () => {alive=false;clearTimeout(timer);};
  },[request,manage,revision]);

  useEffect(() => {
    const calc=()=>{
      const top=card.current?.getBoundingClientRect().top;
      if(!top)return;
      setPageSize(Math.max(4,Math.floor((window.innerHeight-top-180)/47)));
    };
    calc();
    addEventListener('resize',calc);
    const observer=new ResizeObserver(calc);
    if(card.current)observer.observe(card.current);
    return()=>{removeEventListener('resize',calc);observer.disconnect();};
  },[]);

  useEffect(() => {
    if(!open && !detailOf && !assignOpen)return;
    const onKey=(e:KeyboardEvent)=>{if(e.key==="Escape"&&!busy){setOpen(false);setDetailOf(null);setAssignOpen(false);}};
    addEventListener("keydown",onKey);
    return()=>removeEventListener("keydown",onKey);
  });

  // 打开「指定对接人」面板时拉取可指派的用户（仅启用的）
  useEffect(() => {
    if(!assignOpen)return;
    let alive=true;
    request("/users").then((d: UserRow[])=>{if(alive)setUsers(d.filter(u=>u.is_active));}).catch(()=>{});
    return()=>{alive=false;};
  },[assignOpen,request]);

  // 打开动向明细抽屉时按需拉取该客户的动态
  useEffect(() => {
    if(!detailOf?.loading)return;
    let alive=true;
    request(`/customer-signals?offset=${detailOf.offset}&customer_id=${encodeURIComponent(detailOf.customer.id)}`)
      .then((d: {total:number;items:Signal[]})=>{if(alive)setDetailOf(p=>p&&{...p,signals:d.items,total:d.total,loading:false});})
      .catch((e: Error)=>{if(alive){setError(e.message);setDetailOf(p=>p&&{...p,loading:false});}});
    return()=>{alive=false;};
  },[detailOf?.loading,detailOf?.offset,detailOf?.customer.id,request]);

  function focus(){requestAnimationFrame(()=>{heading.current?.focus();});}
  function newCustomer(){setDraft(empty);setError("");setMessage("");setOpen(true);focus();}
  function edit(c:Customer){
    setDraft({id:c.id,name:c.name,aliases:c.aliases.join("\n"),urls:(c.reference_urls?.length?c.reference_urls:c.website?[c.website]:[]).join("\n")});
    setError("");setMessage("");setOpen(true);focus();
  }
  function cancel(){setDraft(empty);setError("");setMessage("");setOpen(false);}
  function openDetail(c:Customer){setEvidence(null);setDetailOf({customer:c,signals:[],total:0,offset:0,loading:true});requestAnimationFrame(()=>{detailTitle.current?.focus();});}
  function closeDetail(){setDetailOf(null);setEvidence(null);}
  function toggleSel(id:string){setSelected(p=>{const n=new Set(p); if(n.has(id))n.delete(id);else n.add(id); return n;});}
  function selAllPage(){
    setSelected(p=>{
      const ids=pageRows.map(c=>c.id);
      const all=ids.length>0&&ids.every(id=>p.has(id));
      const n=new Set(p);
      ids.forEach(id=>{ if(all)n.delete(id);else n.add(id); });
      return n;
    });
  }
  async function applyAssign(){
    setBusy(true);setError("");
    try{
      await request("/customers/batch-owner",{method:"POST",body:JSON.stringify({customer_ids:[...selected],owner_user_id:assignTarget||null})});
      const name=users.find(u=>u.id===assignTarget)?.display_name;
      setMessage(assignTarget?`已把 ${selected.size} 家客户的对接人指定为 ${name}。`:`已清除 ${selected.size} 家客户的对接人。`);
      setSelected(new Set());setAssignOpen(false);refresh();
    }catch(e){setError(e instanceof Error?e.message:"批量指定失败");}
    finally{setBusy(false);}
  }

  async function save(){
    if(!form.current?.reportValidity())return;
    const body={name:draft.name,aliases:draft.aliases.split(/[\n，,]/).map(s=>s.trim()).filter(Boolean),reference_urls:draft.urls,website:null};
    setBusy(true);setError("");
    try{
      if(draft.id){
        await request(`/customers/${draft.id}`,{method:"PATCH",body:JSON.stringify(body)});
        setMessage("客户配置已修改，保持原启停状态；当前批次完成后使用新配置。");
      }else{
        await request("/customers",{method:"POST",body:JSON.stringify(body)});
        setMessage("客户已加入，自动开始监测近30天的相关动态。");
      }
      setDraft(empty);setOpen(false);refresh();
    }catch(e){setError(e instanceof Error?e.message:"保存失败");}
    finally{setBusy(false);}
  }

  async function toggle(c: Customer) {
    setBusy(true);setMessage("");
    try {await request(`/rules/${c.rule_id}`,{method:"PATCH",body:JSON.stringify({enabled:!c.enabled})});refresh();setMessage(c.enabled?"已停止后续搜索，当前批次处理完毕后停止。":"已开始持续监测。");}
    catch(e) {setError(e instanceof Error?e.message:"操作失败");}
    finally {setBusy(false);}
  }

  const enabledCount = customers.filter(c=>c.enabled).length;
  const attention = customers.filter(c=>statusOf(c).tab==="attention").length;
  const counts: Record<Tab, number> = {
    all: customers.length,
    on: customers.filter(c=>statusOf(c).tab==="on").length,
    attention,
    off: customers.filter(c=>statusOf(c).tab==="off").length,
  };
  const q=query.trim().toLowerCase();
  const filtered=customers.filter(c=>{
    if(tab!=="all"&&statusOf(c).tab!==tab)return false;
    if(q&&!(c.name.toLowerCase().includes(q)||c.aliases.some(a=>a.toLowerCase().includes(q))))return false;
    return true;
  });
  const pages=Math.max(1,Math.ceil(filtered.length/pageSize));
  const current=Math.min(page,pages);
  const pageRows=filtered.slice((current-1)*pageSize,current*pageSize);

  if(!manage) return <SignalsReadOnly request={request} error={error} setError={setError}/>;

  return <>
    {error && <p className="error" role="alert">{error} <button type="button" onClick={refresh}>重试</button></p>}
    {message && <p className="success" role="status">{message}</p>}

    <div className="page-head">
      <div>
        <h1 className="page-title">客户动向</h1>
        <p className="page-sub">添加客户后自动检索其公开动态，每天更新。点条数看明细。</p>
      </div>
    </div>

    <div className="kpis">
      <div className="kpi"><div className="kpi-l">监测客户</div><div className="kpi-v num">{customers.length}<small>家</small></div><div className="kpi-d">{enabledCount} 家监测中 · {customers.length-enabledCount} 家已停止</div></div>
      <div className="kpi"><div className="kpi-l">需要关注</div><div className="kpi-v num c-amber">{attention}<small>家</small></div><div className="kpi-d">有客户搜不出结果，点状态看原因</div></div>
      <div className="kpi"><div className="kpi-l">近 30 天动向</div><div className="kpi-v num">{signalsTotal ?? "—"}<small>条</small></div><div className="kpi-d">点击「条数」查看该客户的动向明细</div></div>
    </div>

    <div className="seg-tabs" role="tablist" aria-label="按监测状态筛选">
      {TABS.map(t=><button key={t.key} type="button" role="tab" aria-selected={tab===t.key} className={tab===t.key?"active":""} onClick={()=>{setTab(t.key);setPage(1);}}>
        {t.label}<span className="n">{counts[t.key]}</span>
      </button>)}
      <button type="button" className="btn btn-primary btn-sm seg-new" onClick={newCustomer}><PlusIcon/>新增客户动向</button>
      <div className="search-box">
        <input type="search" aria-label="搜索客户" placeholder="搜索客户名称或简称…" value={query} onChange={e=>{setQuery(e.target.value);setPage(1);}}/>
      </div>
    </div>

    {selected.size>0&&<div className="batch-bar" role="toolbar" aria-label="批量操作">
      <span>已选 <b>{selected.size}</b> 家客户</span>
      <button type="button" className="btn btn-sm btn-primary" onClick={()=>{setAssignTarget("");setAssignOpen(true);}}>指定对接人</button>
      <button type="button" className="btn btn-sm btn-quiet" onClick={()=>setSelected(new Set())}>取消选择</button>
    </div>}

    <div className="table-card" ref={card}>
      <div className="table-scroll no-fade">
        <table className="rule-table fit">
          <thead><tr>
            <th style={{width:'4%'}}><input type="checkbox" aria-label="全选本页" checked={pageRows.length>0&&pageRows.every(c=>selected.has(c.id))} onChange={selAllPage}/></th>
            <th style={{width:'42%'}}>客户</th>
            <th style={{width:'13%'}}>近 30 天动向</th>
            <th style={{width:'15%'}}>最近入库</th>
            <th style={{width:'14%'}}>对接人</th>
            <th style={{width:'12%'}}>操作</th>
          </tr></thead>
          <tbody>
            {pageRows.map((c)=>{
              const s=statusOf(c);
              return <tr key={c.id}>
                <td className="sel-cell"><input type="checkbox" aria-label={`选择 ${c.name}`} checked={selected.has(c.id)} onChange={()=>toggleSel(c.id)} disabled={busy}/></td>
                <td>
                  <div className="cell-line">
                    <button type="button" className="cell-link" disabled={busy} onClick={()=>edit(c)} title="修改该客户">{c.name}</button>
                    <button type="button" className="edit-name" disabled={busy} onClick={()=>edit(c)} title="修改该客户" aria-label={`修改 ${c.name}`}><EditIcon/></button>
                    <span className={"st "+s.cls} title={s.note}>{s.text}</span>
                  </div>
                </td>
                <td><button type="button" className="count-cell" disabled={busy} onClick={()=>openDetail(c)} title="查看该客户的动向明细">{c.signal_count ?? 0} <small>条</small></button></td>
                <td className="muted">{dateTime(c.last_found_at)}</td>
                <td className="muted">{c.owner_name||"—"}</td>
                <td><div className="actions">
                  <button className="btn btn-sm btn-quiet" disabled={busy} onClick={()=>toggle(c)}>{c.enabled?"停止监测":"开始监测"}</button>
                </div></td>
              </tr>;
            })}
          </tbody>
        </table>
      </div>
      {filtered.length>0&&<div className="table-foot">
        <span>共 {filtered.length} 条 · 第 {current} / {pages} 页 · 每页 {pageSize} 条{q?` · 已搜索“${query}”`:''}{tab!=="all"?` · ${TABS.find(t=>t.key===tab)!.label}`:''}</span>
        <div className="chart-pager">
          <button className="btn btn-sm" disabled={current<=1} onClick={()=>setPage(current-1)}>上一页</button>
          <button className="btn btn-sm" disabled={current>=pages} onClick={()=>setPage(current+1)}>下一页</button>
        </div>
      </div>}
      {!filtered.length && <div className="empty">{customers.length && (q||tab!=="all") ? "没有符合条件的客户，试试调整搜索词或状态筛选。" : "还没有客户，点「新增客户动向」加第一家。"}</div>}
    </div>

    {open && <div className="drawer-layer">
      <div className="drawer-backdrop" onClick={cancel}/>
      <aside className="console-drawer" role="dialog" aria-modal="true" aria-labelledby="customer-editor-title">
        <button type="button" className="dr-close" onClick={cancel} aria-label="关闭编辑器">✕</button>
        <div className="dr-head">
          <div className="dr-eyebrow">{draft.id?"修改":"新增"} · 客户动向</div>
          <h2 className="dr-title" id="customer-editor-title" tabIndex={-1} ref={heading}>{draft.id?"修改客户":"新增客户动向"}</h2>
          <p className="dr-sub">填写企业全称即可，其他叫法能帮搜索更准。</p>
        </div>
        <div className="dr-body">
          <form ref={form} id="customer-form" aria-labelledby="customer-editor-title" onSubmit={e=>{e.preventDefault();void save();}}>
            <label htmlFor="customer-name">企业全称 <span className="opt">必填</span></label>
            <input id="customer-name" name="name" required minLength={2} maxLength={120} value={draft.name} disabled={busy} onChange={e=>setDraft({...draft,name:e.target.value})}/>
            <label htmlFor="customer-alias">其他叫法 <span className="opt">选填，逗号或换行分隔，最多 5 个</span></label>
            <textarea id="customer-alias" name="aliases" rows={3} maxLength={600} value={draft.aliases} disabled={busy} onChange={e=>setDraft({...draft,aliases:e.target.value})} placeholder={"例如：西安装备制造\n陕直股份"}/>
            <details className="adv">
              <summary>高级：加参考网址（选填）</summary>
              <label htmlFor="customer-site">参考网址 <span className="opt">逗号或换行分隔，最多 10 个</span></label>
              <textarea id="customer-site" name="reference_urls" rows={3} maxLength={10000} spellCheck={false} autoCapitalize="none" value={draft.urls} disabled={busy} onChange={e=>setDraft({...draft,urls:e.target.value})} placeholder={"https://企业官网\nhttps://自媒体主页"}/>
            </details>
            <p className="hint">系统会自动用企业全称和其他叫法去搜；参考网址只是帮搜索更准，不填也行。</p>
          </form>
        </div>
        <div className="dr-foot">
          <button type="button" className="btn" onClick={cancel} disabled={busy}>取消</button>
          <button type="submit" form="customer-form" className="btn btn-primary" disabled={busy}>{busy?"保存中…":draft.id?"修改":"开始监测"}</button>
        </div>
      </aside>
    </div>}

    {detailOf && <div className="drawer-layer">
      <div className="drawer-backdrop" onClick={closeDetail}/>
      <aside className="console-drawer" role="dialog" aria-modal="true" aria-labelledby="customer-detail-title">
        <button type="button" className="dr-close" onClick={closeDetail} aria-label="关闭动向明细">✕</button>
        <div className="dr-head">
          <div className="dr-eyebrow">客户动向明细 · 近 30 天</div>
          <h2 className="dr-title" id="customer-detail-title" tabIndex={-1} ref={detailTitle}>
            {detailOf.customer.name}
            <span className={"st "+statusOf(detailOf.customer).cls} style={{marginLeft:10,verticalAlign:"middle"}}>{statusOf(detailOf.customer).text}</span>
          </h2>
          <p className="dr-sub">上次自动检索 {dateTime(detailOf.customer.last_search_at)} · 最近入库 {dateTime(detailOf.customer.last_found_at)}</p>
        </div>
        <div className="dr-body">
          {detailOf.loading&&<p className="empty">正在读取动向…</p>}
          {!detailOf.loading&&!detailOf.signals.length&&<p className="empty">暂时没有新动向，系统每天自动复查。</p>}
          {!detailOf.loading&&detailOf.signals.map(s=><div className="signal-item" key={s.id}>
            <div className="signal-title">{s.url?<a href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a>:s.title}</div>
            <div className="cell-meta"><span className="chip">{s.topic}</span> 发布 {s.published_at||"—"} · 采集 {dateTime(s.created_at)}</div>
            {!!s.fragments?.length&&<div className="customer-fragments">{s.fragments.map((f,i)=><span key={i} title={f.text}>{f.text}</span>)}</div>}
            {s.url&&<button type="button" className="text-button" onClick={()=>evidence?.id===s.id?setEvidence(null):request(`/customer-signals/${s.id}`).then(d=>setEvidence({...d.evidence,id:s.id})).catch(e=>setError(e.message))}>{evidence?.id===s.id?"收起":s.content_kind==="search_excerpt"?"看搜索摘要":"展开原文"}</button>}
            {evidence?.id===s.id&&<div className="customer-evidence-inline">
              <small>{evidence.content_kind==="search_excerpt"?"只抓到搜索摘要，正文还没读取":"来源正文"}</small>
              <pre>{evidence.raw_content}</pre>
            </div>}
          </div>)}
        </div>
        <div className="dr-foot">
          <span className="dr-meta">共 {detailOf.total} 条 · 第 {detailOf.offset/30+1} 页</span>
          <div className="chart-pager">
            <button className="btn btn-sm" disabled={detailOf.loading||!detailOf.offset} onClick={()=>setDetailOf(p=>p&&{...p,offset:Math.max(0,p.offset-30),loading:true})}>上一页</button>
            <button className="btn btn-sm" disabled={detailOf.loading||detailOf.offset+30>=detailOf.total} onClick={()=>setDetailOf(p=>p&&{...p,offset:p.offset+30,loading:true})}>下一页</button>
          </div>
          <button type="button" className="btn btn-primary" onClick={closeDetail}>关闭</button>
        </div>
      </aside>
    </div>}

    {assignOpen && <div className="drawer-layer">
      <div className="drawer-backdrop" onClick={()=>setAssignOpen(false)}/>
      <aside className="console-drawer" role="dialog" aria-modal="true" aria-labelledby="assign-owner-title">
        <button type="button" className="dr-close" onClick={()=>setAssignOpen(false)} aria-label="关闭指定对接人">✕</button>
        <div className="dr-head">
          <div className="dr-eyebrow">批量操作 · 客户动向</div>
          <h2 className="dr-title" id="assign-owner-title" tabIndex={-1}>指定对接人</h2>
          <p className="dr-sub">为已选 {selected.size} 家客户统一指定对接人，后续按人推送时以此为准。</p>
        </div>
        <div className="dr-body">
          {!users.length&&<p className="empty">正在读取用户列表…</p>}
          <div className="assign-list" role="radiogroup" aria-label="选择对接人">
            <button type="button" role="radio" aria-checked={assignTarget===""} className={"assign-item"+(assignTarget===""?" on":"")} onClick={()=>setAssignTarget("")}>
              <span className="assign-dot" aria-hidden/><span className="assign-name">暂不指定</span>
            </button>
            {users.map(u=><button type="button" role="radio" aria-checked={assignTarget===u.id} key={u.id} className={"assign-item"+(assignTarget===u.id?" on":"")} onClick={()=>setAssignTarget(u.id)}>
              <span className="assign-dot" aria-hidden/><span className="assign-name">{u.display_name}</span>
            </button>)}
          </div>
        </div>
        <div className="dr-foot">
          <button type="button" className="btn" onClick={()=>setAssignOpen(false)} disabled={busy}>取消</button>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={()=>void applyAssign()}>{busy?"保存中…":"确认指定"}</button>
        </div>
      </aside>
    </div>}
  </>;
}

function SignalsReadOnly({request,error,setError}:{request:Request;error:string;setError:(s:string)=>void}){
  const [result,setResult]=useState<{total:number;items:Signal[]}|null>(null);
  const [offset,setOffset]=useState(0);
  const [query,setQuery]=useState("");
  useEffect(()=>{
    let alive=true;
    request(`/customer-signals?offset=${offset}`).then(d=>{if(alive)setResult(d);}).catch(e=>{if(alive)setError(e.message);});
    return()=>{alive=false;};
  },[request,offset]);
  const items=(result?.items||[]).filter(s=>{const q=query.trim().toLowerCase();return !q||s.customer_name.toLowerCase().includes(q)||s.title.toLowerCase().includes(q);});
  return <>
    {error&&<p className="error" role="alert">{error}</p>}
    <div className="page-head"><div><h1 className="page-title">客户动向</h1><p className="page-sub">客户名称命中、主题相关、发布时间在近 30 天内的入库信息。</p></div></div>
    <div className="seg-tabs"><div className="search-box"><input type="search" placeholder="搜索客户或标题…" value={query} onChange={e=>setQuery(e.target.value)}/></div></div>
    <div className="table-card">
      <div className="table-scroll">
        <table className="rule-table">
          <thead><tr><th style={{minWidth:200}}>客户 / 主题</th><th style={{minWidth:320}}>标题与原文片段</th><th>发布时间</th><th>采集时间</th></tr></thead>
          <tbody>{items.map(s=><tr key={s.id}>
            <td><div className="cell-main"><div className="cell-name">{s.customer_name}</div><div className="cell-meta">{s.topic}</div></div></td>
            <td><div className="signal-title">{s.url?<a href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a>:s.title}</div>
              {!!s.fragments?.length&&<div className="customer-fragments">{s.fragments.map((f,i)=><span key={i} title={f.text}>{f.text}</span>)}</div>}</td>
            <td className="muted">{s.published_at||"—"}</td><td className="muted">{dateTime(s.created_at)}</td>
          </tr>)}</tbody>
        </table>
      </div>
      {result&&!items.length&&<div className="empty">近 30 天暂无动向。</div>}
      {result&&result.total>30&&<div className="table-foot">
        <span>共 {result.total} 条 · 第 {offset/30+1} 页</span>
        <div className="chart-pager">
          <button className="btn btn-sm" disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-30))}>上一页</button>
          <button className="btn btn-sm" disabled={offset+30>=result.total} onClick={()=>setOffset(offset+30)}>下一页</button>
        </div>
      </div>}
      {!result&&<div className="empty">正在读取动向…</div>}
    </div>
  </>;
}
