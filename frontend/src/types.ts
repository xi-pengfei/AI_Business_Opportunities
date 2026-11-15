export type Fragment = { index: number; text: string; start: number; end: number; before: string; after: string };
export type Item = {
  id: string;
  related_item_id?: string;
  relation_kind?: string;
  source_urls?: string[];
  quality_status?: string;
  ai_review?: {decision?:string;reason?:string;evidence?:string;error?:string;model?:string;deduplication?:{relation:string;reason:string}};
  source_type?: string;
  source_name?: string;
  business_status?: string;
  requires_claim?: boolean;
  sent_at?: number;
  claimed_by?: string;
  claimed_at?: number;
  title: string;
  fragments?: Fragment[];
  category?: string;
  received_fields?: string[];
  url?: string;
  text?: string;
  contacts?: { type: string; value: string }[];
  created_at: number;
  is_demo: boolean;
  region?: string;
  region_evidence?: string;
  published_at?: string;
};
export type Execution = {
  id: number;
  task_id: string;
  kind: string;
  created_at: number;
  is_demo: boolean;
};
export type Snapshot = {
  information_sources: Record<string, number>;
  information_flows: {source:string;target:string;value:number}[];
  backlog_history: number[][];
  search_hit_history?: number[][];
  search_hit_total?: number;
  search_hit_success?: number;
  active_item_ids: string[];
  pending_count: number;
  backlog_count: number;
  pushed_count: number;
  assigned_count: number;
  assignment_status: string;
  customer_items: Item[];
  assigned_items: (Item & {recipient: string; delivery_status: string; sent_at: number; read_at?: number; claimed_by?:string; claimed_at?:number})[];
  backlog_points: {id:string; created_at:number; waiting_hours:number; fragments:number; category:string}[];
  delivery: { available: boolean; sent: number | null };
  regions: { name: string; count: number }[];
  region_unknown: number;
  task_scatter: { time: number; duration: number; status: string; attempts: number; kind: string }[];
  collectors: {
    id: string;
    name: string;
    query: string;
    state: string;
    next_run_at: number;
    provider: string;
    last_success_at: number | null;
    next_action_at: number;
    history: {start:number; results:number|null; successes:number; failures:number; warnings:number; running:number}[];
    continuous: boolean;
    search_page: number;
    search_engine: string;
    search_outcome: string;
    last_result_at: number | null;
    last_opportunity_at: number | null;
    waiting_recheck: boolean;
    done: number;
    total: number;
    duplicates: number;
    rounds: number;
    max_results: number;
    error_code: string | null;
  }[];
  mode: string;
  server_time: number;
  cursor: number;
  task_counts: Record<string, number>;
  item_count: number;
  trend: number[][];
  collection_history: number[][];
  discovery_history: { start: number; end: number; sources: Record<string, number> }[];
  discovery_calendar: { date: string; start: number; end: number; count: number }[];
  source_counts: Record<string, number>;
  category_counts: Record<string, number>;
  items: Item[];
  events: Execution[];
};
export type Rule = {
  search_spec?: {product?:string;synonyms?:string[];actions?:string[];regions?:string[];retired?:boolean};
  id: string;
  name: string;
  query: string;
  provider: string;
  enabled: boolean;
  interval_seconds: number;
  max_results: number;
  owner_user_id?: string | null;
};
export type Me = {
  id: string;
  username: string;
  display_name: string;
  role: "admin" | "member";
  is_active?: boolean;
  created_at?: number;
  identities?: string[];
};
export type DingTalkConfig = {
  enabled: boolean;
  client_id: string;
  scope: string;
  redirect_uri: string;
};
export type InviteInfo = {
  provider: string;
  display_name: string;
  used: boolean;
  expired: boolean;
};
export type Task = {
  id: string;
  kind: string;
  status: string;
  attempts: number;
  error_code: string | null;
  created_at: number;
  parent_id: string | null;
};
export const status: Record<string, string> = {
  queued: "排队中",
  running: "执行中",
  retry_wait: "等待重试",
  action_required: "待配置",
  succeeded: "已完成",
  failed: "失败",
};
export const errors: Record<string, string> = {
  xhs_login_required: "小红书登录已失效，请到管理台扫码登录",
  xhs_verification_required: "小红书要求验证，已暂停该来源，请先在账号端完成验证",
  xhs_connector_authorization: "小红书连接器凭证不匹配，请检查服务端配置",
  xhs_not_configured: "小红书连接器尚未配置",
  xhs_unavailable: "小红书连接器暂时无法访问，请稍后重试",
  xhs_request_failed: "小红书读取失败，等待下一次重试",
  xhs_invalid_response: "小红书返回内容与接口格式不符，未记为空结果",

  searxng_not_configured: "自建搜索服务尚未配置",
  searxng_rate_limited: "搜索入口要求验证或限流，冷却后重试，其他可用入口继续",
  searxng_engines_disabled: "搜索入口未启用，已停止向该入口请求",
  searxng_engines_unavailable: "上游搜索引擎暂时不可用，正在等待重试",
  searxng_request_failed: "自建搜索连接失败，正在重试",
  search_key_missing: "未配置 Tavily 密钥，请在服务端配置后重试",
  search_authorization_required: "搜索服务授权或额度异常",
  search_rate_limited: "搜索服务限流，等待重试",
  demo_disabled: "演示适配器未启用",
  worker_lease_expired: "执行租约过期，已进入恢复流程",
  search_request_failed: "搜索请求失败",
  empty_content: "来源未返回可用正文",
  invalid_source_url: "来源网址格式不受支持",
  worker_error: "任务执行异常",
};
export const clock = (t: number) =>
  new Date(t * 1000).toLocaleTimeString("zh-CN", { hour12: false });

export const sourceName = (i: Item) => i.source_name || ({public_tender:'商机',social_demand:'小红书',customer_watch:'监控'} as Record<string,string>)[i.source_type || 'public_tender'] || '商机';
export const businessState = (i: Item) => ({merged:'已合并',review_pending:'待AI审核',review_required:'待核实',collected:'已采集',waiting_claim:'待认领',claimed:'已认领',sent:'已推送',sending:'推送中',unknown:'推送结果待核实',failed:'推送失败',restored:'已恢复，回执待核实'} as Record<string,string>)[i.business_status || 'collected'] || '已采集';
export const fullTime = (t?:number) => t ? new Date(t*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}) : '—';
