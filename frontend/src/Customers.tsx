import { useCallback, useEffect, useState } from "react";
import { errors } from "./types";

type Request = (path: string, options?: RequestInit) => Promise<any>;
type Customer = { id: string; name: string; aliases: string[]; website?: string; rule_id: string; enabled: boolean; query?: string; state: string; error_code?: string; last_search_at?: number; last_found_at?: number; next_run_at: number };
type Signal = { id: string; customer_name: string; title: string; url?: string; topic: string; fragments?: {text:string}[]; published_at?: string; created_at: number; matched_name?: string };
const dateTime = (value?: number) => value ? new Date(value * 1000).toLocaleString("zh-CN", {timeZone:"Asia/Shanghai", hour12:false}) : "—";

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
      } catch(e) {if(alive) setError(e instanceof Error ? e.message : "客户动态读取失败");}
      finally {if(alive) timer=setTimeout(load,10000);}
    };
    void load();
    return () => {alive=false;clearTimeout(timer);};
  },[request,manage,selected,offset,revision]);
  async function toggle(c: Customer) {
    setBusy(true);setMessage("");
    try {await request(`/rules/${c.rule_id}`,{method:"PATCH",body:JSON.stringify({enabled:!c.enabled})});refresh();setMessage(c.enabled?"已停止后续搜索，当前批次处理完毕后停止。":"已开始持续监测。");}
    catch(e) {setError(e instanceof Error?e.message:"操作失败");}
    finally {setBusy(false);}
  }
  return <div className="customer-monitor">
    {manage && <div className="rule-layout">
      <section className="panel">
        <h2 id="customer-create-title">新增客户监测</h2>
        <form aria-labelledby="customer-create-title" onSubmit={async e=>{
          e.preventDefault();const form=e.currentTarget;const fd=new FormData(form);
          setBusy(true);setMessage("");
          try {
            await request("/customers",{method:"POST",body:JSON.stringify({name:fd.get("name"),aliases:String(fd.get("aliases")||"").split(/[\n，,]/).map(s=>s.trim()).filter(Boolean),website:fd.get("website")||null})});
            form.reset();refresh();setMessage("客户已加入，自动开始监测近30天的相关动态。");
          } catch(e) {setError(e instanceof Error?e.message:"保存失败");}
          finally {setBusy(false);}
        }}>
          <label htmlFor="customer-name">企业全称（必填）</label><input id="customer-name" name="name" required minLength={2} maxLength={120} />
          <label htmlFor="customer-alias">常用简称（选填，每行一个，最多5个）</label><textarea id="customer-alias" name="aliases" maxLength={600} />
          <label htmlFor="customer-site">官网（选填）</label><input id="customer-site" name="website" type="url" maxLength={1000} spellCheck={false} autoCapitalize="none" />
          <button type="submit" disabled={busy}>{busy?"正在保存…":"保存并开始监测"}</button>
          <p className="hint">查找该客户的招采、扩产、产能、信息化和智能制造动态。官网作为身份参考，搜索范围不限于官网。</p>
        </form>
      </section>
      <section className="panel">
        <h2>监测客户 <small>{customers.length} 家</small></h2>
        {customers.map(c=><article className="rule" key={c.id}>
          <div><h3>{c.name}</h3><p>{c.aliases.join(" / ")}</p>
            <small>{!c.enabled?"已停止":c.error_code?(errors[c.error_code]||"搜索入口等待恢复"):c.state==="running"?"正在搜索":!c.last_search_at?"等待首次搜索／入口恢复":c.next_run_at>Date.now()/1000?"等待复查新增":"持续监测中"}</small>
            <small className="customer-meta">最后搜索：{dateTime(c.last_search_at)} · 最后新增：{dateTime(c.last_found_at)}</small>
            {c.query && <small className="customer-meta">当前搜索：{c.query}</small>}
            {c.website && <a href={c.website} target="_blank" rel="noopener noreferrer">官网</a>}
          </div>
          <button type="button" disabled={busy} onClick={()=>toggle(c)}>{c.enabled?"停止监测":"开始监测"}</button>
        </article>)}
        {!customers.length && <p className="empty">添加客户后自动开始监测。</p>}
      </section>
    </div>}
    <section className="panel customer-signals">
      <div className="detail-title"><h2>客户动态 <small>{result?.total ?? "—"} 条 · 近30天</small></h2>
        {manage && <label className="customer-filter">客户<select value={selected} onChange={e=>{setSelected(e.target.value);setOffset(0);setResult(null);setDetail(null);}}><option value="">全部客户</option>{customers.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}
      </div>
      {error && <p className="error" role="alert">{error} <button type="button" onClick={refresh}>重试</button></p>}
      {message && <p className="success" role="status">{message}</p>}
      {!result ? <p className="empty">正在读取客户动态…</p> : !result.items.length ? <p className="empty">尚未找到符合客户名称、主题和近30天日期要求的信息。监测会继续轮换搜索，并复查新增。</p> : <>
        <div className="customer-table" tabIndex={0} role="region" aria-label="客户动态记录">
          <table><thead><tr><th scope="col">客户 / 主题</th><th scope="col">标题与原文片段</th><th scope="col">发布时间</th><th scope="col">采集时间</th></tr></thead>
            <tbody>{result.items.map(s=><tr key={s.id}>
              <th scope="row"><span>{s.customer_name}</span><small className="customer-meta">{s.topic}</small></th>
              <td>{s.url?<a href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a>:s.title}
                <div className="customer-fragments">{s.fragments?.map((f,i)=><span key={i} title={f.text}>{f.text}</span>)}</div>
                {manage && s.url && <button type="button" className="text-button" onClick={()=>request(`/customer-signals/${s.id}`).then(setDetail).catch(e=>setError(e.message))}>查看采集原文</button>}
              </td><td>{s.published_at||"—"}</td><td>{dateTime(s.created_at)}</td>
            </tr>)}</tbody>
          </table>
        </div>
        {result.total>30 && <div className="chart-pager"><button disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-30))}>上一页</button><span>第 {offset/30+1} 页</span><button disabled={offset+30>=result.total} onClick={()=>setOffset(offset+30)}>下一页</button></div>}
      </>}
      {detail && <section className="customer-evidence" aria-label="客户动态采集原文"><div className="detail-title"><h3>{detail.evidence.title}</h3><button type="button" onClick={()=>setDetail(null)}>关闭原文</button></div><small>{detail.evidence.content_kind==="search_excerpt"?"搜索摘要，尚未读取完整正文":"来源正文"}</small><pre>{detail.evidence.raw_content}</pre></section>}
    </section>
  </div>;
}
