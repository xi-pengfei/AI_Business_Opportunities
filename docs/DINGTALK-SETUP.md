# 钉钉群接入：明确回复认领后发送下一条

目标群为「西安财纵软件科技有限公司」公司大群。企业内部应用「AI商机智能体」已创建，尚未完成发布、入群和真实消息验收。当前发送关闭，不会向群里自动发送历史信息。

## 认领规则

机器人每次发送一条商机，附唯一 BO 编号。群成员引用对应消息，@AI商机智能体，回复「收到」「同意」「拿到信息了」「认领」或「我来跟进」。第一位有效回复者成为负责人，保存钉钉身份、姓名、认领时间和回复消息标识；随后发送下一条。已读、发送成功和动画完成均不算认领。

群机器人需要被 @ 才能收到对应群消息。引用消息的元数据仍需真实客户端验收；若客户端不提供引用内容，使用「@AI商机智能体 收到 BO-消息中的编号」。不将没有编号关联的泛泛「收到」自动匹配给最新商机。重复回复不改负责人，否定或歧义回复不认领。

## 用户从当前页面继续（2026-11-15）

应用与机器人资料已填写，消息预览图已上传；消息接收模式已选 Stream。机器人配置页底部的「发布」尚未点击，应用仍在开发中。

1. 打开钉钉开发者平台 → 西安财纵软件科技有限公司 → 应用开发 → AI商机智能体 → 机器人，核对名称、简介、描述及消息预览图，保留 Stream 模式，点击底部「发布」保存机器人配置。
2. 进入权限管理，搜索并申请「企业内机器人发送消息权限」。按后台提示由有权限的管理员批准；当前无需通讯录全量读取或群历史消息读取权限。
3. 进入版本管理与发布，新建版本（例如 1.0.0），填写说明「公开需求信息推送与群内认领」，选择公司大群使用人员对应的可用范围，再按后台要求发布企业内版本。
4. 钉钉客户端打开「西安财纵软件科技有限公司」群 → 群设置 → 机器人（部分版本称智能群助手）→ 添加机器人，搜索并添加本应用的「AI商机智能体」，不是添加自定义 Webhook 机器人。如搜索不到，先核对版本发布和人员可用范围。
5. 在开发者平台的凭证与基础信息取得 Client ID / Client Secret，并在机器人配置处取得 RobotCode。填到本机 .env 对应三项即可；不需要在聊天中发送 Secret。
6. 先保持 DINGTALK_ENABLED=false。告知应用已发布并入群后，再完成群会话 ID 获取及接收验证。群名称不等于 openConversationId，当前服务需要该 ID 后才可启用；不要只填群名就开启发送。

## 本机接入配置

1. 为应用添加机器人能力，配置 Stream 接收模式，取得 RobotCode。
2. 按官方发送接口要求开通最小必要权限，发布企业内部版本并将机器人加入目标群。
3. 凭证页取得 Client ID 和 Client Secret，仅保存在本机 .env，不进入聊天、截图或 Git。
4. 通过官方 chooseChat 或目标群的机器人回调确认 openConversationId，不能用群名替代。

```dotenv
DINGTALK_ENABLED=false
DINGTALK_APP_KEY=应用ClientID
DINGTALK_APP_SECRET=应用ClientSecret
DINGTALK_ROBOT_CODE=机器人RobotCode
DINGTALK_CONVERSATION_ID=目标群openConversationId
DINGTALK_GROUP_NAME=西安财纵软件科技有限公司
```

完成配置和目标群核对后才启用 DINGTALK_ENABLED=true，并重建服务环境：

```sh
docker compose up -d --force-recreate api notifier claim-listener
```

启用会从已有有效信息中按入库时间推送一条，属于正式群消息。notifier 独立发送，claim-listener 通过官方 Stream SDK 接收回复，不需要公网回调端口。采集不依赖这两个服务。没有认领时只阻止后续群推送，采集和入库继续。

## 验收和异常

