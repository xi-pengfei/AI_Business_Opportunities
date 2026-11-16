import React, { useState, useEffect, useRef, useCallback } from "react";
import { createRoot } from "react-dom/client";
import { CollectorMonitor } from "./CollectorMonitor";
import "./collector-monitor.css";
import { Charts } from "./Charts";
import type { ChartSelection } from "./Charts";
import { expandCargo, landFragment, cargoKey } from "./fragments";
import type { Cargo } from "./fragments";
import {SourceFeed} from "./SourceFeed";
import {Information} from "./FlowPanels";
import { Xiaohongshu } from "./Xiaohongshu";
import { BusinessFollowup } from "./FollowupPanels";
import { NetworkRules } from "./NetworkRules";
import { Customers } from "./Customers";
import { TokenPanel, KeyIcon } from "./TokenPanel";
import { Users } from "./Users";
import { Spider } from "./Spider";
import { clock, fullTime, status, errors } from "./types";
import type { Snapshot, Rule, Task, Item, Me, DingTalkConfig, InviteInfo } from "./types";
import "./style.css";
import "./display-layout.css";
import "./black-theme.css";
import "./design-tokens.css";
import "./console.css";

const base = "/api/v1";

/** 把后端返回的 detail 转成可读文案（422 校验错误是数组，直接显示会变成「请求失败」）。 */
function readableDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d: any) => {
        const msg = typeof d?.msg === "string" ? d.msg.replace(/^Value error,\s*/i, "") : "";
        if (msg) return msg;
        if (d?.loc) return `${String(d.loc.at(-1))}: 参数无效`;
        return "";
      })
      .filter(Boolean);
    return parts.join("；");
  }
  return "";
}
type Session = { access_token: string; user: Me };

/** 跳转钉钉扫码授权页；state 防 CSRF，邀请码随会话带到回调页。 */
function startDingTalk(cfg: DingTalkConfig) {
  const state = Math.random().toString(36).slice(2) + Date.now().toString(36);
  sessionStorage.setItem("scout-dd-state", state);
  const query = new URLSearchParams({
    redirect_uri: cfg.redirect_uri,
    response_type: "code",
    client_id: cfg.client_id,
    scope: cfg.scope,
    state,
    prompt: "consent",
  });
  location.href = `https://login.dingtalk.com/oauth2/auth?${query}`;
}

/** 钉钉扫码回调页：校验 state、凭 authCode 换会话（可携带邀请码完成绑定）。 */
function DingTalkCallback({ onLogin }: { onLogin: (token: string, user: Me) => void }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const code = params.get("authCode") || params.get("code");
    const state = params.get("state");
    const expected = sessionStorage.getItem("scout-dd-state");
    sessionStorage.removeItem("scout-dd-state");
    const invite = sessionStorage.getItem("scout-invite");
    if (!code) {
      setBusy(false);
      setError("没有拿到钉钉授权码，可能你取消了授权。请返回登录页重试。");
      return;
    }
    if (expected && state && expected !== state) {
      setBusy(false);
      setError("登录状态校验失败，请返回登录页重新扫码。");
      return;
    }
    fetch(base + "/auth/dingtalk/callback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ authCode: code, invite: invite || null }),
      signal: AbortSignal.timeout(20000),
    })
      .then(async (r) => {
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(readableDetail(data.detail) || "钉钉登录失败，请稍后重试");
        return data;
      })
      .then((d) => {
        sessionStorage.removeItem("scout-invite");
        onLogin(d.access_token, d.user);
      })
      .catch((e) => {
        setBusy(false);
        setError((e as Error).message);
      });
  }, []);
  return (
    <main className="login panel">
      <h1>钉钉登录</h1>
      {busy && <p>正在完成钉钉扫码登录…</p>}
      {error ? (
        <>
          <p className="error" role="alert">{error}</p>
          <button onClick={() => { location.href = "/"; }}>返回登录页</button>
        </>
      ) : null}
    </main>
  );
}

