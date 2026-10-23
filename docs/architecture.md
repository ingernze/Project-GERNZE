> 2026-10-20 状态更新：本文下方较早阶段的计划不代表现状。现已存在 Android 工程、手机独立 API、四层记忆和共享书架；以 README、现行源码及 docs/release-1.1.0.md 为准。真机、真实模型和全部机型适配仍需分别验收。

# 莉宝现行结构与阅读入口

## 2026-10-18 记忆设计更新：已批准方向，尚未实现

用户决定改为三层：核心设定由用户控制且回答时必带；审核记忆由用户或其明确委派的审查AI经独立入口写入；日常聊天模型只能修改第三层工作记忆。审查间隔由用户指定，授权审查者批准后晋级，不能静默自动晋级。具体权限、现成项目核对与接续范围见[三层记忆设计](memory-design.md)。下面早期说明保留当时背景，不能把现有手填笔记和摘要认作三层自动积累已实现。


核对日期：2026-10-09。基线为已部署的Windows桌面程序及已上传的源码，不是旧源码候选目录。先读本页，再沿目标功能阅读；不要求先通读全仓库。

## 系统边界

```text
Windows桌面宿主（Tkinter＋Win32）
  ├─角色渲染与动作调度：PNG清单、锚点、定时回调
  ├─工作台宿主：本机HTTP服务 → 浏览器HTML/CSS/JS
  │   └─有限JSON命令 → 数据与设置逻辑 → SQLite／JSON
  └─声音控制
      ├─固定录音 → Windows播放
      └─后台任务 → 独立GPT-SoVITS推理进程 → WAV → 播放
```

工作台仅监听127.0.0.1，端口由系统分配；每次服务启动生成会话凭据。人物页的陪伴聊天API与声音专用API分别配置，均与本机工作台会话凭据分开。应用没有自动长期对话记忆，也没有内部MCP。

## 按任务找文件

以下路径相对仓库根目录。

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

## 两条典型调用链

保存动作设置：`modules.js`收集参数 → `app.js`向`/api/call`提交`behavior.set` → `server.py`校验 → 桌面事件桥通知`app.py` → 保存JSON并调整定时任务。源码中同名命令与参数契约是迁移依据。

保存学习汇报：`modules.js` → `app.js` → `bridge.py`的`daily.save` → `daily_study.py`解析／保存 → `core.py`的SQLite事务。教学提示词与历史参考是数据，不能作为宿主指令执行。

## 生命周期与命名

界面更新归Tk主线程；耗时声音任务在后台执行，模型在独立进程加载。取消与退出使旧结果失效，防止延迟补播。声音空闲约120秒结束自有引擎。前端Scope与AbortController负责切页释放事件、请求与清理函数。

美术第一套是插画，内部ID仍为style2；第二套是像素备用，内部ID为original。不要按旧ID猜展示顺序。声音第一／第二套是另一个编号体系。`desktop_main.py`是当前正式桌面入口；原试验名称已整理。`MemoryModule`和`memory.*`是现有项目记录接口，不等于自动对话记忆。

## 测试与素材边界

Python桌面依赖见根目录requirements文件。前端运行无需npm构建；DOM测试需要Node.js和jsdom，`daily_study.test.cjs`还调用Python夹具，通过HEBAO_PYTHON指定解释器。本仓库尚无jsdom锁版本及package-lock。

涉及真实PNG、WAV、视频、Tk窗口、Win32或GPU的测试需相应资源和平台。独立数据测试与API夹具不能被当成手机版验收。完整人物动作、声音模型、推理引擎依赖和运行环境不在仓库中；当前只有一张F00人物示例图。

## 参考与第三方复用入口

参考资料、已采用组件和发布说明统一见 [复用与来源登记](reuse-and-attribution.md)。候选不等于实际安装，教程许可与组件许可分别核对。


## 2026-10-16 当前边界修订

固定台词的已认可 WAV、播放、音量与触发设置属于骨架。可选模块仅包括学习与语音生成；移除语音生成不得移除固定录音。声音页可保留固定台词入口，但模块安装状态只统计 voice_engine。兼容旧版 fixed_voice 安装路径只用于读取，新的打包脚本将 assets/voice 随骨架打包，不再生成固定语音可选包。旧 EXE 需重新打包后才有此行为，现有录音与用户设置不迁移、不删除。

人物页的纯文字陪伴聊天使用独立的可配置 API 接口，不依赖语音生成引擎；声音模块中的 API 指声音专用对话入口。两者均由用户显式发送才请求。人物系统消息已接回原来确认的人设总稿与核心原则，细节见下节；未逐句审核的60条候选台词不自动启用。最近六轮仍是进程内历史，不是长期记忆或纠错学习。


### 已找回的原人设

2026-10-16找回美术库内2026-09-29已确认总稿、原创人设核心及2026-10-04事实表，替换本轮临时基础语气。运行入口为 src/workbench/companion_persona.md；每次发送聊天请求都读取，缺失或无效时明确报错，不静默退回“只知道名字”。系统输出格式留在 companion_chat.py，与人物设定分开。两种桌面打包脚本都明确带入该文件。

依据：D:/GERNZE美术库/美术资源/Hecate_Persona_Corpus_Received_v02_20261004/unpacked/Hebao_Personality_Corpus_v02/原始资料/人设原件/00_已确认_简版总稿与固定关系.md 与同目录01_莉宝人设核心_从用户定义继续.md。原参考分析包含妃咲、普通赫波、37、远旅及艾琳、安洁莉特的部分特点，只采用已确认的原创原则，不继承参考角色经历；60条candidate台词不自动启用。人设接入不代表长期记忆已实现，也不代表真实API语气已获用户认可。


### 2026-10-16 主动保存的陪伴记忆

人物页新增“记忆（本机）”：用户主动保存、纠正、忘记，单独存于用户数据目录workbench/companion-memory.sqlite3，不复用项目记录、学习数据库或账号级Codex记忆。最多100条有效记录，其中最多6条由用户勾选供聊天参考，重要项优先；本轮一并带入选中的少量记录，没有自动摘要、语义检索、自动记事或主动推送。日期为用户填写的事件/约定日期，不创建提醒。

UUID记录、修订、父修订和来源设备为后续交换预留。纠正须匹配当前版本，避免旧页面覆盖新值；忘记擦除当前正文，只留无正文删除标记，不保存逐版私人正文。SQLite按需开关连接并用事务写入，没有新服务/框架。修改后清空进程内短期对话并让旧的在途回复失效；已经发送的API内容和外部备份无法由此撤回。记忆文本是上下文数据，不能替换人设、输出格式或工具权限。人物与声音API继续独立，未接手机同步、加密配对或APK更新。
