import { useCallback, useEffect, useRef, useState } from "react";
import { errors, type Request } from "./types";
import "./xiaohongshu.css";

type XhsAccount = {
  id: string; name: string; url: string; token: string;
  owner_user_id: string | null; owner_name: string | null;
  enabled: boolean; created_at: number;
  rule: { id: string | null; query: string; enabled: boolean; state: string; error_code: string | null; next_run_at: number };
  runs_total: number;
};
type RunRow = { id: string; query: string; status: string; attempts: number; error_code: string | null; discovered: number; created_at: number; updated_at: number };
type Me = { id: string; role: string; display_name: string; username: string } | null;
type Draft = { id?: string; name: string; url: string; token: string; query: string };
const empty: Draft = { name: "", url: "", token: "", query: "" };
const dateTime = (value?: number) => value ? new Date(value * 1000).toLocaleString("zh-CN", {timeZone:"Asia/Shanghai", hour12:false}) : "—";
const RUN_STATUS: Record<string, string> = {
  queued: "等待执行", running: "执行中", succeeded: "已完成",
  failed: "失败", action_required: "需要处理", cancelled: "已取消",
};
const PlusIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><path d="M12 5v14M5 12h14"/></svg>;
const EditIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>;

type Status = { cls: string; text: string; note?: string; tab: "on" | "attention" | "off" };
function statusOf(a: XhsAccount): Status {
  if (!a.enabled || !a.rule.enabled) return { cls: "st-off", text: "已停止", tab: "off" };
  const code = a.rule.error_code;
  if (code === "xhs_login_required") return { cls: "st-failed", text: "登录失效", note: errors[code], tab: "attention" };
  if (code === "xhs_verification_required") return { cls: "st-failed", text: "需要验证", note: errors[code], tab: "attention" };
  if (code) return { cls: "st-failed", text: "采集异常", note: errors[code] || "采集入口等待恢复", tab: "attention" };
  if (a.rule.state === "running") return { cls: "st-on", text: "采集中", tab: "on" };
  return { cls: "st-on", text: "监测中", note: `下次复查 ${dateTime(a.rule.next_run_at)}`, tab: "on" };
}

type Tab = "all" | "on" | "attention" | "off";
const TABS: { key: Tab; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "on", label: "监测中" },
  { key: "attention", label: "需要关注" },
  { key: "off", label: "已停止" },
];

