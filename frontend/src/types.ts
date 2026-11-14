export type Item = {
  id: string;
  title: string;
  url?: string;
  text?: string;
  contacts?: { type: string; value: string }[];
  created_at: number;
  is_demo: boolean;
};
export type Execution = {
  id: number;
  task_id: string;
  kind: string;
  created_at: number;
  is_demo: boolean;
};
export type Snapshot = {
  mode: string;
  server_time: number;
  cursor: number;
  task_counts: Record<string, number>;
  item_count: number;
  trend: number[][];
  collection_history: number[][];
  source_counts: Record<string, number>;
  items: Item[];
  events: Execution[];
};
export type Rule = {
  id: string;
  name: string;
  query: string;
  provider: string;
  enabled: boolean;
  interval_seconds: number;
  max_results: number;
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
