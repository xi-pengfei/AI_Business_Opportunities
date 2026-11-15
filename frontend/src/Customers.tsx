import { useCallback, useEffect, useRef, useState } from "react";
import { errors } from "./types";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type Customer = { id: string; name: string; aliases: string[]; website?: string; reference_urls?:string[]; rule_id: string; enabled: boolean; query?: string; state: string; error_code?: string; last_search_at?: number; last_found_at?: number; next_run_at: number };
type Signal = { id: string; customer_name: string; title: string; url?: string; topic: string; fragments?: {text:string}[]; published_at?: string; created_at: number; matched_name?: string };
type Draft = { id?: string; name: string; aliases: string; urls: string };
const empty: Draft = { name: "", aliases: "", urls: "" };
const dateTime = (value?: number) => value ? new Date(value * 1000).toLocaleString("zh-CN", {timeZone:"Asia/Shanghai", hour12:false}) : "—";
const PlusIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><path d="M12 5v14M5 12h14"/></svg>;

function statusOf(c: Customer): { cls: string; text: string; note?: string } {
  if (!c.enabled) return { cls: "st-off", text: "已停止" };
  if (c.error_code) return { cls: "st-failed", text: "入口受限", note: errors[c.error_code] || "搜索入口等待恢复" };
  if (c.state === "running") return { cls: "st-on", text: "正在搜索" };
  if (!c.last_search_at) return { cls: "st-wait", text: "等待首次搜索" };
  if (c.next_run_at > Date.now() / 1000) return { cls: "st-wait", text: "等待复查新增" };
  return { cls: "st-on", text: "持续监测中" };
}

