# 莉宝 Codex 接入插件

此包独立下载，骨架不携带、不自动安装。提供原有本地 stdio MCP 与 Skill，不另开模型，也不把桌宠的 API 配置偷换为 Codex。

Windows 安装：解压后运行“安装.cmd”，准备独立 Python 依赖；随后重启 Codex，在本机插件入口启用“莉宝 Codex 接入”。如已手动连接旧 gernze MCP，先关闭旧连接，避免两个入口重复留底。宿主会要求单独信任提醒钩子，本包不绕过该机制。

默认只有基础角色与空白记忆。本机资料保存在 LocalAppData/GERNZE/CodexPlugin，升级和卸载不清空它。只收集用户明确授权的当前对话；第一、二层经 MCP 只读，第三层仍待审。通用源码不含作者的完整人设、个人资料、真实聊天及配对凭据。

可选手机完成提醒由本机 notifications.json 连接已配对电脑发布器。手机主界面手动开启后，Stop 事件仅提交不含原话的任务完成编号；断线自动关闭，重连不自动开启。本版手机前台接收，退后台或锁屏会暂停，不能当作后台即时推送。钩子未获信任时不会自动运行。

卸载：先在 Codex 关闭插件，再运行“卸载.cmd”移除本插件的本机发现入口；如宿主仍保留安装缓存，在插件页移除。保留所有个人资料，不修改其它连接、全局 Skill 或 notify 配置。

本轮按作者要求未执行安装/卸载、宿主事件或手机实测。结构依据 [OpenAI 插件规范](https://developers.openai.com/plugins/build/plugins)，事件依据 [Hooks](https://learn.chatgpt.com/docs/hooks)。不包含上传、发布或自动信任操作。
