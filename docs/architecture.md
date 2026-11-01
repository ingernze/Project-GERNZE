# GERNZE 现行结构与阅读入口

核对日期：2026-10-31。本文分开描述主干源码、作者日用电脑版、手机与公开发行。2026-10-29电脑日用书架已接入分类资料并启用本地增量接回；这只扩展书架查看，不表示研究聊天或Agent已在日用版启用。源码能力、候选构建和本机部署继续分别记入[制作日志](development-log.md)，记忆权限见[记忆设计](memory-design.md)。

## 当前状态边界

- **电脑日用版**：作者确认及现有部署记录表明，分类书架已有424份资料：见闻101份、兴趣专题293份、大学课程30份；原有已审记忆单列。日用入口及书架增量同步已启用，原聊天、记忆、美术、人设、核心资料、连接和可选模块保留。原聊天库未整体迁移为研究库。
- **研究聊天**：源码已有普通研究资料与课程的单次选材、带来源回答、摘要、核对等能力，但日用电脑版没有启用`ResearchProvider`、普通研究聊天或课程聊天。书架查看不授予聊天用途。
- **手机**：作者确认安装的记录仍为私人1.1.2/code32；10月30日至31日另构建私人code33—35，当前原电脑更新入口提供code35，尚未确认安装。新增分类书架只读接回见闻/兴趣正文与课程目录；课程正文不传，分类缓存不供聊天。研究缓存及Agent缓存属于独立能力，不能混作当前分类书架用途。独立研究身份1.1.2-research.3/code3仍是未真机安装的历史候选。
- **Agent**：显式独立后端、配对导出和手机缓存接收已在源码中，默认不配置，日用入口未启用。手机缓存不进入手机聊天或L2。
- **公开版**：按项目现有发布记录，正式公开版仍为1.1.1。1.1.2公开候选及10月29日本机书架更新均未上传发布；本机生效不等于公开发行。
- 主干接回时已核对10月29日的导入、分类读取、部署、启动及最终状态记录，并确认现用EXE哈希与部署记录一致。记录支持424份资料、导入前后21表不变、schema1保留和当时窗口启动；本次未重新读取私人数据库、调用模型或运行应用测试，不据此声称每份内容已核实或当前进程仍在运行。

## 端与职责

- Windows宿主负责人物、动作、窗口与声音；工作台通过本机HTTP与有限JSON命令连接宿主和SQLite/JSON资料。工作台监听127.0.0.1及随机端口，每次启动有独立会话凭据。
- 桌面聊天位于`src/workbench/companion_chat.py`，API连接与声音专用API分开。现行源码支持多连接的动态密钥管理；Windows凭据标识不因产品名整理而迁移。
- Android工程及手机独立API已存在，入口见README和`mobile/`。桌面侧已有`layer_sync.py`、`phone_archive.py`及配对来源校验。存在接口和单元测试不等于手机端到端或全部机型验收完成。
- `agent-bridge/`为独立Codex MCP桥。普通默认桌面没有消费Agent L3/L4的入口，`desktopConsumesAgentTier3`仍为false；显式`GERNZE_AGENT_PROFILE`可启动独立Agent后端，但不改变普通默认模式或该桥接标志。独立Agent资料不自动进入普通聊天、记忆审批或手机聊天。

## 四层资料与权限

| 层 | 现行入口 | 请求如何使用 |
| --- | --- | --- |
| L1核心 | `system_prompt()`读取本地人设及核心；干净源码使用公开示例 | 固定上下文；普通聊天、摘要和审查接口无权改写 |
| L2已审 | `MemoryLayers.decide/change_approved/context_notes` | 只取有效、未撤回、无同步冲突项；版本/作用域规则仍检查 |
| L3待审 | 原文生成的摘要、合法配对来源，`context_summaries` | 带来源的未确认资料，不自动当作用户事实；独立审查才可批准 |
| L4原文 | `ConversationStore`持久化完整会话；手机原文独立归档 | 近期完整轮、历史检索及书架入口；一次请求不会带全部原文 |

`MemoryModule`/`memory.*`是项目记录接口，不等于聊天四层库。旧手工笔记保留浏览，不会自动升级为L2，旧“加入聊天”勾选和手工写入入口已移除。普通聊天模型不能调用批准操作；用户或已委派的电脑独立审查流程通过各自入口批准具体版本。

更正/撤回使用版本检查，使旧在途回复和派生上下文失效；不承诺撤回已经发往外部API或备份的内容。现行L2更正没有单独永久强制带入旗标，不能声称所有历史纠正无限常驻上下文。

## 聊天与预算调用链

`scene-chat.js` → `chat.reply` → `CompanionChat.reply_request` → 同步有效L2、建立请求轮次 → 按既定设置尝试到期摘要 → `ContextManager.build` → 一次聊天API请求 → 完整性/版本检查 → L4提交。

