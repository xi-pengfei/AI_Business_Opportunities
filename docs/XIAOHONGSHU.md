# 小红书需求采集

## 用户操作

1. 在管理台打开「小红书采集」。页面列出全部账号：账号名、关键词、状态、建立人、累计爬取批次（点数字看明细）。
2. 点「新增账号」填写账号名称、连接器地址、访问令牌与关键词（每行一组）。一个账号 = 一路独立连接器（自己的登录态）+ 自己的关键词。
3. 对该行点「扫码登录」，用小红书App扫描二维码并在手机上确认。不要把密码或Cookie粘贴到系统里。登录成功后，该账号等待中的任务自动重新排队。
4. 关键词随时可改，保存即按新关键词继续采集；「停止」只停该账号后续批次。多账号并发采集，互相不影响。
5. 权限：账号与关键词全员可见（只读）；只有建立者本人和系统管理员可以修改、扫码、启停。爬取记录以数字链接打开，看得到每批的开始时间、状态、发现条数与失败原因。
6. 有效需求依次出现在大屏来源终端、蜘蛛搬运和信息库。客户动态在大屏独立区域显示。小红书商机与网络商机共用钉钉推送、显式回复认领流程。

连续运行是后台轮换关键词、处理本批并周期复查，不是持续高频刷新同一个页面。小红书每批间隔至少60秒；遇到连接失败冷却10分钟，登录失效/验证只暂停该账号，其他账号与其他来源继续。没有金额或正式公司名称也可以保留，但必须能在原文看到需求表达。保留近30天，未知日期归档，帖子ID与内容去重。图片里的文字、视频语音、评论需求尚未识别。

## 接入与部署

使用开源 [xpzouying/xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp) 的 HTTP 接口。它是第三方连接器，不是小红书官方数据API。程序只允许调用登录检查、扫码、搜索、笔记详情四类接口；不调用发布、评论、点赞、私信和关注。

```sh
# .env 设置随机 XIAOHONGSHU_TOKEN；不是小红书密码。
docker compose --profile xiaohongshu up -d xiaohongshu social-worker
```

连接器只在Compose内部网络提供服务，无对外端口。`XIAOHONGSHU_TOKEN`用于内部接口认证；Cookie在独立Docker卷 `xhs_session`，不会进入Git、任务队列、API返回或前端。多账号时，连接器地址与令牌存在 `xhs_accounts` 表（管理台维护，令牌只回显掩码），迁移 w023 会把 `.env` 里的 `XIAOHONGSHU_URL/TOKEN` 收编为「默认账号」并链上原有规则。`note_token`是搜索结果里的单篇公开笔记访问参数，不是账号Cookie，详情读取完成即从任务载荷移除；信息库只返回不含访问参数的原始帖子网址。

接口版本按部署镜像锁定。源项目提示同一账号在其他网页端重新登录可能使现有会话失效。持续采集依赖平台可访问性，不能保证免限流或不触发验证，也不绕过验证码、访问限制或登录权限。

## 数据和展示

`Rule.source_type=social_demand`，`provider=xiaohongshu`，`monitor_rules.xhs_account_id` 指向 `xhs_accounts`；独立`social`队列，social-worker 并发 3 支撑多账号并行。采集配置、登录/风控阻断与错误退避都按 `xhs_account_id` 隔离：某账号登录失效只冷却它自己的规则，无账号的遗留任务回落到全局 `.env` 配置。搜索得到帖子ID后，每帖独立读取正文、原始发布日期，成功后复用清洗、Item、事件和大屏feed。不会把搜索卡片的标题当作完整正文。

`Item.source_type=social_demand`、`information_kind=demand`、`category=小红书需求`。公开招采的历史拒绝指纹不适用于小红书；全网资讯清理也不会删除小红书需求。钉钉接收opportunity和demand类型，首个明确回复的成员成为认领人；认领后继续推送下一条。

搜索接口目前返回页面已加载的结果，没有已验证的分页游标；首版轮换关键词并按最新排序复查，不宣称可以无限翻页或搜全所有帖子。没有返回正文、登录异常、验证码、响应格式改变都不视为正常空结果。采集动画仅由真实新增Item触发；测试数据只用于隔离测试，不进入生产库。

## Apple Silicon 本机运行

本机测试中，v2.7.4 的 linux/amd64 容器浏览器持续无法获取二维码（40秒及110秒均超时），同版本 darwin-arm64 原生浏览器成功。此环境改用原生连接器；不是通过无限延长超时解决。

原生服务监听 `127.0.0.1:18061`，Docker Desktop 后台通过 `XIAOHONGSHU_URL=http://host.docker.internal:18061` 访问，仍校验内部认证令牌。原容器停止，避免同一账号两套浏览器并行。管理台扫码流程不变。

使用项目官方 release 的 `xiaohongshu-mcp-darwin-arm64`（v2.7.4），浏览器由连接器下载并校验SHA256。`scripts/xiaohongshu_native.py --config <私有配置文件> --runtime <私有运行目录>` 读取 `XIAOHONGSHU_TOKEN`，启动本地二进制 `xiaohongshu-mcp.asset`；密钥不出现在命令行。

本机运行目录在 `~/Library/Application Support/AI_Business_Opportunities/xiaohongshu`，包含连接器、账号Cookie及仅含内部令牌的配置（文件权限0600，目录0700）。由 `~/Library/LaunchAgents/com.aibusiness.xiaohongshu.plist` 管理，用户登录后启动、意外退出自动重启；系统关机或休眠期间不能采集。运行文件与会话均不进Git。连接器安装在Application Support，避免后台服务读取Documents目录受系统权限阻拦。
