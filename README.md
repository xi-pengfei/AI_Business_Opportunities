# AI_Business_Opportunities

持续发现需求信息、汇集客户内外部资料的平台。允许需求模糊，不强制采购金额或商机分级；人员核实，AI 辅助整理及后续客户分析。

当前版本 **0.1：任务骨架与最小采集闭环**。已实现规则管理、持久化任务/Outbox、有限重试与租约恢复、演示、SearXNG 与 Tavily 适配器、正文清洗/精确去重、证据查询、真实统计大屏、地区图、摘要/时效归档和 SSE。CRM、平台账号、AI 分析、分配及 IM 回执尚未实现。默认搜索改为自建 SearXNG，无需搜索 API 密钥；已完成本机真实搜索与连续入库验收，长期稳定性仍待观察。

## 启动

需要 Docker Compose。服务仅绑定本机回环地址，不会对局域网或公网开放。

```sh
./scripts/setup.sh
# 默认启动自建 SearXNG；仅主动选择 Tavily 时才需要 TAVILY_API_KEY
# 仅验证演示链路时设置 ALLOW_DEMO=true
# 不要提交 .env，也不要把访问令牌放进网址。
docker compose up -d --build
```

打开 http://localhost:5180 ，使用 `.env` 中的 `ADMIN_TOKEN`。独立展示入口 http://localhost:5180/display 可使用 `DISPLAY_TOKEN`，仅返回脱敏数据。令牌仅保存在页面内存；浏览器刷新后重新登录。

1. 新建关键词规则，默认选择 SearXNG 自建搜索。
2. 新建规则保存后自动开始连续采集，在任务页查看进度。
3. 信息库查看原文、原始网址、正文/搜索摘要标识及提取到的联系方式。
4. 关键词每行一组自动轮转并扩展地区；当前批次完成后接下一批。点击停止后不再启动下一批。
5. 缺少搜索密钥进入“待配置”；在 `.env` 配置后重建 API/Worker/调度器，再手动重试。

SearXNG 每次保留上游返回的全部结果，关键词/地区轮转后继续请求下一页；实际分页和覆盖范围取决于上游引擎，不保证无限结果。自建服务没有按次 API 账单，但占用机器和网络资源，上游仍可能限流。可选 Tavily 使用 basic、单次最多 20 条，会消耗供应商额度；当前尚无总预算模块。不会自动从 SearXNG 回退到付费服务。密钥仅由服务端读取，不进入队列或浏览器。

## 本地开发（无需构建应用镜像）

```sh
./scripts/setup.sh
docker compose up -d db redis
cd backend && uv sync --python 3.12 && cd ..
python3 scripts/local_backend.py alembic upgrade head
# 以下命令分别运行于终端
python3 scripts/local_backend.py uvicorn scout.api:app --host 127.0.0.1 --port 58100
python3 scripts/local_backend.py celery -A scout.worker:app worker -Q collection --pool=solo --loglevel=WARNING
python3 scripts/local_backend.py python -m scout.dispatcher
cd frontend && npm ci && npm run dev
```

macOS 开发 Worker 用 solo；容器 Worker 用两个独立进程和硬超时。调度器可以启动多个实例，PostgreSQL 行锁防重复调度；数据库不可用时保留失败状态并等待恢复，不声称单机高可用。

## 验证

```sh
cd backend && uv run pytest -q && uv run ruff check .
cd ../frontend && npm run build
# 运行中的本地服务；要求 ALLOW_DEMO=true，创建明确标记的演示规则
cd .. && python3 scripts/smoke.py
```

测试覆盖重复消息、相同内容去重、过期租约与旧 Worker 写入隔离、限次重试、队列不可用后重新投递、规则停用、权限和演示隔离。SQLite 仅用于快速测试；实际运行使用 PostgreSQL。

## 当前边界

- SearXNG 当前仅接入搜索摘要；Crawl4AI 正文采集尚未实现。Tavily 返回正文时保留正文；缺失时明确标记搜索摘要，绝不把摘要当完整正文。
- 当前只调用固定或管理员配置的搜索服务，不直接抓取结果网址。直接 HTTP/浏览器采集需后续加入 DNS/IP/重定向/出站隔离，不能复用当前“证据网址格式校验”作为抓取授权。
- 原文先保存在数据库中（每个结果最多 200,000 字符），后续再加入附件/对象存储。当前不支持 PDF/OCR 与动态网页登录。新信息使用规则抽取摘要，原始文档保留；明确过期招采、往年通知和空摘要归档，不进入主列表。
- 同一规范化 URL 与数据模式只展示一条信息；历史版本保留但合并计数。尚无跨网址语义合并与已知网址的独立更新机制。
- 联系方式只从原文提取邮箱与中国大陆手机号码候选，尚需人工核实；不会补全或猜测。
- 大屏图表来自持久化事件；蜘蛛只在发现新入库信息时搬运，动画不控制写库。首次打开展示快照，不回放历史采集。
- 大屏为管理员模式时展示原文；对外使用独立展示令牌，后端隐藏原文、网址和联系方式。尚无人员角色管理、审计管理、任务保留清理和完整部署监控。
- 分配与接收区域明确显示“尚未接入”，不展示虚构回执。

## 文档与仓库

[开发计划](docs/ROADMAP.md) · [架构](docs/ARCHITECTURE.md) · [交互规格](docs/UX-SPEC.md) · [设计方向](design-system/ai-opportunity/MASTER.md)

公开仓库：https://github.com/xi-pengfei/AI_Business_Opportunities 。已获用户授权进行本地提交和公开推送，功能分支 `codex/<topic>`。密钥、账号会话、客户资料、数据库、采集内容和运行日志不得入库。