export function Customers({request, manage = false}: {request: Request; manage?: boolean}) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [result, setResult] = useState<{total:number;items:Signal[]} | null>(null);
  const [selected, setSelected] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [detail, setDetail] = useState<{evidence:{title:string;raw_content:string;content_kind:string}} | null>(null);
  const [draft, setDraft] = useState<Draft>(empty);
  const [open, setOpen] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const refresh = useCallback(() => setRevision(n=>n+1), []);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const [signals, rows] = await Promise.all([
          request(`/customer-signals?offset=${offset}${selected ? `&customer_id=${encodeURIComponent(selected)}` : ""}`),
          manage ? request("/customers") : Promise.resolve([]),
        ]);
        if (alive) {setResult(signals);setCustomers(rows);setError("");}
      } catch(e) {if(alive) setError(e instanceof Error ? e.message : "监控动态读取失败");}
      finally {if(alive) timer=setTimeout(load,10000);}
    };
    void load();
    return () => {alive=false;clearTimeout(timer);};
  },[request,manage,selected,offset,revision]);

  useEffect(() => {
    if(!open)return;
    const onKey=(e:KeyboardEvent)=>{if(e.key==="Escape"&&!busy)cancel();};
    addEventListener("keydown",onKey);
    return()=>removeEventListener("keydown",onKey);
  });

  function focus(){requestAnimationFrame(()=>{heading.current?.focus();});}
  function newCustomer(){setDraft(empty);setError("");setMessage("");setOpen(true);focus();}
  function edit(c:Customer){
    setDraft({id:c.id,name:c.name,aliases:c.aliases.join("\n"),urls:(c.reference_urls?.length?c.reference_urls:c.website?[c.website]:[]).join("\n")});
    setError("");setMessage("");setOpen(true);focus();
  }
  function cancel(){setDraft(empty);setError("");setMessage("");setOpen(false);}

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
  const attention = customers.filter(c=>c.enabled&&(c.error_code||!c.last_search_at)).length;
  const selectedName = customers.find(c=>c.id===selected)?.name;

  return <>
    {error && <p className="error" role="alert">{error} <button type="button" onClick={refresh}>重试</button></p>}
    {message && <p className="success" role="status">{message}</p>}

    <div className="page-head">
      <div>
        <h1 className="page-title">客户监控</h1>
        <p className="page-sub">把命中商机归到客户身上，持续追踪招采、扩产、产能、信息化等信号变化。填写企业全称即可开始，参考网址用于辅助搜索。</p>
      </div>
      {manage && <div className="page-actions">
        <button type="button" className="btn btn-primary" onClick={newCustomer}><PlusIcon/>新增客户监控</button>
      </div>}
    </div>

    {manage && <div className="kpis">
      <div className="kpi"><div className="kpi-l">监测客户</div><div className="kpi-v num">{customers.length}<small>家</small></div><div className="kpi-d">{enabledCount} 家已开启 · {customers.length-enabledCount} 家已停止</div></div>
      <div className="kpi"><div className="kpi-l">近 30 天动态</div><div className="kpi-v num">{result?.total ?? "—"}<small>条</small></div><div className="kpi-d">{selected?`已筛选：${selectedName||"指定客户"}`:"全部客户合计"}</div></div>
      <div className="kpi"><div className="kpi-l">需要关注</div><div className="kpi-v num">{attention}<small>家</small></div><div className="kpi-d">搜索入口异常或等待首次搜索</div></div>
    </div>}

    {manage && <div className="table-card">
      <div className="table-scroll">
        <table className="rule-table">
          <thead>
            <tr>
              <th style={{minWidth:240}}>客户</th>
              <th>监测状态</th>
              <th>最近搜索</th>
              <th>最后新增</th>
              <th style={{width:170}}>操作</th>
            </tr>
          </thead>
          <tbody>
            {customers.map(c=>{
              const s=statusOf(c);
              const urls=(c.reference_urls?.length?c.reference_urls:c.website?[c.website]:[]);
              return <tr key={c.id}>
                <td><div className="cell-main">
                  <div className="cell-name">{c.name}</div>
                  <div className="cell-meta" title={c.query?`当前搜索：${c.query}`:undefined}>参考网址 {urls.length} 个{c.query?" · 正在搜索":""}</div>
                  {c.aliases.length>0&&<div className="chip-row">{c.aliases.slice(0,3).map(a=><span className="chip" key={a}>{a}</span>)}{c.aliases.length>3&&<span className="chip">+{c.aliases.length-3}</span>}</div>}
                </div></td>
                <td><div className="cell-main">
                  <div><span className={"st "+s.cls}>{s.text}</span></div>
                  {s.note&&<div className="cell-meta">{s.note}</div>}
                </div></td>
                <td className="muted">{dateTime(c.last_search_at)}</td>
                <td className="muted">{dateTime(c.last_found_at)}</td>
                <td><div className="actions">
                  <button className="btn btn-sm" disabled={busy} onClick={()=>edit(c)}>修改</button>
                  <button className="btn btn-sm btn-quiet" disabled={busy} onClick={()=>toggle(c)}>{c.enabled?"停止监测":"开始监测"}</button>
                </div></td>
              </tr>;
            })}
          </tbody>
        </table>
      </div>
      {!customers.length && <div className="empty">还没有客户。点击右上角「新增客户监控」，填写企业全称即可自动开始监测近 30 天动态。</div>}
    </div>}

    <div className="section-head">
      <div>
        <h2>监控动态 <small>{result?.total ?? "—"} 条 · 近 30 天</small></h2>
        <p className="section-sub">客户名称命中、主题相关、发布时间在近 30 天内的入库信息。</p>
      </div>
      {manage && <div className="section-actions">
        <label className="customer-filter">客户
          <select value={selected} onChange={e=>{setSelected(e.target.value);setOffset(0);setResult(null);setDetail(null);}}>
            <option value="">全部客户</option>
            {customers.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
      </div>}
    </div>

    <div className="table-card customer-signals">
      <div className="table-scroll">
        <table className="rule-table">
          <thead><tr>
            <th style={{minWidth:200}}>客户 / 主题</th>
            <th style={{minWidth:320}}>标题与原文片段</th>
            <th>发布时间</th>
            <th>采集时间</th>
          </tr></thead>
          <tbody>{result?.items.map(s=><tr key={s.id}>
            <td><div className="cell-main">
              <div className="cell-name">{s.customer_name}</div>
              <div className="cell-meta">{s.topic}</div>
            </div></td>
            <td>
              <div className="signal-title">{s.url?<a href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a>:s.title}</div>
              {!!s.fragments?.length && <div className="customer-fragments">{s.fragments.map((f,i)=><span key={i} title={f.text}>{f.text}</span>)}</div>}
              {manage && s.url && <button type="button" className="text-button" onClick={()=>request(`/customer-signals/${s.id}`).then(setDetail).catch(e=>setError(e.message))}>查看采集原文</button>}
            </td>
            <td className="muted">{s.published_at||"—"}</td>
            <td className="muted">{dateTime(s.created_at)}</td>
          </tr>)}</tbody>
        </table>
      </div>
      {result && !result.items.length && <div className="empty">尚未找到符合客户名称、主题和近 30 天日期要求的信息。监测会继续轮换搜索，并复查新增。</div>}
      {result && result.total>30 && <div className="table-foot">
        <span>共 {result.total} 条 · 第 {offset/30+1} 页</span>
        <div className="chart-pager">
          <button className="btn btn-sm" disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-30))}>上一页</button>
          <button className="btn btn-sm" disabled={offset+30>=result.total} onClick={()=>setOffset(offset+30)}>下一页</button>
        </div>
      </div>}
      {!result && <div className="empty">正在读取监控动态…</div>}
    </div>

    {detail && <section className="panel customer-evidence" aria-label="监控动态采集原文">
      <div className="detail-title"><h3>{detail.evidence.title}</h3><button type="button" className="btn btn-sm" onClick={()=>setDetail(null)}>关闭原文</button></div>
      <small>{detail.evidence.content_kind==="search_excerpt"?"搜索摘要，尚未读取完整正文":"来源正文"}</small>
      <pre>{detail.evidence.raw_content}</pre>
    </section>}

    {open && <div className="drawer-layer">
      <div className="drawer-backdrop" onClick={cancel}/>
      <aside className="console-drawer" role="dialog" aria-modal="true" aria-labelledby="customer-editor-title">
        <button type="button" className="dr-close" onClick={cancel} aria-label="关闭编辑器">✕</button>
        <div className="dr-head">
          <div className="dr-eyebrow">{draft.id?"修改":"新建"} · 客户监测</div>
          <h2 className="dr-title" id="customer-editor-title" tabIndex={-1} ref={heading}>{draft.id?"修改客户监测":"新增客户监控"}</h2>
          <p className="dr-sub">填写企业全称即可，简称与参考网址帮助搜索更准。</p>
        </div>
        <div className="dr-body">
          <form ref={form} id="customer-form" aria-labelledby="customer-editor-title" onSubmit={e=>{e.preventDefault();void save();}}>
            <label htmlFor="customer-name">企业全称 <span className="opt">必填</span></label>
            <input id="customer-name" name="name" required minLength={2} maxLength={120} value={draft.name} disabled={busy} onChange={e=>setDraft({...draft,name:e.target.value})}/>
            <label htmlFor="customer-alias">常用简称 <span className="opt">选填，每行一个，最多 5 个</span></label>
            <textarea id="customer-alias" name="aliases" rows={3} maxLength={600} value={draft.aliases} disabled={busy} onChange={e=>setDraft({...draft,aliases:e.target.value})} placeholder={"例如：西安装备制造\n陕直股份"}/>
            <label htmlFor="customer-site">参考网址 <span className="opt">选填，逗号或换行分隔，最多 10 个</span></label>
            <textarea id="customer-site" name="reference_urls" rows={3} maxLength={10000} spellCheck={false} autoCapitalize="none" value={draft.urls} disabled={busy} onChange={e=>setDraft({...draft,urls:e.target.value})} placeholder={"https://企业官网\nhttps://自媒体主页"}/>
            <p className="hint">查找该客户的招采、扩产、产能、信息化和智能制造动态。参考网址用于辅助搜索，范围不限于这些网站；需要登录的平台仍需单独接入。</p>
          </form>
        </div>
        <div className="dr-foot">
          <button type="button" className="btn" onClick={cancel} disabled={busy}>取消</button>
          <button type="submit" form="customer-form" className="btn btn-primary" disabled={busy}>{busy?"正在保存…":draft.id?"保存修改":"保存并开始监测"}</button>
        </div>
      </aside>
    </div>}
  </>;
}