export function Xiaohongshu({request, me}: {request: Request; me: Me}) {
  const [accounts, setAccounts] = useState<XhsAccount[]>([]);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(() => setRevision(n=>n+1), []);
  const explain = (e:unknown) => { const text = e instanceof Error ? e.message : "操作失败，请重试"; return errors[text] || text; };
  // 顶部状态菜单 + 模糊搜索
  const [tab, setTab] = useState<Tab>("all");
  const [query, setQuery] = useState("");
  // 新建 / 修改抽屉
  const [draft, setDraft] = useState<Draft>(empty);
  const [open, setOpen] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  // 扫码登录抽屉（每账号一路登录态）
  const [qrOf, setQrOf] = useState<{account: XhsAccount; img: string; expires: number} | null>(null);
  const qrTitle = useRef<HTMLHeadingElement>(null);
  // 爬取批次明细抽屉（点数字链接打开）
  const [runsOf, setRunsOf] = useState<{account: XhsAccount; total: number; items: RunRow[]} | null>(null);
  const runsTitle = useRef<HTMLHeadingElement>(null);

  const canManage = (a: XhsAccount) => !!me && (me.role === "admin" || a.owner_user_id === me.id);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const d = await request("/xiaohongshu");
        if (alive) { setAccounts(d.accounts); setError(""); }
      } catch(e) { if (alive) setError(explain(e)); }
      finally { if (alive) timer = setTimeout(load, 10000); }
    };
    void load();
    return () => { alive = false; clearTimeout(timer); };
  }, [request, revision]);

  // 扫码后轮询登录状态；二维码 2 分钟过期
  useEffect(() => {
    if (!qrOf) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (Date.now() > qrOf.expires) { if (alive) { setQrOf(null); setMessage("二维码已过期，请重新获取。"); } return; }
      try {
        const r = await request(`/xiaohongshu/accounts/${qrOf.account.id}/login/status`, {method:"POST", signal:AbortSignal.timeout(50000)});
        if (r.is_logged_in) {
          if (alive) { setQrOf(null); setMessage(`${qrOf.account.name} 登录成功，等待中的采集任务会自动继续。`); refresh(); }
          return;
        }
      } catch { /* 瞬时失败不打断轮询 */ }
      if (alive) timer = setTimeout(poll, 15000);
    };
    timer = setTimeout(poll, 15000);
    return () => { alive = false; clearTimeout(timer); };
  }, [qrOf?.account.id, qrOf?.expires, request, refresh]);

  // 打开爬取批次明细抽屉时按需拉取
  useEffect(() => {
    if (!runsOf) return;
    let alive = true;
    request(`/xiaohongshu/accounts/${runsOf.account.id}/runs`)
      .then((d: {account: string; total: number; items: RunRow[]}) => { if (alive) setRunsOf(p => p && {account: p.account, total: d.total, items: d.items}); })
      .catch((e: Error) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [runsOf?.account.id, request]);

  useEffect(() => {
    if (!open && !qrOf && !runsOf) return;
    const onKey = (e:KeyboardEvent) => { if (e.key === "Escape" && !busy) { setOpen(false); setQrOf(null); setRunsOf(null); } };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [open, qrOf, runsOf, busy]);

  function focus(ref: React.RefObject<HTMLHeadingElement | null>) { requestAnimationFrame(() => { ref.current?.focus(); }); }
  function newAccount() { setDraft(empty); setError(""); setMessage(""); setOpen(true); focus(heading); }
  function edit(a: XhsAccount) {
    setDraft({id:a.id, name:a.name, url:a.url, token:"", query:a.rule.query});
    setError(""); setMessage(""); setOpen(true); focus(heading);
  }
  function cancel() { setDraft(empty); setError(""); setMessage(""); setOpen(false); }

  async function save() {
    if (!form.current?.reportValidity()) return;
    const body = {name:draft.name, url:draft.url, token:draft.token, query:draft.query || undefined};
    setBusy(true); setError("");
    try {
      if (draft.id) {
        await request(`/xiaohongshu/accounts/${draft.id}`, {method:"PATCH", body:JSON.stringify(body)});
        setMessage("账号已修改，采集会用新的关键词继续。");
      } else {
        await request("/xiaohongshu/accounts", {method:"POST", body:JSON.stringify(body)});
        setMessage("账号已加入。请先扫码登录，之后按关键词自动采集。");
      }
      setDraft(empty); setOpen(false); refresh();
    } catch(e) { setError(explain(e)); }
    finally { setBusy(false); }
  }

  async function toggle(a: XhsAccount) {
    setBusy(true); setMessage("");
    try {
      await request(`/xiaohongshu/accounts/${a.id}`, {method:"PATCH", body:JSON.stringify({name:a.name, url:a.url, enabled:!a.enabled})});
      setMessage(a.enabled ? "已停止该账号的采集。" : "已恢复该账号的采集。");
      refresh();
    } catch(e) { setError(explain(e)); }
    finally { setBusy(false); }
  }

  async function startScan(a: XhsAccount) {
    setBusy(true); setError(""); setMessage("");
    try {
      const r = await request(`/xiaohongshu/accounts/${a.id}/login/qrcode`, {method:"POST", signal:AbortSignal.timeout(50000)});
      if (r.is_logged_in) { setMessage(`${a.name} 已登录，无需扫码。`); refresh(); }
      else { setQrOf({account:a, img:r.img || "", expires:Date.now() + 120000}); focus(qrTitle); }
    } catch(e) { setError(explain(e)); }
    finally { setBusy(false); }
  }

  function openRuns(a: XhsAccount) { setRunsOf({account:a, total:0, items:[]}); requestAnimationFrame(() => { runsTitle.current?.focus(); }); }

  const attention = accounts.filter(a=>statusOf(a).tab==="attention").length;
  const enabledCount = accounts.filter(a=>statusOf(a).tab!=="off").length;
  const runsTotal = accounts.reduce((sum,a)=>sum+(a.runs_total||0),0);
  const counts: Record<Tab, number> = {
    all: accounts.length,
    on: accounts.filter(a=>statusOf(a).tab==="on").length,
    attention,
    off: accounts.filter(a=>statusOf(a).tab==="off").length,
  };
  const q = query.trim().toLowerCase();
  const filtered = accounts.filter(a=>{
    if (tab!=="all" && statusOf(a).tab!==tab) return false;
    if (q && !(a.name.toLowerCase().includes(q) || a.rule.query.toLowerCase().includes(q))) return false;
    return true;
  });

  return <>
    {error && <p className="error" role="alert">{error} <button type="button" onClick={refresh}>重试</button></p>}
    {message && <p className="success" role="status">{message}</p>}

    <div className="page-head">
      <div>
        <h1 className="page-title">小红书采集</h1>
        <p className="page-sub">每个账号一路独立登录，各自关键词并发采集；自己建的和管理员可操作，其他人只看。</p>
      </div>
    </div>

    <div className="kpis">
      <div className="kpi"><div className="kpi-l">采集账号</div><div className="kpi-v num">{accounts.length}<small>个</small></div><div className="kpi-d">{enabledCount} 个监测中 · {accounts.length-enabledCount} 个已停止</div></div>
      <div className="kpi"><div className="kpi-l">需要关注</div><div className="kpi-v num c-amber">{attention}<small>个</small></div><div className="kpi-d">登录失效或要求验证时，点状态看原因并扫码</div></div>
      <div className="kpi"><div className="kpi-l">累计爬取批次</div><div className="kpi-v num">{runsTotal}<small>次</small></div><div className="kpi-d">点行内「次数」查看该账号的批次明细</div></div>
    </div>

    <div className="seg-tabs" role="tablist" aria-label="按采集状态筛选">
      {TABS.map(t=><button key={t.key} type="button" role="tab" aria-selected={tab===t.key} className={tab===t.key?"active":""} onClick={()=>setTab(t.key)}>
        {t.label}<span className="n">{counts[t.key]}</span>
      </button>)}
      <button type="button" className="btn btn-primary btn-sm seg-new" onClick={newAccount}><PlusIcon/>新增账号</button>
      <div className="search-box">
        <input type="search" aria-label="搜索账号" placeholder="搜索账号名称或关键词…" value={query} onChange={e=>setQuery(e.target.value)}/>
      </div>
    </div>

    <div className="table-card">
      <div className="table-scroll no-fade">
        <table className="rule-table fit">
          <thead><tr>
            <th style={{width:'36%'}}>账号</th>
            <th style={{width:'26%'}}>关键词</th>
            <th style={{width:'12%'}}>爬取批次</th>
            <th style={{width:'12%'}}>建立人</th>
            <th style={{width:'14%'}}>操作</th>
          </tr></thead>
          <tbody>
            {filtered.map((a)=>{
              const s = statusOf(a);
              const keywords = a.rule.query.split("\n").map(s=>s.trim()).filter(Boolean);
              const manageable = canManage(a);
              return <tr key={a.id}>
                <td>
                  <div className="cell-line">
                    {manageable
                      ? <button type="button" className="cell-link" disabled={busy} onClick={()=>edit(a)} title="修改该账号">{a.name}</button>
                      : <span className="cell-name">{a.name}</span>}
                    {manageable && <button type="button" className="edit-name" disabled={busy} onClick={()=>edit(a)} title="修改该账号" aria-label={`修改 ${a.name}`}><EditIcon/></button>}
                    <span className={"st "+s.cls} title={s.note}>{s.text}</span>
                  </div>
                </td>
                <td>{keywords.length
                  ? <div className="customer-fragments">{keywords.slice(0,3).map((k,i)=><span key={i} title={k}>{k}</span>)}{keywords.length>3&&<span title="更多关键词见修改面板">+{keywords.length-3}</span>}</div>
                  : <span className="muted">—</span>}</td>
                <td><button type="button" className="count-cell" disabled={busy} onClick={()=>openRuns(a)} title="查看该账号的爬取批次明细">{a.runs_total ?? 0} <small>次</small></button></td>
                <td className="muted">{a.owner_name || "—"}</td>
                <td>{manageable
                  ? <div className="actions">
                      <button className="btn btn-sm btn-quiet" disabled={busy} onClick={()=>void startScan(a)}>扫码登录</button>
                      <button className="btn btn-sm btn-quiet" disabled={busy} onClick={()=>void toggle(a)}>{a.enabled?"停止":"开始"}</button>
                    </div>
                  : <span className="muted">只读</span>}</td>
              </tr>;
            })}
          </tbody>
        </table>
      </div>
      {!filtered.length && <div className="empty">{accounts.length && (q||tab!=="all") ? "没有符合条件的账号，试试调整搜索词或状态筛选。" : "还没有账号，点「新增账号」接入第一个小红书连接器。"}</div>}
    </div>

    {open && <div className="drawer-layer">
      <div className="drawer-backdrop" onClick={cancel}/>
      <aside className="console-drawer" role="dialog" aria-modal="true" aria-labelledby="xhs-editor-title">
        <button type="button" className="dr-close" onClick={cancel} aria-label="关闭编辑器">✕</button>
        <div className="dr-head">
          <div className="dr-eyebrow">{draft.id?"修改":"新增"} · 小红书采集</div>
          <h2 className="dr-title" id="xhs-editor-title" tabIndex={-1} ref={heading}>{draft.id?"修改账号":"新增账号"}</h2>
          <p className="dr-sub">一个账号就是一路独立连接器：自己的登录态、自己的关键词。</p>
        </div>
        <div className="dr-body">
          <form ref={form} id="xhs-form" aria-labelledby="xhs-editor-title" onSubmit={e=>{e.preventDefault();void save();}}>
            <label htmlFor="xhs-name">账号名称 <span className="opt">必填</span></label>
            <input id="xhs-name" name="name" required minLength={1} maxLength={120} value={draft.name} disabled={busy} onChange={e=>setDraft({...draft,name:e.target.value})} placeholder="例如：销售部小红书号"/>
            <label htmlFor="xhs-url">连接器地址 <span className="opt">必填，以 http(s):// 开头</span></label>
            <input id="xhs-url" name="url" required maxLength={500} spellCheck={false} autoCapitalize="none" value={draft.url} disabled={busy} onChange={e=>setDraft({...draft,url:e.target.value})} placeholder="http://小红书连接器服务地址"/>
            <label htmlFor="xhs-token">访问令牌 <span className="opt">{draft.id?"选填，留空保持原令牌":"选填"}</span></label>
            <input id="xhs-token" name="token" type="password" maxLength={500} autoComplete="off" value={draft.token} disabled={busy} onChange={e=>setDraft({...draft,token:e.target.value})} placeholder={draft.id?"留空则不修改":"连接器访问令牌，未设置可留空"}/>
            <label htmlFor="xhs-query">需求关键词 <span className="opt">必填，每行一组</span></label>
            <textarea id="xhs-query" name="query" rows={5} required maxLength={500} value={draft.query} disabled={busy} onChange={e=>setDraft({...draft,query:e.target.value})} placeholder={"例如：寻找软件开发团队\nERP系统改造 求推荐"}/>
            <p className="hint">系统按这些关键词持续搜索，保留近 30 天提出软件或信息化需求的帖子，过滤广告和教程。</p>
          </form>
        </div>
        <div className="dr-foot">
          <button type="button" className="btn" onClick={cancel} disabled={busy}>取消</button>
          <button type="submit" form="xhs-form" className="btn btn-primary" disabled={busy}>{busy?"保存中…":draft.id?"保存修改":"添加账号"}</button>
        </div>
      </aside>
    </div>}

    {qrOf && <div className="drawer-layer">
      <div className="drawer-backdrop" onClick={()=>setQrOf(null)}/>
      <aside className="console-drawer" role="dialog" aria-modal="true" aria-labelledby="xhs-qr-title">
        <button type="button" className="dr-close" onClick={()=>setQrOf(null)} aria-label="关闭扫码登录">✕</button>
        <div className="dr-head">
          <div className="dr-eyebrow">扫码登录 · 小红书采集</div>
          <h2 className="dr-title" id="xhs-qr-title" tabIndex={-1} ref={qrTitle}>{qrOf.account.name}</h2>
          <p className="dr-sub">用小红书 App 扫码，在手机上确认登录。登录成功后自动继续采集。</p>
        </div>
        <div className="dr-body xhs-qr-body">
          {qrOf.img && <img className="xhs-qr" src={qrOf.img} alt="小红书登录二维码，请使用小红书 App 扫描"/>}
          <p className="hint">二维码约 2 分钟后过期，过期后需重新获取。只读取搜索结果和笔记，不发布、不评论、不点赞。</p>
        </div>
        <div className="dr-foot">
          <button type="button" className="btn" disabled={busy} onClick={()=>void startScan(qrOf.account)}>重新获取二维码</button>
          <button type="button" className="btn btn-primary" onClick={()=>setQrOf(null)}>关闭</button>
        </div>
      </aside>
    </div>}

    {runsOf && <div className="drawer-layer">
      <div className="drawer-backdrop" onClick={()=>setRunsOf(null)}/>
      <aside className="console-drawer" role="dialog" aria-modal="true" aria-labelledby="xhs-runs-title">
        <button type="button" className="dr-close" onClick={()=>setRunsOf(null)} aria-label="关闭爬取批次明细">✕</button>
        <div className="dr-head">
          <div className="dr-eyebrow">爬取批次明细 · 最近 50 次</div>
          <h2 className="dr-title" id="xhs-runs-title" tabIndex={-1} ref={runsTitle}>{runsOf.account.name}</h2>
          <p className="dr-sub">当前关键词：{runsOf.account.rule.query.split("\n").filter(Boolean).join("；") || "—"}</p>
        </div>
        <div className="dr-body">
          {!runsOf.items.length && <p className="empty">正在读取批次记录…</p>}
          <div className="table-scroll">
            <table className="rule-table">
              <thead><tr><th>开始时间</th><th>状态</th><th>发现</th><th>尝试</th></tr></thead>
              <tbody>
                {runsOf.items.map(r=><tr key={r.id}>
                  <td>
                    <div className="cell-main">
                      <div className="cell-name">{dateTime(r.created_at)}</div>
                      {r.error_code && <div className="cell-meta">{errors[r.error_code]||r.error_code}</div>}
                    </div>
                  </td>
                  <td><span className={"st st-"+(r.status==="succeeded"?"on":r.status==="failed"||r.status==="action_required"?"failed":"wait")}>{RUN_STATUS[r.status]||r.status}</span></td>
                  <td>{r.discovered} <small>条</small></td>
                  <td>{r.attempts}</td>
                </tr>)}
              </tbody>
            </table>
          </div>
          {runsOf.items.length>0 && !runsOf.total && <p className="empty">暂无批次记录。</p>}
        </div>
        <div className="dr-foot">
          <span className="dr-meta">累计 {runsOf.total} 次</span>
          <button type="button" className="btn btn-primary" onClick={()=>setRunsOf(null)}>关闭</button>
        </div>
      </aside>
    </div>}
  </>;
}
