# AI 提示词设置

这个隐藏目录存放实际发送给大模型的指令，文件内容为 UTF-8 纯文本（.md）。直接修改对应文件并保存，无需改 Python 代码或重新打包镜像。下一次 AI 调用读取新内容，不缓存；正在进行的请求、已缓存的成功分类、历史审核结果不会自动重做。

macOS Finder 中用 Command + Shift + . 显示隐藏文件。

| 文件 | 用途 | 输出契约（程序校验） |
|---|---|---|
| `product-rule-review.md` | 网络商机表单的 AI 检查建议 | product、synonyms[]、actions[]、notes[]；用户地区由程序保留 |
| `opportunity-review.md` | 各来源候选的买方商机/客户资讯判断 | decision、reason、evidence；允许值见文件 |
| `opportunity-review-repair.md` | 商机证据不连续时的一次纠正 | 与商机判断相同，仍需原文依据 |
| `semantic-dedupe.md` | 近似信息的重复、更新或不同项目判断 | relation、target_id、reason、evidence_new、evidence_existing |
| `geography.md` | 商机地图省级地区识别 | region、basis、place、evidence、reason |
| `geography-repair.md` | 地区证据校验失败时的一次纠正 | 与地区识别相同 |
| `legacy-keyword-review.md` | 旧版关键词检查兼容接口 | name、keywords[]、notes[]；新版表单使用 product-rule-review |

## 怎么修改

1. 先复制要改的文件做备份（备份文件不会被程序读取）。
2. 调整业务范围、判断原则、例子和建议语气。不要删除输出字段要求、改字段名或枚举值；它们是程序读取模型结果的接口。
3. 保存后再发起 AI 检查，或等待后台下一次调用。建议先用规则检查观察改动结果，不要以为保存提示词会自动重审历史数据。
4. 模型输出不符合格式或证据要求时，程序仍拒绝通过；修改提示词不能取消代码中的校验或自动采纳规则建议。

单文件最多64KiB。空文件、缺失文件、非UTF-8文件会使对应AI调用报错；不会静默用另一份提示词，也不会因此默认放行商机。请用编辑器正常保存或先写临时文件再替换，避免保存中途被读取。

## 运行方式

- 本机直接运行：默认读取项目根目录 `.ai-settings/`，不依赖当前工作目录。
- Docker Compose：此目录只读挂载到后端容器 `/app/.ai-settings/`，宿主机修改后容器可读到；不需要重建或重启服务。
- 单独运行后端镜像时，也需挂载目录并设置 `AI_SETTINGS_DIR=/app/.ai-settings`。部署到新服务器必须连同此目录一起复制。
- `AI_SETTINGS_DIR` 可覆盖提示词目录；路径设置改变需要重启进程，但文件内容修改不需要。
- 不在这些文件里放 API Key、Cookie、客户名单或原始商机内容。点开头只是隐藏目录，不是加密。仓库中的默认模板可版本管理；私人定制内容发布前需自行检查。

关键词发现/搜索指数模块尚未实现模型调用。接入时应在此目录新增对应文件，并登记到提示词加载器，不再在业务代码写大段指令。