工作台宿主会接入摘要adapter及独立审查线程；单独实例化CompanionChat默认不接摘要器。摘要或审查可能产生各自的模型调用，本轮没有新增此类调用，也没有自动重试聊天失败。

现行源码的上下文顺序：固定人设/L1、当前输入、局部指令及现有重要/纠正元数据项 → 最近完整轮（默认最多6）→ 命中当前问题的L2 → 相关旧轮 → L3摘要 → 无命中L2补充。每加一项重新计算完整请求预算；保留角色和来源，不切开单轮。六轮保障以固定部分加这六轮能放下为条件；单轮过长则整轮遗漏并记录，其他短轮仍可入选。固定部分超限明确失败。

关键词沿用中文二元词/英文词，并非语义理解。无命中L2最低优先级回填用于保留“现在呢”等跟进的既有行为；预算紧时仍可能漏召回，不承诺无关资料全被排除或全部记忆常驻。`last_context`可核对预算、入选轮次、遗漏和未命中项；它不是模型真实token账单。

桌面当前使用应用估计窗口32768、余量512。普通回复预留700；当前作者消息以有限中文明确详述请求开头、且不含引文标记时预留1800，其他情况仍700。这是可漏判的简单规则，不是完整意图识别；未标来源且无引用边界的粘贴材料仍可能被误判。ContextManager局部预留与实际max_tokens使用同一数值，不改变共享Budget或近期完整轮优先级。此处不是提供方模型规格或精确token计费，较小窗口仍由调用者配置。

现行输出协议要求JSON，emotion/action按既有规则归一化。已移除正文4000字符静默截断；损坏或重复字段的结构化JSON、损坏围栏、超过64000字符正文及length等未完成结束状态失败，不自动重试。完整普通纯文本与缺少finish_reason的旧提供方继续兼容；这不证明该提供方输出真实完整。以花括号/方括号开头的自然文本、围栏纯文本和JSON标量不走纯文本兼容，这是收紧格式后的代价。作者电脑版1.1.2已更新；真实模型在所有输入下的自然详略及所有安装场景并未因此全部验收。

## 按任务找文件

以下路径相对仓库根目录，按当前任务读取直接相关文件。

| 功能 | 先读 | 验证入口 |
| --- | --- | --- |
| 聊天上下文/持久化 | `companion_chat.py`、`context_manager.py`、`conversation_store.py`（均在`src/workbench/`） | `long_chat_integration_test.py`、`context_selection_test.py` |
| 记忆层与审查 | `memory_layers.py`、`desktop_memory_review.py`、`review_admission.py` | `desktop_auto_review_test.py`、`desktop_review_integrity_test.py` |
| 连接与密钥 | `companion_chat.py`连接方法 | `connection_profiles_test.py` |
| 旧笔记兼容同步 | persistent_memory.py、chat_sync.py | memory_sync_test.py（旧笔记不自动进入现行聊天） |
| 手机分层/原文 | `layer_sync.py`、`phone_archive.py` | `phone_sync_test.py`、`tests/alignment/` |
| 书架与历史 | `memory_archive.py`、`research_books.py`、`research_shelf_sync.py`、`static/memory-books.js` | `chat.books.*`/`chat.research.*`契约与来源测试 |
| 普通研究与课程聊天 | `research_context.py`、`study_chat.py`、`research_summaries.py` | `src/workbench/tests/`；默认日用入口未启用 |
| Agent独立桥 | `agent-bridge/core.py`、`CONTRACT.md` | `agent-bridge/check.py`；普通默认桌面消费未接入 |
| Agent桌面后端与缓存 | `src/workbench/agent_memory/`、`docs/agent-runtime.md`、`mobile/src/agent-cache.mjs` | 相关定向检查；不等于日用或真机启用 |

