import { useState } from "react";
import { clock, errors, status } from "./types";
import type { Task } from "./types";
type Tab = "all" | "running" | "attention" | "done";
const TABS: { key: Tab; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "running", label: "进行中" },
  { key: "attention", label: "需要处理" },
  { key: "done", label: "已完成" },
];
function tabOf(t: Task): Tab {
  if (t.status === "failed" || t.status === "action_required") return "attention";
  if (["queued", "running", "retry_wait"].includes(t.status)) return "running";
  return "done";
}

export function Tasks({tasks, onRetry}: {tasks: Task[]; onRetry: (t: Task) => Promise<unknown> | void}) {
  const [tab, setTab] = useState<Tab>("all");
  const [query, setQuery] = useState("");
  const [retrying, setRetrying] = useState(false);
  const retry = async (t: Task) => {
    setRetrying(true);
    try { await onRetry(t); } finally { setRetrying(false); }
  };
  const running = tasks.filter(t => tabOf(t) === "running").length;
  const attention = tasks.filter(t => tabOf(t) === "attention").length;
  const q = query.trim().toLowerCase();
  const filtered = tasks.filter(t => {
    if (tab !== "all" && tabOf(t) !== tab) return false;
    if (q && !((errors[t.error_code || ""] || t.error_code || "").toLowerCase().includes(q))) return false;
    return true;
  });
  return <>
    <div className="page-head">
      <div>
        <h1 className="page-title">任务运行</h1>
        <p className="page-sub">每次采集和入库都会留下记录，出问题的任务可以重试。</p>
      </div>
    </div>

    <div className="kpis">
      <div className="kpi"><div className="kpi-l">最近任务</div><div className="kpi-v num">{tasks.length}<small>条</small></div><div className="kpi-d">系统保留最近 50 条任务记录</div></div>
      <div className="kpi"><div className="kpi-l">进行中</div><div className="kpi-v num c-green">{running}<small>条</small></div><div className="kpi-d">排队或正在执行的任务</div></div>
      <div className="kpi"><div className="kpi-l">需要处理</div><div className="kpi-v num c-amber">{attention}<small>条</small></div><div className="kpi-d">失败或需要人工介入的任务，可重试</div></div>
    </div>

    <div className="seg-tabs" role="tablist" aria-label="按任务状态筛选">
      {TABS.map(t => <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} className={tab === t.key ? "active" : ""} onClick={() => setTab(t.key)}>
        {t.label}<span className="n">{t.key === "all" ? tasks.length : t.key === "running" ? running : t.key === "attention" ? attention : tasks.length - running - attention}</span>
      </button>)}
      <div className="search-box">
        <input type="search" aria-label="搜索任务原因" placeholder="搜索任务原因…" value={query} onChange={e => setQuery(e.target.value)} />
      </div>
    </div>

    <div className="table-card">
      <div className="table-scroll no-fade">
        <table className="rule-table fit">
          <thead><tr>
            <th style={{width: '20%'}}>开始时间</th>
            <th style={{width: '14%'}}>阶段</th>
            <th style={{width: '14%'}}>状态</th>
            <th style={{width: '8%'}}>尝试</th>
            <th style={{width: '32%'}}>原因</th>
            <th style={{width: '12%'}}>操作</th>
          </tr></thead>
          <tbody>
            {filtered.map(t => <tr key={t.id}>
              <td className="muted">{clock(t.created_at)}</td>
              <td>{t.kind === "search" ? "发现来源" : "清洗入库"}</td>
              <td><span className={"st st-" + t.status}>{status[t.status] || t.status}</span></td>
              <td>{t.attempts}</td>
              <td>{t.error_code ? errors[t.error_code] || t.error_code : "—"}</td>
              <td><div className="actions">
                {["failed", "action_required"].includes(t.status)
                  ? <button className="btn btn-sm btn-quiet" disabled={retrying} onClick={() => void retry(t)}>重试</button>
                  : <span className="muted">—</span>}
              </div></td>
            </tr>)}
          </tbody>
        </table>
      </div>
      {!filtered.length && <div className="empty">{tasks.length && (q || tab !== "all") ? "没有符合条件的任务，试试调整搜索词或状态筛选。" : "还没有任务记录。"}</div>}
    </div>
  </>;
}
