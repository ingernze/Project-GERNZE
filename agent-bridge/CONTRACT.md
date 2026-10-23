# Codex莉宝模块与桌面适配契约

本模块用已安装的官方MCP Python SDK 1.27.0（MIT），stdio传输，Skill只负责调用流程。普通Codex、角色会话和桌宠可同时运行；角色会话UUID独立。本模块不实例化旧ConversationStore，因为其初始化会接管owner并中断旧pending请求。

## 已接与待接

已接：第一层人设/基础文件只读；旧电脑版lc_summaries只读，过滤当前epoch/未删除会话；Codex角色原文独立留底；有来源的第三层候选保存、CAS纠正、幂等、撤回防复活。

待2号接回：正式第二层发布只读快照；电脑版把本模块第三层纳入待审显示/检索；第四层把Agent会话纳入书架。手机尚无该模块通道，不能声称双端互通。设置项desktopConsumesAgentTier3暂固定false，2号真正集成后才能调整为宿主实测状态；旧桌面摘要也不能自动冒充已审第二层。

## 权限与来源

MCP没有写第一二层、批准、任意文件路径、SQL或shell的接口。第三层仅写settings.local.json指定的独立agent-memory.sqlite3；L1/L2路径没有模型可传入的写参数。Skill要求只在用户明确开启莉宝模式时记录实际对话，不读取所有Codex历史。调用者提交的原文标agent_reported，不能当作宿主验证的转录或用户已审核事实。来源校验只证明源记录存在，不能证明摘要语义正确，升二层仍需审查。

这限制的是模块接口，不是操作系统权限：普通Codex已有文件工具依然受其原本沙箱/审批控制。不能以MCP工具白名单声称整个Agent在系统层绝对无法写某文件。需要硬隔离时应使用独立受限执行身份/只读挂载；本轮没有扩大沙箱权限或授予自动批准。

## 2号接法

1. 用core.read_agent_working(path)读取独立库（只读，不创建）。保留key、revision、sourceHash、sourceRefs和deleted；tier=3、status=pending、approved=false。撤回条目用于失效处理，不进入回答。重复同key/revision不要重复导入，新的纠正不能被旧版覆盖。
2. 现有库不会自动消费这些内容。桌面要明确把其作为第三层检索资料，不能把函数调用成功等同模型请求已带入。应验证请求实际包含符合条件的合成摘要。
3. 第二层由桌面审查流程原子发布JSON快照（先写同目录临时文件，再替换），settings.local.json的approved_snapshot指定该路径。格式：`{"format":"gernze-approved-snapshot-v1","tier":2,"entries":[{"key":"来源key","revision":"当前版本","body":"已审正文","deleted":false}]}`。保留删除标记；MCP只读，不新增审批工具。未发布/缺失时状态是awaiting_desktop_layer_adapter，不是空记忆。
4. 第四层在agent_turns，原话按session_id/seq归档。可用只读适配纳入月/日书架，时间为UTC ISO，显示按Asia/Shanghai。留底源头是agent_reported，不能和宿主捕获的原文混淆。
5. 不要用agent库替换或改造现有真实用户数据库。所有适配先在独立合成库/候选目录完成，给作者看效果，认可后交主干。

## 使用

直接在当前Codex对话中使用莉宝的人设和记忆，同时继续正常Agent工作。用户本次已明确选择此用法，无需另开角色聊天或进入/退出模式。begin_lily_session仅创建内部存储编号，不创建应用聊天窗口；后续复用返回编号。首次安装后工具目录未必热加载，必要时在MCP设置中重新连接；这只是连接步骤，不是以后必须分开聊天的使用要求。普通Codex对话不会因此全部被自动采集，也没有替换桌宠/手机的DS提供商。

消耗本来Codex会话的额度；本模块不持有聊天API密钥、不另发模型请求。外部SDK只处理本机stdio，结果仅在用户明确调用后交给当前Codex会话。

## 参考与验证

- OpenAI官方MCP：https://learn.chatgpt.com/docs/extend/mcp?surface=cli
- OpenAI技能：https://learn.chatgpt.com/docs/build-skills
- 官方SDK 1.27.0：本机已安装版本，复用FastMCP/ClientSession/stdio_client；未升级到main上的v2接口。
- MCP Memory参考服务器：https://github.com/modelcontextprotocol/servers/tree/main/src/memory。只参考可读资源和受控工具的拆分；它的实体图增删接口不符合本项目一二层只读边界，未安装它或迁移现有库。
- SDK维护仓库：https://github.com/modelcontextprotocol/python-sdk，MIT。上游主分支已有v2接口，不能直接抄给1.27.0；示例路径读取失败，使用已安装1.27.0实际接口与真实握手核对。未编造Star/性能或生产稳定性。

check.py用临时合成库测真实MCP握手和读写。真实模型语义、桌宠请求带入、第二层接回和手机仍未验收；模块测试不代表这些已完成。