/** 邀请绑定落地页：/invite?k=<令牌>，管理员把链接发给员工，员工点按钮扫码绑定。 */
function InviteBind({ cfg }: { cfg: DingTalkConfig | null }) {
  const k = new URLSearchParams(location.search).get("k") || "";
  const [info, setInfo] = useState<InviteInfo | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!k) { setError("链接缺少邀请码，请使用管理员发送的完整链接打开。"); return; }
    fetch(base + `/auth/invite-info?token=${encodeURIComponent(k)}`, { signal: AbortSignal.timeout(15000) })
      .then(async (r) => {
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(readableDetail(data.detail) || "邀请链接无效");
        return data as InviteInfo;
      })
      .then(setInfo)
      .catch((e) => setError((e as Error).message));
  }, [k]);
  const invalid = !!info && (info.used || info.expired);
  return (
    <main className="login panel">
      <h1>绑定钉钉账号</h1>
      {error && <p className="error" role="alert">{error}</p>}
      {info && !invalid && (
        <>
          <p>
            你好，<strong>{info.display_name}</strong>！绑定钉钉后即可扫码登录管理台，
            商机信息也会推送到你的钉钉。
          </p>
          <button
            disabled={!cfg?.enabled}
            onClick={() => {
              sessionStorage.setItem("scout-invite", k);
              if (cfg) startDingTalk(cfg);
            }}
          >
            {cfg?.enabled ? "使用钉钉扫码完成绑定" : "钉钉登录尚未配置，请联系管理员"}
          </button>
          <small>链接 7 天内有效，只能使用一次。</small>
        </>
      )}
      {invalid && (
        <>
          <p className="error" role="alert">
            {info!.used ? "该邀请链接已被使用。" : "该邀请链接已过期。"}
          </p>
          <button onClick={() => { location.href = "/"; }}>回到登录页</button>
        </>
      )}
      {!info && !error && <p>正在读取邀请信息…</p>}
    </main>
  );
}
const savedSession: Session | null = (() => {
  try {
    const raw = sessionStorage.getItem("scout-session");
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
})();
function App() {
  const [token, setToken] = useState(savedSession?.access_token ?? "");
  const [me, setMe] = useState<Me | null>(savedSession?.user ?? null);
  const [draftUser, setDraftUser] = useState("");
  const [draftPass, setDraftPass] = useState("");
  useEffect(() => {
    if (token && me) sessionStorage.setItem("scout-session", JSON.stringify({ access_token: token, user: me }));
    else sessionStorage.removeItem("scout-session");
  }, [token, me]);
  // 大屏免登录链接：/display?k=<令牌>，校验通过直接亮屏
  useEffect(() => {
    const k = new URLSearchParams(location.search).get("k");
    if (!k) return;
    fetch(base + "/display/snapshot", {
      headers: { Authorization: `Bearer ${k}` },
      signal: AbortSignal.timeout(15000),
    })
      .then((r) => {
        if (!r.ok) throw new Error("invalid");
        setToken(k);
        setMe(null);
        setPage("display");
        history.replaceState({}, "", "/display");
      })
      .catch(() => {});
  }, []);
  const [page, setPage] = useState(
    ["display", "rules", "customers", "xiaohongshu", "tasks", "information", "users"].includes(location.pathname.slice(1)) ? location.pathname.slice(1) : "rules",
  );
  const demo = false;
  const [fullscreen,setFullscreen]=useState(!!document.fullscreenElement);
  useEffect(()=>{const changed=()=>setFullscreen(!!document.fullscreenElement);document.addEventListener('fullscreenchange',changed);return()=>document.removeEventListener('fullscreenchange',changed);},[]);
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
  const [informationStatus, setInformationStatus] = useState("active");
  const [tokenOpen, setTokenOpen] = useState(false);
  const [ddCfg, setDdCfg] = useState<DingTalkConfig | null>(null);
  useEffect(() => {
    // 公开配置：登录页据此显示钉钉扫码入口
    fetch(base + "/auth/dingtalk/config", { signal: AbortSignal.timeout(10000) })
      .then((r) => r.json())
      .then(setDdCfg)
      .catch(() => setDdCfg({ enabled: false, client_id: "", scope: "", redirect_uri: "" }));
  }, []);
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
        if (response.status === 401 && me) {
          // 会话过期：清空并回到登录页
          setToken("");
          setMe(null);
        }
        const result = await response.json().catch(() => ({}));
        throw new Error(
          readableDetail(result.detail) || `请求失败 (${response.status})`,
        );
      }
      return response.json();
    },
    [token, me],
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
      assignedIds.current = new Set([...snapshot.assigned_items, ...(snapshot.customer_items || [])].map(i=>i.id));
      const validIds = new Set(snapshot.active_item_ids);
      setLibrary(old=>old.filter(i=>validIds.has(i.id) && !assignedIds.current.has(i.id)));
      setTerminalFeed(old=>old.filter(i=>validIds.has(i.id)));
      cargoQueue.current = cargoQueue.current.filter(i=>validIds.has(i.id));
      if (currentCargo.current && !validIds.has(currentCargo.current.id)) {
        assignedIds.current.add(currentCargo.current.id);
        nextCargo();
      }
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
        const [r, t, i] = await Promise.all([
          request("/rules"),
          request(`/tasks?demo=${demo}`),
          request(`/items?demo=${demo}&status=${informationStatus}`),
        ]);
        if (activeView.current !== viewKey) return;
        setRules(r);
        setTasks(t);
        setItems(i);
      }
    } catch (e) {
      if (activeView.current !== viewKey) return;
      setConnected(false);
      setConnectionError("连接暂时中断，正在自动重连");
    } finally {
      refreshing.current = false;
    }
  }, [token, demo, page, request, nextCargo, informationStatus]);
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
  function logout() {
    setToken("");
    setMe(null);
    setData(null);
    setPage("rules");
    history.replaceState({}, "", "/");
  }
  async function login(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await fetch(base + "/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: draftUser.trim(), password: draftPass }),
        signal: AbortSignal.timeout(15000),
      });
      const result = await r.json().catch(() => ({}));
      if (!r.ok)
        throw Error(
          readableDetail(result.detail) || "登录失败，请稍后重试",
        );
      setToken(result.access_token);
      setMe(result.user);
      setDraftPass("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (location.pathname === "/dingtalk")
    return (
      <DingTalkCallback
        onLogin={(t, u) => {
          setToken(t);
          setMe(u);
          history.replaceState({}, "", "/");
        }}
      />
    );
  if (location.pathname === "/invite") return <InviteBind cfg={ddCfg} />;
  if (!token)
    return (
      <main className="login panel">
        <h1>AI商机智能体</h1>
        <p>使用账号登录管理台；展示大屏请打开管理员生成的大屏链接（无需登录）。</p>
        <form onSubmit={login}>
          <label>
            用户名
            <input
              type="text"
              required
              autoComplete="username"
              autoFocus
              value={draftUser}
              onChange={(e) => setDraftUser(e.target.value)}
            />
          </label>
          <label>
            密码
            <input
              aria-invalid="false"
              type="password"
              required
              autoComplete="current-password"
              value={draftPass}
              onChange={(e) => setDraftPass(e.target.value)}
            />
          </label>
          <button disabled={busy}>{busy ? "登录中…" : "进入系统"}</button>
        </form>
        {ddCfg?.enabled && (
          <>
            <div className="sso-divider" aria-hidden="true"><span>或</span></div>
            <button type="button" className="sso-dingtalk" onClick={() => startDingTalk(ddCfg)}>
              使用钉钉扫码登录
            </button>
          </>
        )}
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
        <small>没有账号？请联系系统管理员开通；首次登录后建议立即修改密码。</small>
      </main>
    );
  const display = page === "display";

  const navRules = rules.filter(r=>r.provider!=="demo"&&r.provider!=="xiaohongshu"&&!r.search_spec?.retired).length;
  const liveTasks = tasks.filter(t=>["running","queued","retry_wait"].includes(t.status)).length;
  const crumb = ({
    rules:["网络商机","商机主题列表"],
    customers:["客户动向","动向明细"],
    xiaohongshu:["小红书","账号与关键词"],
    tasks:["任务运行","实时任务"],
    information:["信息库","已入库档案"],
    users:["系统设置","用户管理"],
  } as Record<string,[string,string]>)[page]||["管理台",""];
  const navIcon=(paths:string[])=>(
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {paths.map((d,i)=><path key={i} d={d}/>)}
    </svg>
  );
  const NAV:Array<[string,string,string[]]>= [
    ["rules","网络商机",["M3 17l5-5 4 3 5-7 4 4","M3 21h18"]],
    ["customers","客户动向",["M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2","M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z","M22 21v-2a4 4 0 0 0-3-3.87"]],
    ["xiaohongshu","小红书",["M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v9a1.5 1.5 0 0 1-1.5 1.5H9l-5 4z","M8 9h8","M8 12h5"]],
    ["tasks","任务运行",["M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18","M12 7v5l3.5 2"]],
    ["information","信息库",["M4 19.5A2.5 2.5 0 0 1 6.5 17H20","M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"]],
    ["users","用户管理",["M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2","M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z","M23 21v-2a4 4 0 0 0-3-3.87","M16 3.13a4 4 0 0 1 0 7.75"]],
  ];
  return (
    <main className={display ? `screen${fullscreen ? " is-fullscreen" : ""}` : "workspace"}>
      {display ? (
        <>
          <header className="mast">
            <h1>AI商机智能体</h1>
            <div className="toolbar">
              <button className="management-action" hidden={fullscreen} onClick={() => navigate("rules")}>
                管理台
              </button>
              <button hidden={fullscreen}
                onClick={logout}
              >
                退出
              </button>
              <button
                onClick={() => {
                  setError("");
                  (document.fullscreenElement
                    ? document.exitFullscreen()
                    : document.documentElement.requestFullscreen()
                  ).catch(() => setError("当前浏览器无法切换全屏"));
                }}
              >
                {fullscreen ? "退出全屏" : "全屏"}
              </button>
            </div>
          </header>
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
              {chartSelection && <ChartRecords key={`${chartSelection.start}:${chartSelection.end}:${chartSelection.provider || ""}:${chartSelection.region || ""}`}
                selection={chartSelection} request={request} close={() => setChartSelection(null)}
                open={(item) => request(`/items/${item.id}`).then(setDetail).catch(e => setError(e.message))} />}

              <div className="workfield">
                <section className="panel terminal">
                  <h2>信息来源</h2>
                  <SourceFeed items={terminalFeed} moving={moving} landed={landed} />
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
                    信息库 <small>{data.pending_count} 条</small>
                  </h2>
                  <Information
                    items={library}
                    lifecycle={false}
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
              <BusinessFollowup data={data} open={item=>request(`/items/${item.id}`).then(setDetail).catch(e=>setError(e.message))} />
              <div className="charts"><Charts data={data} onSelect={setChartSelection} dark /></div>
              <CollectorMonitor collectors={data.collectors} stale={!!connectionError} />
            </>
          )}
          {!data && <div className="empty">正在读取运行状态…</div>}
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
              {detail.ai_review?.reason && <p>AI 审核：{detail.ai_review.reason} · {detail.ai_review.model}</p>}
              {detail.ai_review?.deduplication && <p>相似信息比对：{detail.ai_review.deduplication.reason}</p>}
              {detail.related_item_id && <p>{detail.relation_kind==='update'?'这是关联商机的新进展':'已关联到同一商机'} <button className="text-button" onClick={()=>request(`/items/${detail.related_item_id}`).then(setDetail).catch(e=>setError(e.message))}>查看关联商机</button></p>}
              {!!detail.source_urls?.length && <div><p>原始来源网址</p>{detail.source_urls.map(url=><p key={url}><a href={url} target="_blank" rel="noopener noreferrer">{url}</a></p>)}</div>}
              {detail.ai_review?.evidence && <p>判断依据：{detail.ai_review.evidence}</p>}
              {detail.ai_review?.error && <p>审核暂未完成：{detail.ai_review.error}</p>}
              {detail.quality_status==='review_required' && <button disabled={busy} onClick={()=>action(()=>request(`/items/${detail.id}/review`,{method:'POST'}),'已重新加入审核队列')}>重新审核</button>}
              <pre>{detail.evidence.raw_content}</pre>
            </section>
          )}
          <div className="notice" role="status">
            {connected ? "服务已连接" : "连接中断或等待服务"} · {streamState}
            {data && ` · 最后更新 ${fullTime(data.server_time)}`}
          </div>
        </>
      ) : (
        <>
          <aside className="console-side">
            <div className="console-brand">
              <span className="console-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 3v3M12 18v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M3 12h3M18 12h3M4.9 19.1L7 17M17 7l2.1-2.1" />
                  <circle cx="12" cy="12" r="3.2" />
                </svg>
              </span>
              <div>
                <b>AI 商机智能体</b>
                <small>Opportunity Agent</small>
              </div>
            </div>
            <nav className="console-nav" aria-label="管理导航">
              {NAV.filter(([key]) => key !== "users" || me?.role === "admin").map(([key, label, paths]) => (
                <button
                  key={key}
                  className="console-nav-item"
                  aria-current={page === key ? "page" : undefined}
                  onClick={() => navigate(key)}
                >
                  {navIcon(paths)}
                  <span>{label}</span>
                  {key === "rules" && navRules > 0 && <em className="console-badge">{navRules}</em>}
                  {key === "tasks" && liveTasks > 0 && <em className="console-badge live">{liveTasks}</em>}
                </button>
              ))}
            </nav>
            <button type="button" className="console-side-foot" onClick={() => setTokenOpen(true)} aria-haspopup="dialog">
              <span className="console-avatar" aria-hidden="true"><KeyIcon/></span>
              <div>
                <b>{me?.display_name || "账号中心"}</b>
                <small>{me?.role === "admin" ? "系统管理员 · 账号中心" : "成员 · 账号中心"}</small>
              </div>
            </button>
          </aside>
          <div className="console-main">
            <header className="mast console-top">
              <div className="console-crumb">
                <span>{crumb[0]}</span>
                <span className="console-crumb-sep" aria-hidden="true">/</span>
                <b>{crumb[1]}</b>
              </div>
              <div className="toolbar">
                <button onClick={() => navigate("display")}>展示大屏</button>
                <span className="top-user" title={`已登录：${me?.username ?? ""}`}>{me?.display_name}</span>
                <button onClick={logout}>退出</button>
              </div>
            </header>
            <div className="console-body">
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
              {!data && <div className="empty">正在读取运行状态…</div>}
              {page === "xiaohongshu" && <Xiaohongshu request={request} />}
              {page === "customers" && <Customers request={request} manage />}
              {page === "rules" && <NetworkRules rules={rules} request={request} onSaved={refresh} liveTasks={liveTasks} me={me} />}
              {page === "users" && me?.role === "admin" && <Users request={request} me={me} />}
              {page === "tasks" && (
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
                            <td><span className={"st st-" + t.status}>{status[t.status]}</span></td>
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
              {page === "information" && (
                <section className="panel library">
                  <h2>
                    信息库 <small>最近 50 条 · 原文待人工核实</small>
                  </h2>
                  <label>信息状态 <select value={informationStatus} onChange={e=>{setItems([]);setInformationStatus(e.target.value);}}>
                    <option value="active">有效信息</option><option value="review_pending">待 AI 审核</option>
                    <option value="review_required">待核实 / 审核异常</option><option value="archived">已过滤 / 已归档</option><option value="merged">重复信息（已合并）</option>
                  </select></label>
                  <p className="scroll-hint">表格可横向滚动，右侧可查看推送与认领记录</p>
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
                  {detail.ai_review?.reason && <p>AI 审核：{detail.ai_review.reason} · {detail.ai_review.model}</p>}
                  {detail.ai_review?.deduplication && <p>相似信息比对：{detail.ai_review.deduplication.reason}</p>}
                  {detail.related_item_id && <p>{detail.relation_kind==='update'?'这是关联商机的新进展':'已关联到同一商机'} <button className="text-button" onClick={()=>request(`/items/${detail.related_item_id}`).then(setDetail).catch(e=>setError(e.message))}>查看关联商机</button></p>}
                  {!!detail.source_urls?.length && <div><p>原始来源网址</p>{detail.source_urls.map(url=><p key={url}><a href={url} target="_blank" rel="noopener noreferrer">{url}</a></p>)}</div>}
                  {detail.ai_review?.evidence && <p>判断依据：{detail.ai_review.evidence}</p>}
                  {detail.ai_review?.error && <p>审核暂未完成：{detail.ai_review.error}</p>}
                  {detail.quality_status==='review_required' && <button disabled={busy} onClick={()=>action(()=>request(`/items/${detail.id}/review`,{method:'POST'}),'已重新加入审核队列')}>重新审核</button>}
                  <pre>{detail.evidence.raw_content}</pre>
                </section>
              )}
            </div>
            <div className="notice console-notice" role="status">
              {connected ? "服务已连接" : "连接中断或等待服务"} · {streamState}
              {data && ` · 最后更新 ${fullTime(data.server_time)}`}
            </div>
          </div>
          <TokenPanel
            open={tokenOpen}
            request={request}
            user={me}
            onClose={() => setTokenOpen(false)}
          />
        </>
      )}
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