- 推送后从待推送信息库移到下方表，状态为待认领，仍计入未认领积压。
- 引用并 @ 回复后，记录实际认领人，积压减少一条，随后发下一条。
- 两人认领同一条仅首个有效回复生效；纯已读、其他群和无关回复不推进。
- 发送结果不明确时暂停后续推送，不盲目重发；目标群真实有效认领可以确认接收。
- Stream 离线时不能保证回复补投；服务恢复后成员可再次发送明确认领回复。
- 代码模拟测试不等于真实钉钉验收；引用字段形态、权限、群会话和完整往返仍需现场验证。

## 官方依据

- [发送群消息](https://open.dingtalk.com/document/orgapp/the-robot-sends-a-group-message)
- [Stream 协议与群机器人消息](https://open-dingtalk.github.io/developerpedia/docs/learn/stream/protocol/)
- [应用访问凭证](https://open.dingtalk.com/document/orgapp/obtain-the-access_token-of-an-internal-app)
- [选择群](https://open.dingtalk.com/document/orgapp/jsapi-choose-chat)

# 扫码登录与邀请绑定（阶段 2）

登录不再依赖共享账号：管理员先建账号，再发一次性邀请链接；员工打开链接用钉钉扫码完成绑定，此后可直接「钉钉扫码登录」。钉钉身份只挂在 `user_identities`（provider=dingtalk），与密码登录并存、互为补充，用户表不存渠道 ID。

## 一次性配置

1. 钉钉开发者平台 → 应用「AI商机智能体」→ 登录与分享 → 回调域名/回调地址，登记站点回调：
   `https://<站点域名>/dingtalk`（本机联调为 `http://127.0.0.1:5180/dingtalk`）。
   未登记的回调会被授权页直接拒绝。
2. 权限管理申请「通讯录个人信息读权限」（`Contact.User.Read`），否则拿不到 unionId。
3. `.env` 复用机器人同一应用的凭证，并显式写回调地址（缺省时按站点自身 origin 拼 `/dingtalk`）：

```dotenv
DINGTALK_APP_KEY=应用ClientID
DINGTALK_APP_SECRET=应用ClientSecret
DINGTALK_REDIRECT_URI=https://<站点域名>/dingtalk
```

4. 重建 api/web：

```sh
docker compose build api web migrate && docker compose up -d
```

凭证齐备后登录页自动出现「使用钉钉扫码登录」，无需改代码。

## 使用流程

1. 管理员在「系统设置 → 用户管理」建账号（用户名+初始密码）。
2. 点该行「邀请绑定」→ 生成一次性链接（7 天有效，只能用一次；重新生成会立刻作废旧链接）。
3. 把链接发给本人（钉钉里直接发即可）。对方打开后点「使用钉钉扫码完成绑定」，扫码即绑定成功并直接进入系统。
4. 之后本人可以在登录页选择「钉钉扫码登录」，不必记密码。已绑定状态在用户管理表的「钉钉」列可见。

## 规则与边界

- 一个钉钉账号只能绑定一个用户；已被他人占用时返回 409，需管理员先解除。
- 同一用户重新邀请可改绑新的钉钉账号，旧身份自动替换（一人一号，不做多身份并存）。
- 扫码登录只认已绑定账号，不会按手机号/昵称自动建号，避免账号被冒领。
- 邀请令牌一次性、可过期；`used_at` 非空即失效，过期后需重新生成。
- 钉钉返回的 openId 是应用级标识，跨应用会变；unionId 稳定，落库同时保存两者。
- 钉钉未配置时（`DINGTALK_APP_KEY`/`DINGTALK_APP_SECRET` 任一为空），登录页不显示扫码入口，邀请页提示联系管理员。

## 官方依据（扫码登录）

- [获取用户 token](https://open.dingtalk.com/document/orgapp-server/obtain-user-token)
- [获取用户个人信息](https://open.dingtalk.com/document/orgapp-server/dingtalk-retrieve-user-information)
