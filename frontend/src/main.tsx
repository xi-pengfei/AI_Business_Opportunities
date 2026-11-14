import React, { useState, useEffect, useRef, useCallback } from "react";
import { createRoot } from "react-dom/client";
import { Charts } from "./Charts";
import type { ChartSelection } from "./Charts";
import { expandCargo, landFragment, cargoKey } from "./fragments";
import type { Cargo } from "./fragments";
import {SourceFields, Information} from "./FlowPanels";
import {AutoScroll} from "./AutoScroll";
import { Customers } from "./Customers";
import { Spider } from "./Spider";
import { clock, status, errors } from "./types";
import type { Snapshot, Rule, Task, Item } from "./types";
import "./style.css";

const base = "/api/v1";
function App() {
  const [token, setToken] = useState("");
  const [draftToken, setDraftToken] = useState("");
  const [page, setPage] = useState(
    ["display", "rules", "customers", "tasks", "information"].includes(location.pathname.slice(1)) ? location.pathname.slice(1) : "rules",
  );
  const demo = false;
  const [chartSelection, setChartSelection] = useState<ChartSelection | null>(null);
  const [data, setData] = useState<Snapshot | null>(null);
  const [rules, setRules] = useState<Rule[]>([]),
    [tasks, setTasks] = useState<Task[]>([]),
    [items, setItems] = useState<Item[]>([]);
  const [connectionError, setConnectionError] = useState("");
  const [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [connected, setConnected] = useState(false);
  const [providers, setProviders] = useState<{
    searxng: { configured: boolean };
    tavily: { configured: boolean };
    demo: { enabled: boolean };
  } | null>(null);
  const [detail, setDetail] = useState<
    (Item & { evidence: { raw_content: string; content_kind: string } }) | null
  >(null);
  const [moving, setMoving] = useState<Cargo | null>(null);
  const cargoQueue = useRef<Cargo[]>([]);
  const currentCargo = useRef<Cargo | null>(null);
  const assignedIds = useRef(new Set<string>());
  const [library, setLibrary] = useState<Item[]>([]);
  const [landed, setLanded] = useState<Set<string>>(new Set());
  const activeCargo = useRef(false);
  const feedCursor = useRef<{after: number; after_id: string} | null>(null);
  const [terminalFeed, setTerminalFeed] = useState<Item[]>([]);
  const nextCargo = useCallback(() => {
    const next = cargoQueue.current.shift() || null;
    activeCargo.current = !!next;
    currentCargo.current = next;
    setMoving(next);
    // The terminal is a rolling stream: newest entry on top, the spider walks
    // up to it and the feed follows the spider instead of a scrollbar.
    if (next) setTerminalFeed(old => [next, ...old.filter(i => i.id !== next.id)].slice(0, 5));
  }, []);
  const completeCargo = useCallback(() => {
    const cargo = currentCargo.current;
    if (cargo) {
      if (!assignedIds.current.has(cargo.id)) setLibrary(old => landFragment(old, cargo));
      setLanded(old => new Set([...old, cargoKey(cargo)]));
    }
    nextCargo();
  }, [nextCargo]);
  const seen = useRef(new Set<string>()),
    hydrated = useRef(false);
  const [streamState, setStreamState] = useState("连接中");
  const refreshing = useRef(false);
  const activeView = useRef("");
  activeView.current = `${token}:${demo}:${page}`;
  const request = useCallback(
    async (path: string, options: RequestInit = {}) => {
      const response = await fetch(base + path, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          ...options.headers,
        },
        signal: options.signal ?? AbortSignal.timeout(15000),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(
          typeof result.detail === "string"
            ? result.detail
            : `请求失败 (${response.status})`,
        );
      }
      return response.json();
    },
    [token],
  );
  const refresh = useCallback(async () => {
    if (!token || refreshing.current) return;
    refreshing.current = true;
    const viewKey = `${token}:${demo}:${page}`;
    try {
      const snapshot: Snapshot = await request(
        `/display/snapshot?demo=${demo}`,
      );
      if (activeView.current !== viewKey) return;
      setData(snapshot);
      assignedIds.current = new Set(snapshot.assigned_items.map(i=>i.id));
      setLibrary(old=>old.filter(i=>!assignedIds.current.has(i.id)));
      setConnected(true);
      setConnectionError("");
      if (!hydrated.current) {
        feedCursor.current = {after: snapshot.server_time, after_id: ""};
        setTerminalFeed(snapshot.items.slice(0, 3));
        setLibrary(snapshot.items);
        setLanded(new Set(expandCargo(snapshot.items).map(cargoKey)));
      } else if (feedCursor.current && cargoQueue.current.length < 200) {
        const cursor = feedCursor.current;
        const feed = await request(`/display/feed?after=${cursor.after}&after_id=${encodeURIComponent(cursor.after_id)}`);
        if (activeView.current !== viewKey) return;
        feedCursor.current = {after: feed.after, after_id: feed.after_id};
        const plain = (feed.items as Item[]).filter(i => !i.fragments?.length);
        if (plain.length) setLibrary(old => [...plain, ...old.filter(i => !plain.some(p => p.id === i.id))].slice(0,30));
        cargoQueue.current.push(...expandCargo(feed.items));
        if (!activeCargo.current) nextCargo();
      }
      hydrated.current = true;
      if (page !== "display") {
        const [r, t, i, p] = await Promise.all([
          request("/rules"),
          request(`/tasks?demo=${demo}`),
          request(`/items?demo=${demo}`),
          request("/providers"),
        ]);
        if (activeView.current !== viewKey) return;
        setRules(r);
        setTasks(t);
        setItems(i);
        setProviders(p);
      }
    } catch (e) {
      if (activeView.current !== viewKey) return;
      setConnected(false);
      setConnectionError("连接暂时中断，正在自动重连");
    } finally {
      refreshing.current = false;
    }
  }, [token, demo, page, request, nextCargo]);
  useEffect(() => {
    setChartSelection(null);
    hydrated.current = false;
    seen.current.clear();
    setMoving(null);
    cargoQueue.current = []; currentCargo.current = null; setLibrary([]); setLanded(new Set()); activeCargo.current = false; feedCursor.current = null; setTerminalFeed([]);
    setData(null);
  }, [demo, token]);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      if (active) await refresh();
      if (active) timer = setTimeout(tick, 5000);
    };
    tick();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [refresh]);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  // Event stream reconnects from the last delivered cursor. Snapshot polling also repairs missed events.
  useEffect(() => {
    if (!token) return;
    const control = new AbortController();
    let cursor = 0;
    let stopped = false;
    let retryTimer: ReturnType<typeof setTimeout>;
    let refreshTimer: ReturnType<typeof setTimeout>;
    async function connect() {
      try {
        setStreamState("连接中");
        const response = await fetch(
          `${base}/display/events?demo=${demo}&after=${cursor}`,
          {
            headers: { Authorization: `Bearer ${token}` },
            signal: control.signal,
          },
        );
        if (!response.ok || !response.body) throw Error();
        setStreamState("事件已连接");
        const reader = response.body.getReader(),
          decoder = new TextDecoder();
        let buffer = "";
        while (!stopped) {
          const { done, value } = await reader.read();
          if (done) throw Error();
          buffer += decoder.decode(value, { stream: true });
          let end;
          while ((end = buffer.indexOf("\n\n")) >= 0) {
            const event = buffer.slice(0, end);
            buffer = buffer.slice(end + 2);
            const id = event.match(/^id: (\d+)/m);
            if (id) {
              cursor = Number(id[1]);
              clearTimeout(refreshTimer);
              refreshTimer = setTimeout(() => refreshRef.current(), 200);
            }
          }
        }
      } catch {
        if (!stopped) {
          setStreamState("事件重连中");
          retryTimer = setTimeout(connect, 3000);
        }
      }
    }
    connect();
    return () => {
      stopped = true;
      control.abort();
      clearTimeout(retryTimer);
      clearTimeout(refreshTimer);
    };
  }, [token, demo]);
  async function action(fn: () => Promise<unknown>, success: string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await fn();
      setMessage(success);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function navigate(next: string) {
    setPage(next);
    setDetail(null);
    setError("");
    setMessage("");
    history.pushState({}, "", next === "display" ? "/display" : `/${next}`);
  }
  useEffect(() => {
    const back = () => setPage(location.pathname.slice(1) || "rules");
    addEventListener("popstate", back);
    return () => removeEventListener("popstate", back);
  }, []);
  async function login(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await fetch(base + "/display/snapshot", {
        headers: { Authorization: `Bearer ${draftToken}` },
        signal: AbortSignal.timeout(15000),
      });
      if (!r.ok) throw Error("访问令牌无效或服务未就绪");
      setToken(draftToken);
      setDraftToken("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (!token)
    return (
      <main className="login panel">
        <h1>AI商机智能体</h1>
        <p>
          使用本机 .env 中的 ADMIN_TOKEN 登录管理台；展示令牌仅可查看脱敏大屏。
        </p>
        <form onSubmit={login}>
          <label>
            访问令牌
            <input
              aria-invalid="false"
              type="password"
              required
              autoComplete="off"
              value={draftToken}
              onChange={(e) => setDraftToken(e.target.value)}
            />
          </label>
          <button disabled={busy}>进入系统</button>
        </form>
        {connectionError && (
          <p className="error" role="status">
            {connectionError}
          </p>
        )}
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <small>令牌仅保留在当前页面内存，刷新后需要重新登录。</small>
      </main>
    );
  const display = page === "display";

  return (
    <main className={display ? "screen" : "workspace"}>
      <header className="mast">
        <h1>AI商机智能体</h1>
        <div className="toolbar">
          <button onClick={() => navigate(display ? "rules" : "display")}>
            {display ? "管理台" : "展示大屏"}
          </button>
          <button
            onClick={() => {
              setToken("");
              setData(null);
            }}
          >
            退出
          </button>
          {display && (
            <button
              onClick={() =>
                (document.fullscreenElement
                  ? document.exitFullscreen()
                  : document.documentElement.requestFullscreen()
                ).catch(() => setError("当前浏览器无法切换全屏"))
              }
            >
              全屏
            </button>
          )}
        </div>
      </header>
      {!display && (
        <nav aria-label="管理导航">
          {[
            ["rules", "采集规则"],
            ["customers", "客户监测"],
            ["tasks", "任务运行"],
            ["information", "信息库"],
          ].map(([key, label]) => (
            <button
              key={key}
              aria-current={page === key ? "page" : undefined}
              onClick={() => navigate(key)}
            >
              {label}
            </button>
          ))}
        </nav>
      )}
      {connectionError && (
        <p className="error" role="status">
          {connectionError}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="success" role="status">
          {message}
        </p>
      )}
      {display && data && (
        <>
          <div className="charts"><Charts data={data} onSelect={setChartSelection} onOpenItem={id=>{if(data.items.some(i=>i.url)) request(`/items/${id}`).then(setDetail).catch(e=>setError(e.message));}} /></div>
          {chartSelection && <ChartRecords key={`${chartSelection.start}:${chartSelection.end}:${chartSelection.provider || ""}:${chartSelection.region || ""}`}
            selection={chartSelection} request={request} close={() => setChartSelection(null)}
            open={(item) => request(`/items/${item.id}`).then(setDetail).catch(e => setError(e.message))} />}

          <div className="collector-strip">
            {data.collectors?.length ? (
              data.collectors.map((c) => (
                <section key={c.id}>
                  <strong>
                    {c.waiting_recheck ? "等待首页复查／入口恢复" : (
                      {
                        queued: "准备搜索",
                        running: "正在搜索",
                        cleaning: "清洗入库",
                        next_batch: "继续下一批",
                        retry_wait: "失败重试中",
                        action_required: "等待服务恢复",
                        failed: "本批失败",
                      } as Record<string, string>
                    )[c.state] || c.state}
                  </strong>
                  <span>{c.query || c.name}</span>
                  <small>{c.search_engine || '搜索服务'} · 第 {c.search_page || 1} 页
                    {c.search_outcome === 'empty' ? ' · 本次返回 0 条' : ''}
                    {c.search_outcome === 'partial_results' ? ' · 部分入口异常，已有结果继续处理' : ''}
                    {c.waiting_recheck ? ' · 等待重新检查搜索结果第一页' : ''}
                  </small>
                  <small>最后搜到结果：{c.last_result_at ? new Date(c.last_result_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}) : '尚未搜到'}
                    {' · '}最后新增商机：{c.last_opportunity_at ? new Date(c.last_opportunity_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}) : '尚无新增'}
                  </small>
                  <small>
                    第 {c.rounds} 批
                    {c.total > 0
                      ? ` · 已处理 ${c.done} / ${c.total} · 重复 ${c.duplicates}`
                      : ""}
                  </small>
                  {c.total > 0 && (
                    <progress
                      aria-label="本批处理进度"
                      value={c.done}
                      max={c.total}
                    />
                  )}
                  {c.error_code && ["retry_wait", "failed", "action_required"].includes(c.state) && (
                    <small>{errors[c.error_code] || c.error_code}</small>
                  )}
                </section>
              ))
            ) : (
              <span>采集已停止</span>
            )}
          </div>
          <div className="workfield">
            <section className="panel terminal">
              <h2>来源终端</h2>
              <div className="terminal-feed">
                {terminalFeed.map(entry => <article className={`source-preview ${moving?.id === entry.id ? "cargo-source" : ""}`} key={entry.id}>
                  <SourceFields item={entry} moving={moving} landed={landed} />
                </article>)}
              </div>
              <p>
                {data.collectors?.some((c) => c.state === "running")
                  ? "正在搜索新来源"
                  : data.collectors?.some((c) => c.state === "cleaning")
                    ? "正在清洗本批信息"
                    : data.collectors?.some(c => c.state === "retry_wait")
                      ? "搜索服务等待重试"
                    : data.collectors?.some(
                          (c) => c.state === "action_required",
                        )
                      ? "采集服务等待授权或额度恢复"
                      : data.collectors?.length
                        ? "自动衔接下一批"
                        : "采集已停止"}
              </p>
              {data.events.slice(0, 3).map((e) => (
                <div className="log" key={e.id}>
                  <time>{clock(e.created_at)}</time>
                  <span>
                    {e.kind === "item.created"
                      ? "信息已归集"
                      : e.kind === "item.duplicate"
                        ? "重复信息已合并"
                        : status[e.kind.split(".")[1]] || e.kind}
                  </span>
                  <code>{e.task_id.slice(0, 8)}</code>
                </div>
              ))}
              {!data.events.length && (
                <p className="empty">
                  尚无执行记录。请先在管理台创建规则并执行。
                </p>
              )}
            </section>
            <section className="panel library">
              <h2>
                信息库 · 待推送 <small>{data.pending_count} 条</small>
              </h2>
              <Information
                items={library}
                autoScroll={!moving}
                open={(item) => {
                  if (item.url)
                    request(`/items/${item.id}`)
                      .then(setDetail)
                      .catch((e) => setError(e.message));
                }}
              />
            </section>
            <Spider
              item={moving}
              onDelivered={completeCargo}
              searching={
                connected &&
                !!data.collectors?.some((c) =>
                  ["queued", "running", "cleaning", "retry_wait", "next_batch"].includes(c.state),
                )
              }
            />
          </div>
          <section className="panel assigned-library">
            <h2>已推送 / 认领 <small>{data.pushed_count} 条 · 已认领 {data.assigned_count} 条</small></h2>
            <AutoScroll enabled label="已推送与认领记录"><table><thead><tr><th>标题</th><th>认领人</th><th>推送时间</th><th>状态</th><th>认领时间</th></tr></thead>
              <tbody>{data.assigned_items.map(i=><tr key={i.id}><td><button className="text-button" onClick={()=>request(`/items/${i.id}`).then(setDetail)}>{i.title}</button></td><td>{i.claimed_by || "—"}</td><td>{i.sent_at?clock(i.sent_at):'—'}</td><td>{i.delivery_status==='restored'?'已恢复，回执待核实':i.delivery_status==='claimed'?'已认领':'待认领'}</td><td>{i.claimed_at?clock(i.claimed_at):'—'}</td></tr>)}</tbody>
            </table></AutoScroll>
            {!data.assigned_items.length && <p className="empty">{data.assignment_status==='not_configured'?'等待接入钉钉群 · 引用消息并 @机器人认领后发送下一条':'暂无已分配信息'}</p>}
          </section>
          <Customers request={request} />
        </>
      )}
      {!data && <div className="empty">正在读取运行状态…</div>}
      {!display && page === "customers" && <Customers request={request} manage />}
      {!display && page === "rules" && (
        <div className="rule-layout">
          <section className="panel">
            <h2>新建采集规则</h2>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const form = e.currentTarget,
                  fd = new FormData(form);
                action(async () => {
                  await request("/rules", {
                    method: "POST",
                    body: JSON.stringify({
                      name: fd.get("name"),
                      query: fd.get("query"),
                      provider: fd.get("provider"),
                      interval_seconds: 0,
                      max_results: 20,
                      enabled: true,
                    }),
                  });
                  form.reset();
                }, "规则已开始连续采集，可随时停止。");
              }}
            >
              <label>
                规则名称
                <input
                  name="name"
                  required
                  maxLength={120}
                  placeholder="例如：制造业数据平台需求"
                />
              </label>
              <label>
                搜索关键词（每行一组，自动轮转）
                <textarea
                  name="query"
                  required
                  maxLength={500}
                  placeholder="例如：制造业 ERP MES 数据打通 招标"
                />
              </label>
              <label>
                搜索服务
                <select name="provider">
                  <option value="searxng">SearXNG 自建搜索</option>
                  <option value="tavily">
                    Tavily 全网搜索
                    {providers && !providers.tavily.configured
                      ? "（待配置密钥）"
                      : ""}
                  </option>
                </select>
              </label>
              <button disabled={busy}>保存并开始采集</button>
              <p className="hint">
                自动轮转关键词并扩展地区；停止后完成当前批次，不再开始下一批。
              </p>
            </form>
          </section>
          <section className="panel">
            <h2>采集规则</h2>
            {!rules.length ? (
              <p className="empty">还没有规则。从左侧添加第一组关键词。</p>
            ) : (
              rules
                .filter((r) => r.provider !== "demo")
                .map((r) => (
                  <article className="rule" key={r.id}>
                    <div>
                      <h3>{r.name}</h3>
                      <p>{r.query}</p>
                      <small>
                        {r.interval_seconds === 0
                          ? "连续采集"
                          : `每 ${r.interval_seconds / 60} 分钟`}{" "}
                        · {r.enabled ? "运行中" : "已停止"}
                      </small>
                    </div>
                    <div className="actions">
                      <button
                        disabled={busy}
                        onClick={() =>
                          action(
                            () =>
                              request(`/rules/${r.id}/run`, {
                                method: "POST",
                                headers: {
                                  "Idempotency-Key": crypto.randomUUID(),
                                },
                              }),
                            "任务已进入队列。",
                          )
                        }
                      >
                        执行一次
                      </button>
                      <button
                        disabled={busy}
                        onClick={() =>
                          action(
                            () =>
                              request(`/rules/${r.id}`, {
                                method: "PATCH",
                                body: JSON.stringify({
                                  enabled: !r.enabled,
                                  interval_seconds: 0,
                                  max_results: 20,
                                }),
                              }),
                            r.enabled
                              ? "已停止后续调度，已入队任务继续执行。"
                              : "规则已启用。",
                          )
                        }
                      >
                        {r.enabled ? "停止" : "开始采集"}
                      </button>
                    </div>
                  </article>
                ))
            )}
          </section>
        </div>
      )}
      {!display && page === "tasks" && (
        <section className="panel">
          <h2>
            任务运行 <small>最近 50 条</small>
          </h2>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>任务</th>
                  <th>阶段</th>
                  <th>状态</th>
                  <th>尝试</th>
                  <th>原因</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <code>{t.id.slice(0, 8)}</code>
                      <small>{clock(t.created_at)}</small>
                    </td>
                    <td>{t.kind === "search" ? "发现来源" : "清洗入库"}</td>
                    <td>{status[t.status]}</td>
                    <td>{t.attempts}</td>
                    <td>
                      {t.error_code
                        ? errors[t.error_code] || t.error_code
                        : "—"}
                    </td>
                    <td>
                      {["failed", "action_required"].includes(t.status) && (
                        <button
                          disabled={busy}
                          onClick={() =>
                            action(
                              () =>
                                request(`/tasks/${t.id}/retry`, {
                                  method: "POST",
                                }),
                              "已重新入队。",
                            )
                          }
                        >
                          重试
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!tasks.length && <p className="empty">尚无任务。</p>}
        </section>
      )}
      {!display && page === "information" && (
        <section className="panel">
          <h2>
            信息库 <small>最近 50 条 · 原文待人工核实</small>
          </h2>
          <Information
            items={items}
            open={(item) =>
              request(`/items/${item.id}`)
                .then(setDetail)
                .catch((e) => setError(e.message))
            }
          />
        </section>
      )}
      {detail && (
        <section className="panel detail" aria-label="信息证据详情">
          <div className="detail-title">
            <h2>{detail.title}</h2>
            <button onClick={() => setDetail(null)}>关闭详情</button>
          </div>
          <p>
            {detail.evidence.content_kind === "search_excerpt"
              ? "搜索摘要（未获取完整正文）"
              : "来源正文"}{" "}
            · {clock(detail.created_at)}
          </p>
          <a href={detail.url} target="_blank" rel="noopener noreferrer">
            查看原始网址
          </a>
          {detail.region_evidence && <p>地区依据：{detail.region_evidence}</p>}
          <pre>{detail.evidence.raw_content}</pre>
        </section>
      )}
      <div className="notice" role="status">
        {connected ? "服务已连接" : "连接中断或等待服务"} · {streamState}
        {data && ` · 最后更新 ${clock(data.server_time)}`}
      </div>
    </main>
  );
}
function ChartRecords({ selection, request, close, open }: {
  selection: ChartSelection;
  request: (path: string) => Promise<{ total: number; items: Item[] }>;
  close: () => void;
  open: (item: Item) => void;
}) {
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<{ total: number; items: Item[] } | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  useEffect(() => {
    let active = true;
    setResult(null); setError("");
    const params = new URLSearchParams({ start: String(selection.start), end: String(selection.end), offset: String(offset) });
    if (selection.provider) params.set("provider", selection.provider);
    if (selection.region) params.set("region", selection.region);
    request(`/display/items?${params}`).then(r => { if (active) setResult(r); })
      .catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [selection, offset, request, retry]);
  return <section className="panel chart-records">
    <div className="detail-title"><h2 tabIndex={-1} ref={heading}>{selection.label}
      {result && <small> · {result.total} 条</small>}</h2><button onClick={close}>关闭筛选</button></div>
    {error ? <p role="alert">{error} <button onClick={() => setRetry(n => n + 1)}>重试</button></p>
      : !result ? <p>正在读取信息…</p> : <>
        <Information items={result.items} open={open} />
        <div className="chart-pager"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>上一页</button>
          <span>第 {offset / 50 + 1} 页</span><button disabled={offset + 50 >= result.total} onClick={() => setOffset(offset + 50)}>下一页</button></div>
      </>}
  </section>;
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