| 功能 | 先读 | 然后按任务读取 | 主要验证 |
| --- | --- | --- | --- |
| 桌面启动、单实例、退出 | `src/desktop_main.py`、`src/app.py` | `src/tray_win32.py`、`src/win_bridge.py` | `src/tests/test_bridge_dispatch.py` |
| 人物美术、缩放与切换 | `src/style_resources.py`、`src/style_controls.py` | `src/app.py`中的帧加载和播放 | `src/tests/test_style_resources.py`（需要图片） |
| 眨眼、睡眠、摆腿与参数 | `src/activity_timing.py`、`src/autonomous_actions.py` | `src/idle_blink.py`、`src/foot_sway.py`、`src/manual_actions.py` | `src/tests/test_activity_timing.py`、`src/tests/test_foot_sway.py` |
| 拖拽、惯性、走路 | `src/grab_sway.py`、`src/character_inertia.py` | `src/walk_trial.py`、`src/walk_controls.py` | `src/tests/test_inertia.py`、`src/tests/test_fourway_walk.py` |
| 浏览器窗口与服务生命周期 | `src/workbench_host.py`、`src/workbench_window.py` | `src/workbench/server.py`、`src/workbench/entrance.py` | `src/tests/test_workbench_window.py`、`src/tests/test_entrance_session.py` |
| 工作台页面和导航 | `src/workbench/static/index.html`、`src/workbench/static/app.js` | `modules.js`（页面）、`runtime.js`（注册及释放）、`frame.js`／`layout.js`／`style.css` | `src/workbench/tests/` |
| 工作台接口 | `src/workbench/server.py`中的CONTROL、`src/workbench/bridge.py`中的CONTRACTS | Handler、validate_call及Bridge.call | `src/tests/test_paper_study.py`、`src/tests/test_activity_timing.py` |
| 六级提示词与汇报 | `src/libao_modules/daily_study.py` | `prompts.py`、`handoff.py`、`security.py` | `src/tests/test_daily_study.py`、`src/tests/test_paper_study.py` |
| SQLite、项目记录、提醒 | `src/libao_modules/core.py` | `registry.py`、`reminders.py`、`capabilities.py` | `src/tests/test_local_snapshot.py`、`src/tests/test_daily_study.py` |
| 固定语音、音量、场景绑定 | `src/scene_voice.py` | `src/voice_bindings_window.py` | `src/tests/test_scene_voice.py`、`src/tests/test_voice_volume.py` |
| 文字转语音、取消与模型选择 | `src/voice_module.py` | `src/voice_text_window.py`、`voice_engine/voice_backend.py`、`engine_worker.py` | `src/tests/test_voice_module.py`、`src/tests/test_workbench_voice.py` |
| 可选模块安装与移除 | `src/optional_modules.py` | `src/module_packages_window.py`、`src/package_optional_modules.py` | `src/tests/test_optional_modules.py` |
| 打包发行、隐私边界 | `src/build_modular_release.ps1`、`source-files.json` | `tools/export_source.py`、`.gitignore`、`docs/source-package.md` | 文件清单与导出校验 |

## 生命周期、素材与验证边界

界面更新归Tk主线程；耗时声音任务在后台执行，模型在独立进程加载。前端释放事件/请求，取消与退出使旧结果失效。固定台词录音属于骨架，语音生成引擎可选；移除后者不得删除固定录音。桌面入口为`desktop_main.py`。内部style2/original、Hecate/hebao及凭据/安装身份兼容标识不随意改名。

本地私人设定不加入公开源码及发行包；运行加载失败应明确报错。媒体、Tk/Win32、GPU、手机、真实API分别需要对应环境验收，文本检查不能替代这些验证。结构修复不重做UI、美术或进度轨道。

参考及实际复用见[复用与来源登记](reuse-and-attribution.md)。后续接回候选要比较当前文件，保留同期更新，不能用候选目录整体覆盖正式工程。

## 可选桌面见闻接线（源码，默认关闭）

WorkbenchServer增加宿主构造参数encounter_enabled=False和encounter_directory=None，经create_desktop_chat接入LocalEncounterProvider。默认不建库或导入见闻存储；启用需宿主提供独立外部账本绝对目录，消息和模型不能选目录或开关。桌面仅复用0.3.3-chat.2的四个账本/读取模块与无副作用包入口，不捆绑Codex探索执行器、MCP服务或浏览环境；后续同步该子集需核对来源版本和哈希。

普通问题按现有词项相关检索，少量完整近期分享问句可用recent，有效选摘再筛相关性，最多三个来源。整块external_encounters及隔离说明在原有内容选完后才尝试加入，共享当前请求700/1800局部预算；不挤掉已选上下文。结果标为低信任外部资料，与用户事实和指令分开，不写人物核心或批准记忆。

已采用资料的在途回答在提交阶段用catalog、provider代次与SQLite短门闩复核；纠正、删除、停用、替换或核对失败使整条回答作废。未采用资料的普通回答不受外部变化影响。既有已发布历史、缓存与自动摘要尚未实现外部来源依赖撤回；不能把在途保护扩大为历史撤回。真实账本未启用，真实模型自然度、EXE/APK和手机消费未验。Agent逐项依赖仍是独立合成实验，未用于此生产流程。

## 分类书架与研究接线

### 电脑日用书架：已启用，仅限查看与资料更新

`research_books.py`通过`chat.research.groups/list/read`提供四组只读投影：已审聊天记忆、见闻、兴趣专题、大学课程。已审记忆继续来自原`lm_approved`；其他三组来自同一资料目录。旧L2没有可靠归因时留在原有已审组，不根据正文猜测分类。

