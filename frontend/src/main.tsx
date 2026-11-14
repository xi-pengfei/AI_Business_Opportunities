import React, { useState, useEffect, useRef, useCallback } from "react";
import { createRoot } from "react-dom/client";
import { Charts } from "./Charts";
import { Spider } from "./Spider";
import { clock, status, errors } from "./types";
import type { Snapshot, Rule, Task, Item } from "./types";
import "./style.css";

const base = "/api/v1";
function App() {
  const [token, setToken] = useState("");
  const [draftToken, setDraftToken] = useState("");
  const [page, setPage] = useState(
    location.pathname === "/display" ? "display" : "rules",
  );
  const [demo, setDemo] = useState(false);
  const [data, setData] = useState<Snapshot | null>(null);
  const [rules, setRules] = useState<Rule[]>([]),
    [tasks, setTasks] = useState<Task[]>([]),
    [items, setItems] = useState<Item[]>([]);
  const [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [connected, setConnected] = useState(false);
  const [providers, setProviders] = useState<{
    tavily: { configured: boolean };
    demo: { enabled: boolean };
  } | null>(null);
  const [detail, setDetail] = useState<
    (Item & { evidence: { raw_content: string; content_kind: string } }) | null
  >(null);
  const [moving, setMoving] = useState<Item | null>(null);
  const seen = useRef(new Set<string>()),
    hydrated = useRef(false);
  const [streamState, setStreamState] = useState("连接中");
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
    if (!token) return;
    const viewKey = `${token}:${demo}:${page}`;
    try {
      const snapshot: Snapshot = await request(
        `/display/snapshot?demo=${demo}`,
      );
      if (activeView.current !== viewKey) return;
      setData(snapshot);
      setConnected(true);
      if (hydrated.current) {
        const fresh = snapshot.items.find((i) => !seen.current.has(i.id));
        if (fresh) setMoving(fresh);
      }
      snapshot.items.forEach((i) => seen.current.add(i.id));
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
      setError((e as Error).message);
    }
  }, [token, demo, page, request]);
  useEffect(() => {
    hydrated.current = false;
    seen.current.clear();
    setMoving(null);
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
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <small>令牌仅保留在当前页面内存，刷新后需要重新登录。</small>
      </main>
    );
  const display = page === "display";
  const source = moving || data?.items[0];
  return (
    <main className={display ? "screen" : "workspace"}>
      <header className="mast">
        <h1>AI商机智能体</h1>
        <span className="mode">{demo ? "演示数据" : "真实数据"}</span>
        <div className="toolbar">
          <label>
            数据范围
            <select
              value={String(demo)}
              onChange={(e) => {
                setDemo(e.target.value === "true");
                setError("");
              }}
            >
              <option value="false">真实数据</option>
              <option value="true">演示数据</option>
            </select>
          </label>
          <button onClick={() => navigate(display ? "rules" : "display")}>
            {display ? "管理台" : "展示大屏"}
          </button>
          {display && (
            <button
              onClick={() =>
                document.documentElement
                  .requestFullscreen()
                  .catch(() => setError("当前浏览器无法进入全屏"))
              }
            >
              全屏
            </button>
          )}
          <button
            onClick={() => {
              setToken("");
              setData(null);
            }}
          >
            退出
          </button>
        </div>
      </header>
      {!display && (
        <nav aria-label="管理导航">
          {[
            ["rules", "采集规则"],
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
      <div className="notice" role="status">
        {connected ? "服务已连接" : "连接中断或等待服务"} · {streamState}
        {data && ` · 最后更新 ${clock(data.server_time)}`}
      </div>
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
          <Charts data={data} />
          <div className="workfield">
            <section className="panel terminal">
              <h2>来源终端</h2>
              {source && (
                <div className="source-preview">
                  {source.url && (
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {source.url}
                    </a>
                  )}
                  <h3>{source.title}</h3>
                  <p>{source.text?.slice(0, 180)}</p>
                </div>
              )}
              <p>
                {data.task_counts.running
                  ? "正在执行采集任务"
                  : data.task_counts.queued
                    ? "任务排队中"
                    : data.task_counts.action_required
                      ? "有任务等待配置，其他来源可继续运行"
                      : "等待下一轮任务"}
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
            <section className="panel">
              <h2>
                信息库 <small>{data.item_count} 条</small>
              </h2>
              <Information
                items={data.items}
                open={(item) => {
                  if (item.url)
                    request(`/items/${item.id}`)
                      .then(setDetail)
                      .catch((e) => setError(e.message));
                }}
              />
            </section>
            <Spider item={moving} />
          </div>
          <section className="panel handoff">
            <h2>分配与接收</h2>
            <div className="empty">
              分配和通知尚未接入。已归集的信息可先在信息库查看与人工跟进。
            </div>
          </section>
        </>
      )}
      {!data && <div className="empty">正在读取运行状态…</div>}
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
                      interval_seconds: Number(fd.get("interval")) * 60,
                      max_results: Number(fd.get("max")),
                      enabled: false,
                    }),
                  });
                  form.reset();
                }, "规则已保存为草稿，可以先执行一次验证结果。");
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
                搜索关键词
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
                  <option value="tavily">
                    Tavily 全网搜索
                    {providers && !providers.tavily.configured
                      ? "（待配置密钥）"
                      : ""}
                  </option>
                  {providers?.demo.enabled && (
                    <option value="demo">演示适配器（不会搜索网络）</option>
                  )}
                </select>
              </label>
              <div className="fields">
                <label>
                  执行间隔（分钟）
                  <input
                    name="interval"
                    type="number"
                    min={5}
                    max={43200}
                    defaultValue={60}
                    required
                  />
                </label>
                <label>
                  每次最多结果
                  <input
                    name="max"
                    type="number"
                    min={1}
                    max={10}
                    defaultValue={5}
                    required
                  />
                </label>
              </div>
              <button disabled={busy}>保存草稿</button>
              <p className="hint">保存不触发采集；启用后按间隔持续运行。</p>
            </form>
          </section>
          <section className="panel">
            <h2>采集规则</h2>
            {!rules.length ? (
              <p className="empty">还没有规则。从左侧添加第一组关键词。</p>
            ) : (
              rules.map((r) => (
                <article className="rule" key={r.id}>
                  <div>
                    <h3>{r.name}</h3>
                    <p>{r.query}</p>
                    <small>
                      {r.provider === "demo" ? "演示" : "Tavily"} · 每{" "}
                      {r.interval_seconds / 60} 分钟 ·{" "}
                      {r.enabled ? "已启用" : "草稿 / 已停用"}
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
                          "任务已进入队列；请在对应数据范围查看任务。",
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
                              body: JSON.stringify({ enabled: !r.enabled }),
                            }),
                          r.enabled
                            ? "已停止后续调度，已入队任务继续执行。"
                            : "规则已启用。",
                        )
                      }
                    >
                      {r.enabled ? "停用" : "启用"}
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
          {!tasks.length && <p className="empty">当前数据范围尚无任务。</p>}
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
          <pre>{detail.evidence.raw_content}</pre>
        </section>
      )}
    </main>
  );
}
function Information({
  items,
  open,
}: {
  items: Item[];
  open: (item: Item) => void;
}) {
  return (
    <>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>信息原文</th>
              <th>原始网址</th>
              <th>联系方式</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>
                  {item.url ? (
                    <button className="text-button" onClick={() => open(item)}>
                      {item.title}
                    </button>
                  ) : (
                    <span>{item.title}</span>
                  )}
                  <p className="excerpt">{item.text?.slice(0, 160)}</p>
                  <small>{clock(item.created_at)}</small>
                </td>
                <td>
                  {item.url ? (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {new URL(item.url).hostname}
                    </a>
                  ) : (
                    "已脱敏"
                  )}
                </td>
                <td>{item.contacts?.map((c) => c.value).join(" / ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!items.length && (
        <p className="empty">尚无归集信息。采集完成后会自动出现。</p>
      )}
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