作者日用电脑版已于2026-10-29接入424份分类资料，计数与核实边界见文首。`ResearchBooks.read`要求课程使用`study_material`、其他分类使用`browse`的明确本地查看用途；只读展示不绑定`ResearchProvider`、不发模型请求、不批准L2。课程正文只在主动打开时读取，未自动加入普通聊天；见闻和兴趣也不会因为进入书架而自动进入普通聊天。

普通日用宿主在默认`research_enabled=False`且没有自定义聊天工厂时，可由资料目录中的本机`bookshelf-receipt.json`启用`ResearchShelfSync`。回执必须匹配格式、资料目录身份、命名空间、来源类型和宿主课程映射，并明确`automaticSync=true`。同步器只读取清单明确列出的分类索引、导入包和必要修订历史，核对数量、分类、课程范围、哈希、分片连续性及修订链，整批导入；不完整或未授权交付保留原书架。

启动及打开分类书架时检查后续完整交付，不新增轮询、模型调用或HTTP/模型写入入口。该过程在现有日用聊天库中增加`rc_*`书架表，不构造研究Journal、不升级原聊天库schema，也不改变既有聊天/审批权限。

10月31日电脑和手机共用`memory-books.js`中的专题导航：按明确系列/标题标识将歌单、见闻和课程收纳，未知资料保留单列。分组及检索只使用目录元数据，不改变原条目ID、修订、信任或聊天准入；AI自学仍属于见闻。日用静态文件已更新，重新加载工作台后生效。

手机完整分类书架使用独立`gernze-bookshelf-cache-v1`协议，代码入口为`bookshelf_transfer.py`、`mobile/src/bookshelf-native.mjs`及`bookshelf-cache.mjs`，复用原配对TLS与`layerExchange`。目录冻结、有界动态分页与整目录最终核验后，手机完整校验并原子替换缓存；中断和校验失败保留旧缓存。课程仅目录，不把此通道当作研究摘要、L2/L3或Agent同步。code35已构建并接原更新入口，实际手机安装和本轮WebView显示未确认；此前日期的EXE核对不代替本轮静态文件和手机包核对。


### 研究聊天与摘要：源码已有，日用默认关闭

`research_catalog.py`分开维护目录、条目正文与按版本保存的来源原文；`research_context.py`提供绑定单次用途的宿主适配、延迟历史读取和回答/实际来源依赖同库提交。`create_desktop_chat`及`WorkbenchServer`的`research_enabled`默认False。只有显式研究宿主才构造`ResearchJournal`和`ResearchProvider`，普通日用会话不升级。

课程权限和预算先于正文读取；研究相关轮暂缓旧摘要/L3，原文保留。显式研究会话使用user_version4，旧默认读者及旧研究v2/v3运行时拒绝。`StudyChat`只接受课程，`ResearchChat`只接受普通研究；人物场景书架可选一份用于下一问，发送、移除或关闭后清除。模型和HTTP参数不能自行签发用途或课程权限。

`research_summaries.py`保存研究专用受限增量摘要，元数据和正文分表，记录外部来源、精确父摘要、原文状态与独立覆盖。普通摘要优先，每问最多一次摘要worker；研究摘要在当前明确材料后按余量取用。采用摘要的回答继承依赖并同事务保存；旧审批/同步不接收这些摘要，旧原文covered标记不动。

`research_review.py`复用原审查调度，单独存`rc_summary_reviews`，不等于用户事实审批。`research_transfer.py`在既有配对LayerSync中协商单向完整快照；手机研究缓存使用独立存储。手机源码还有普通研究摘要单次取用、带来源原文上行、电脑整理及核对等能力，但不表示手机课程聊天、任意全历史双向合并或Agent聊天已完成，更不表示已安装到作者手机。

完整接口、各阶段验证和限制见[研究资料接线](research-catalog.md)。独立研究测试入口见`research_preview.py`及[独立测试说明](research-preview.md)；该入口使用独立目录和身份，不是10月29日日用书架更新的同义词。

## Agent桌面后端与手机缓存

`src/desktop_main.py`在显式设置`GERNZE_AGENT_PROFILE`时使用`AgentFactory`和独立资料目录；可选`GERNZE_AGENT_SOURCE_CONFIG`限定一个会话及1至8条明确来源。未设置时继续普通默认后端，不发现或读取Agent库。独立Agent会话库为schema6，不与原聊天库或研究库混用，连接凭据另设命名空间。

Agent回答、实际来源依赖、摘要及撤回协调已接回源码，配套Publisher与手机待核实缓存接收也已存在。该缓存只表示最后一次接回状态，不自动用于手机聊天或L2。默认未配置，作者日用入口未启用；独立电脑/更新EXE和研究身份APK的构建通过不能写成用户设备已接通。启用条件和回退边界见[Agent桌面后端](agent-runtime.md)。
